"""Durable index job state and atomic generation publication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.embeddings import INDEX_CONTRACT
from app.brain.models import DocumentIndexJob, DocumentIndexOutbox

INDEX_QUEUED = "queued"
INDEX_PROCESSING = "processing"
INDEX_READY = "ready"
INDEX_FAILED = "failed"


async def queue_document_index(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_subject_id: str,
    document_id: UUID,
    version_id: UUID,
    extraction_id: UUID,
) -> UUID:
    existing = await session.scalar(
        select(DocumentIndexJob.id).where(
            DocumentIndexJob.tenant_id == tenant_id,
            DocumentIndexJob.document_version_id == version_id,
            DocumentIndexJob.index_contract == INDEX_CONTRACT,
        )
    )
    if existing is not None:
        return existing
    job_id = uuid4()
    session.add(
        DocumentIndexJob(
            id=job_id,
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            extraction_id=extraction_id,
            actor_subject_id=actor_subject_id,
            index_contract=INDEX_CONTRACT,
            state=INDEX_QUEUED,
            attempt_count=0,
        )
    )
    session.add(
        DocumentIndexOutbox(id=uuid4(), tenant_id=tenant_id, job_id=job_id, publish_attempt_count=0)
    )
    return job_id


async def claim_index_job(
    session: AsyncSession, *, job_id: UUID, lease_seconds: int
) -> DocumentIndexJob | None:
    now = datetime.now(UTC)
    job = await session.scalar(
        select(DocumentIndexJob)
        .where(DocumentIndexJob.id == job_id)
        .with_for_update(skip_locked=True)
    )
    if job is None or job.state in {INDEX_READY, INDEX_FAILED}:
        return None
    if (
        job.state == INDEX_PROCESSING
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    ):
        return None
    job.state = INDEX_PROCESSING
    job.attempt_count += 1
    job.error_code = None
    job.started_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    return job


async def mark_index_ready(session: AsyncSession, *, job_id: UUID) -> None:
    await session.execute(
        update(DocumentIndexJob)
        .where(DocumentIndexJob.id == job_id)
        .values(
            state=INDEX_READY,
            error_code=None,
            lease_expires_at=None,
            completed_at=datetime.now(UTC),
        )
    )


async def mark_index_failed(session: AsyncSession, *, job_id: UUID, error_code: str) -> None:
    await session.execute(
        update(DocumentIndexJob)
        .where(DocumentIndexJob.id == job_id)
        .values(
            state=INDEX_FAILED,
            error_code=error_code[:80],
            lease_expires_at=None,
            completed_at=datetime.now(UTC),
        )
    )


async def release_index_for_retry(
    session: AsyncSession, *, job_id: UUID, delay_seconds: int
) -> None:
    await session.execute(
        update(DocumentIndexJob)
        .where(DocumentIndexJob.id == job_id)
        .values(state=INDEX_QUEUED, lease_expires_at=None, error_code=None)
    )
    await session.execute(
        update(DocumentIndexOutbox)
        .where(DocumentIndexOutbox.job_id == job_id)
        .values(available_at=datetime.now(UTC) + timedelta(seconds=delay_seconds))
    )
