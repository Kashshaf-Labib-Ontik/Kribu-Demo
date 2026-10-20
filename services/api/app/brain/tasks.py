"""Celery tasks for durable, idempotent document indexing."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.ai.errors import ModelProviderError
from app.brain.chunking import CHUNKER_VERSION, SourceBlock, chunk_blocks
from app.brain.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    GeminiEmbeddingProvider,
)
from app.brain.indexing import (
    claim_index_job,
    mark_index_failed,
    mark_index_ready,
    release_index_for_retry,
)
from app.brain.models import (
    DocumentIndexGeneration,
    DocumentIndexHead,
    DocumentIndexJob,
    DocumentSearchChunk,
)
from app.core.config import get_settings
from app.core.database import create_session_factory
from app.documents.models import DocumentContentBlock, DocumentExtraction
from app.identity.tenancy import set_trusted_tenant_context
from app.ingestion.celery_app import celery_app
from app.policy.models import ResourceDescriptor

logger = logging.getLogger(__name__)


def _owner_url() -> str:
    owner = get_settings().ingestion_owner_database_url
    if owner is None:
        raise RuntimeError("KRIBU_INGESTION_OWNER_DATABASE_URL is required for the worker")
    return owner.get_secret_value()


async def _dispatch_pending_indexes() -> int:
    engine = create_async_engine(_owner_url())
    try:
        async with engine.begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT o.id, o.job_id
                        FROM document_index_outbox o
                        JOIN document_index_jobs j ON j.id = o.job_id
                        WHERE j.state IN ('queued', 'processing')
                          AND o.available_at <= now()
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
                celery_app.send_task("app.brain.tasks.index_document_task", args=[str(job_id)])
                await connection.execute(
                    text(
                        """
                        UPDATE document_index_outbox
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


async def _trusted_context(job_id: UUID) -> tuple[str, str] | None:
    engine = create_async_engine(_owner_url())
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT tenant_id::text, actor_subject_id "
                        "FROM document_index_jobs WHERE id = :job_id"
                    ),
                    {"job_id": job_id},
                )
            ).one_or_none()
            return None if row is None else (row[0], row[1])
    finally:
        await engine.dispose()


def _runtime_sessions() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    engine = create_async_engine(get_settings().database_url.get_secret_value(), pool_pre_ping=True)
    return create_session_factory(engine), engine


async def _claim_and_load(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    tenant_id: str,
    actor_id: str,
) -> tuple[DocumentIndexJob, DocumentExtraction, str, list[SourceBlock]] | None:
    settings = get_settings()
    async with session_factory() as session, session.begin():
        await set_trusted_tenant_context(session, tenant_id=tenant_id, subject_id=actor_id)
        job = await claim_index_job(
            session, job_id=job_id, lease_seconds=settings.ingestion_task_timeout_seconds + 30
        )
        if job is None:
            return None
        extraction = await session.scalar(
            select(DocumentExtraction).where(DocumentExtraction.id == job.extraction_id)
        )
        title = await session.scalar(
            select(ResourceDescriptor.title).where(ResourceDescriptor.id == job.document_id)
        )
        blocks = (
            await session.scalars(
                select(DocumentContentBlock)
                .where(DocumentContentBlock.extraction_id == job.extraction_id)
                .order_by(DocumentContentBlock.ordinal)
            )
        ).all()
        if extraction is None or title is None:
            await mark_index_failed(session, job_id=job_id, error_code="source_unavailable")
            return None
        source_blocks = [
            SourceBlock(
                id=block.id,
                ordinal=block.ordinal,
                block_type=block.block_type,
                text=block.text,
                locator=block.locator,
            )
            for block in blocks
        ]
        return job, extraction, title, source_blocks


