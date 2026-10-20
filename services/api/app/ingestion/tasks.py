"""Celery tasks: dispatch durable outbox records and publish complete parses atomically."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from celery.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.database import create_session_factory
from app.documents.errors import DocumentStoreUnavailableError
from app.documents.models import (
    DocumentContentBlock,
    DocumentExtraction,
    DocumentIngestionJob,
    DocumentVersion,
)
from app.documents.parsing import (
    NORMALIZATION_VERSION,
    ParseQuarantinedError,
    ParseResult,
    parse_document,
)
from app.documents.storage import LocalFileObjectStore
from app.identity.tenancy import set_trusted_tenant_context
from app.ingestion.celery_app import celery_app
from app.ingestion.service import claim_job, mark_quarantined, mark_ready, release_for_retry

logger = logging.getLogger(__name__)


def _owner_url() -> str:
    settings = get_settings()
    owner = settings.ingestion_owner_database_url
    if owner is None:
        raise RuntimeError("KRIBU_INGESTION_OWNER_DATABASE_URL is required for the worker")
    return owner.get_secret_value()


async def _dispatch_pending() -> int:
    """Republish queued or expired work. Duplicate messages are safe by ``claim_job``."""
    engine = create_async_engine(_owner_url())
    try:
        async with engine.begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT o.id, o.job_id
                        FROM document_ingestion_outbox o
                        JOIN document_ingestion_jobs j ON j.id = o.job_id
                        WHERE j.state IN ('queued', 'processing')
                          AND (o.last_published_at IS NULL
                               OR o.last_published_at < now() - interval '30 seconds')
                        ORDER BY o.available_at, o.created_at
                        FOR UPDATE OF o SKIP LOCKED
                        LIMIT 20
                        """
                    )
                )
            ).all()
            for outbox_id, job_id in rows:
                celery_app.send_task("app.ingestion.tasks.parse_document_task", args=[str(job_id)])
                await connection.execute(
                    text(
                        """
                        UPDATE document_ingestion_outbox
                        SET last_published_at = now(),
                            publish_attempt_count = publish_attempt_count + 1
                        WHERE id = :id
                        """
                    ),
                    {"id": outbox_id},
                )
            return len(rows)
    finally:
        await engine.dispose()


async def _trusted_job_context(job_id: UUID) -> tuple[str, str] | None:
    """Resolve tenant/actor only from the persisted job, never Celery arguments."""
    engine = create_async_engine(_owner_url())
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT tenant_id::text, actor_subject_id
                        FROM document_ingestion_jobs
                        WHERE id = :job_id
                        """
                    ),
                    {"job_id": job_id},
                )
            ).one_or_none()
            return None if row is None else (row[0], row[1])
    finally:
        await engine.dispose()


def _runtime_sessions() -> tuple[
    async_sessionmaker[AsyncSession], LocalFileObjectStore, AsyncEngine
]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    return (
        create_session_factory(engine),
        LocalFileObjectStore(settings.document_store_path),
        engine,
    )


async def _claim_and_load(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    tenant_id: str,
    actor_id: str,
) -> tuple[DocumentIngestionJob, DocumentVersion] | None:
    settings = get_settings()
    async with session_factory() as session, session.begin():
        await set_trusted_tenant_context(session, tenant_id=tenant_id, subject_id=actor_id)
        job = await claim_job(
            session, job_id=job_id, lease_seconds=settings.ingestion_task_timeout_seconds + 30
        )
        if job is None:
            return None
        version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == job.document_version_id,
                DocumentVersion.tenant_id == job.tenant_id,
            )
        )
        if version is None:
            await mark_quarantined(session, job_id=job.id, error_code="version_unavailable")
            return None
        return job, version


async def _publish_parse(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    tenant_id: str,
    actor_id: str,
    result: ParseResult,
) -> None:
    parsed = result
    async with session_factory() as session, session.begin():
        await set_trusted_tenant_context(session, tenant_id=tenant_id, subject_id=actor_id)
        job = await session.scalar(
            select(DocumentIngestionJob).where(DocumentIngestionJob.id == job_id)
        )
        if job is None or job.state != "processing":
            return
        existing = await session.scalar(
            select(DocumentExtraction).where(
                DocumentExtraction.document_version_id == job.document_version_id,
                DocumentExtraction.tenant_id == job.tenant_id,
            )
        )
        if existing is not None:
            await mark_ready(session, job_id=job_id)
            return
        extraction = DocumentExtraction(
            id=uuid4(),
            tenant_id=job.tenant_id,
            document_id=job.document_id,
            document_version_id=job.document_version_id,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            normalization_version=NORMALIZATION_VERSION,
            block_count=len(parsed.blocks),
        )
        session.add(extraction)
        # Blocks use explicit foreign-key UUIDs rather than an ORM relationship, so flush the
        # parent before adding them. The surrounding transaction still publishes all derived
        # content atomically.
        await session.flush()
        session.add_all(
            DocumentContentBlock(
                id=uuid4(),
                tenant_id=job.tenant_id,
                extraction_id=extraction.id,
                document_id=job.document_id,
                document_version_id=job.document_version_id,
                ordinal=block.ordinal,
                block_type=block.block_type,
                text=block.text,
                locator=block.locator,
            )
            for block in parsed.blocks
        )
        await mark_ready(session, job_id=job_id)


async def _quarantine(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    tenant_id: str,
    actor_id: str,
    error_code: str,
) -> None:
    async with session_factory() as session, session.begin():
        await set_trusted_tenant_context(session, tenant_id=tenant_id, subject_id=actor_id)
        await mark_quarantined(session, job_id=job_id, error_code=error_code)


async def _release_for_retry(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    tenant_id: str,
    actor_id: str,
) -> None:
    async with session_factory() as session, session.begin():
        await set_trusted_tenant_context(session, tenant_id=tenant_id, subject_id=actor_id)
        await release_for_retry(session, job_id=job_id)


def dispatch_ingestion_outbox() -> int:
    return asyncio.run(_dispatch_pending())


async def _run_parse_task(parsed_job_id: UUID) -> None:
    """Run a parse task on one event loop so asyncpg connections remain loop-local."""
    context = await _trusted_job_context(parsed_job_id)
    if context is None:
        return
    tenant_id, actor_id = context
    session_factory, store, engine = _runtime_sessions()
    try:
        claimed = await _claim_and_load(
            session_factory, job_id=parsed_job_id, tenant_id=tenant_id, actor_id=actor_id
        )
        if claimed is None:
            return
        job, document_version = claimed
        data = store.read(document_version.storage_key)
        settings = get_settings()
        parsed = parse_document(
            data=data,
            filename=document_version.original_filename,
            max_pdf_pages=settings.ingestion_max_pdf_pages,
            max_content_units=settings.ingestion_max_content_units,
        )
        await _publish_parse(
            session_factory,
            job_id=job.id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            result=parsed,
        )
    except DocumentStoreUnavailableError:
        await _release_for_retry(
            session_factory,
            job_id=parsed_job_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
        )
        raise
    except ParseQuarantinedError as exc:
        await _quarantine(
            session_factory,
            job_id=parsed_job_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            error_code=exc.code,
        )
    except SoftTimeLimitExceeded:
        await _quarantine(
            session_factory,
            job_id=parsed_job_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            error_code="parse_timeout",
        )
    except Exception:
        logger.exception("document ingestion failed")
        await _quarantine(
            session_factory,
            job_id=parsed_job_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            error_code="parse_failed",
        )
    finally:
        # Each task owns its engine pool; Celery's single worker keeps local memory bounded.
        await engine.dispose()


def parse_document_task(_task: object, job_id: str) -> None:
    """Parse one job. The only queue argument is an opaque server-created UUID."""
    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        logger.warning("discarding ingestion task with invalid job id")
        return
    asyncio.run(_run_parse_task(parsed_job_id))


celery_app.task(name="app.ingestion.tasks.dispatch_ingestion_outbox")(dispatch_ingestion_outbox)
celery_app.task(
    bind=True,
    name="app.ingestion.tasks.parse_document_task",
    autoretry_for=(DocumentStoreUnavailableError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)(parse_document_task)