async def _publish_generation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    tenant_id: str,
    actor_id: str,
    chunks: list[object],
    embeddings: list[list[float]],
) -> None:
    from app.brain.contracts import ChunkDraft

    typed_chunks = [chunk for chunk in chunks if isinstance(chunk, ChunkDraft)]
    if len(typed_chunks) != len(chunks) or len(typed_chunks) != len(embeddings):
        raise ValueError("chunk and embedding counts differ")
    async with session_factory() as session, session.begin():
        await set_trusted_tenant_context(session, tenant_id=tenant_id, subject_id=actor_id)
        job = await session.scalar(
            select(DocumentIndexJob).where(DocumentIndexJob.id == job_id).with_for_update()
        )
        if job is None or job.state != "processing":
            return
        existing_head = await session.scalar(
            select(DocumentIndexHead).where(
                DocumentIndexHead.document_version_id == job.document_version_id
            )
        )
        if existing_head is not None:
            existing_generation = await session.scalar(
                select(DocumentIndexGeneration).where(
                    DocumentIndexGeneration.id == existing_head.active_generation_id,
                    DocumentIndexGeneration.index_contract == job.index_contract,
                )
            )
            if existing_generation is not None:
                await mark_index_ready(session, job_id=job_id)
                return

        generation_id = uuid4()
        combined_hash = hashlib.sha256(
            b"".join(chunk.content_hash for chunk in typed_chunks)
        ).digest()
        generation = DocumentIndexGeneration(
            id=generation_id,
            tenant_id=job.tenant_id,
            document_id=job.document_id,
            document_version_id=job.document_version_id,
            extraction_id=job.extraction_id,
            chunker_version=CHUNKER_VERSION,
            embedding_provider=EMBEDDING_PROVIDER,
            embedding_model=EMBEDDING_MODEL,
            embedding_dimension=EMBEDDING_DIMENSION,
            index_contract=job.index_contract,
            content_hash=combined_hash,
            chunk_count=len(typed_chunks),
            state="ready",
            completed_at=datetime.now(UTC),
        )
        session.add(generation)
        await session.flush()
        session.add_all(
            DocumentSearchChunk(
                id=uuid4(),
                tenant_id=job.tenant_id,
                generation_id=generation_id,
                document_id=job.document_id,
                document_version_id=job.document_version_id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                source_references=[ref.model_dump(mode="json") for ref in chunk.source_references],
                content_hash=chunk.content_hash,
                embedding=embedding,
            )
            for chunk, embedding in zip(typed_chunks, embeddings, strict=True)
        )
        await session.flush()
        if existing_head is not None:
            await session.execute(
                update(DocumentIndexGeneration)
                .where(DocumentIndexGeneration.id == existing_head.active_generation_id)
                .values(state="superseded")
            )
        statement = postgresql_insert(DocumentIndexHead).values(
            tenant_id=job.tenant_id,
            document_version_id=job.document_version_id,
            active_generation_id=generation_id,
            updated_at=datetime.now(UTC),
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "document_version_id"],
                set_={
                    "active_generation_id": generation_id,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        await mark_index_ready(session, job_id=job_id)


async def _set_retry_or_failure(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    tenant_id: str,
    actor_id: str,
    retryable: bool,
    error_code: str,
) -> None:
    async with session_factory() as session, session.begin():
        await set_trusted_tenant_context(session, tenant_id=tenant_id, subject_id=actor_id)
        if retryable:
            job = await session.scalar(
                select(DocumentIndexJob).where(DocumentIndexJob.id == job_id)
            )
            attempts = 1 if job is None else max(1, job.attempt_count)
            await release_index_for_retry(
                session, job_id=job_id, delay_seconds=min(300, 2 ** min(attempts, 8))
            )
        else:
            await mark_index_failed(session, job_id=job_id, error_code=error_code)


async def _run_index_task(job_id: UUID) -> None:
    context = await _trusted_context(job_id)
    if context is None:
        return
    tenant_id, actor_id = context
    session_factory, engine = _runtime_sessions()
    provider: GeminiEmbeddingProvider | None = None
    try:
        claimed = await _claim_and_load(
            session_factory, job_id=job_id, tenant_id=tenant_id, actor_id=actor_id
        )
        if claimed is None:
            return
        _, _, title, blocks = claimed
        chunks = chunk_blocks(blocks)
        provider = GeminiEmbeddingProvider(get_settings())
        embeddings = await provider.embed_documents(
            title=title, texts=[chunk.text for chunk in chunks]
        )
        await _publish_generation(
            session_factory,
            job_id=job_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            chunks=list(chunks),
            embeddings=embeddings,
        )
    except ModelProviderError as exc:
        await _set_retry_or_failure(
            session_factory,
            job_id=job_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            retryable=exc.retryable,
            error_code=exc.code,
        )
    except Exception:
        logger.exception("document indexing failed")
        await _set_retry_or_failure(
            session_factory,
            job_id=job_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            retryable=False,
            error_code="index_failed",
        )
    finally:
        if provider is not None:
            await provider.close()
        await engine.dispose()


def dispatch_index_outbox() -> int:
    return asyncio.run(_dispatch_pending_indexes())


def index_document_task(job_id: str) -> None:
    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        logger.warning("discarding index task with invalid job id")
        return
    asyncio.run(_run_index_task(parsed_job_id))


celery_app.task(name="app.brain.tasks.dispatch_index_outbox")(dispatch_index_outbox)
celery_app.task(name="app.brain.tasks.index_document_task")(index_document_task)
