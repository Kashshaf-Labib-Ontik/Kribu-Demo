"""Database operations for durable document ingestion jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentIngestionJob, DocumentIngestionOutbox
from app.identity.contracts import CurrentUser

QUEUED = "queued"
PROCESSING = "processing"
READY = "ready"
QUARANTINED = "quarantined"


async def queue_document_ingestion(
    session: AsyncSession,
    *,
    current_user: CurrentUser,
    document_id: UUID,
    version_id: UUID,
) -> UUID:
    """Insert job and outbox in the caller's already-open document transaction."""
    job_id = uuid4()
    session.add(
        DocumentIngestionJob(
            id=job_id,
            tenant_id=current_user.tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            actor_subject_id=current_user.subject_id,
            state=QUEUED,
            attempt_count=0,
        )
    )
    session.add(
        DocumentIngestionOutbox(
            id=uuid4(), tenant_id=current_user.tenant_id, job_id=job_id, publish_attempt_count=0
        )
    )
    return job_id


async def claim_job(
    session: AsyncSession, *, job_id: UUID, lease_seconds: int
) -> DocumentIngestionJob | None:
    """Claim one queued/expired job. Concurrent Celery deliveries are harmless."""
    now = datetime.now(UTC)
    job = await session.scalar(
        select(DocumentIngestionJob)
        .where(DocumentIngestionJob.id == job_id)
        .with_for_update(skip_locked=True)
    )
    if job is None or job.state == READY or job.state == QUARANTINED:
        return None
    if job.state == PROCESSING and job.lease_expires_at is not None and job.lease_expires_at > now:
        return None
    job.state = PROCESSING
    job.attempt_count += 1
    job.error_code = None
    job.started_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    return job


async def mark_ready(session: AsyncSession, *, job_id: UUID) -> None:
    await session.execute(
        update(DocumentIngestionJob)
        .where(DocumentIngestionJob.id == job_id)
        .values(state=READY, error_code=None, lease_expires_at=None, completed_at=datetime.now(UTC))
    )


async def mark_quarantined(session: AsyncSession, *, job_id: UUID, error_code: str) -> None:
    await session.execute(
        update(DocumentIngestionJob)
        .where(DocumentIngestionJob.id == job_id)
        .values(
            state=QUARANTINED,
            error_code=error_code[:80],
            lease_expires_at=None,
            completed_at=datetime.now(UTC),
        )
    )


async def release_for_retry(session: AsyncSession, *, job_id: UUID) -> None:
    """Make a transient infrastructure failure eligible for the durable dispatcher again."""
    await session.execute(
        update(DocumentIngestionJob)
        .where(DocumentIngestionJob.id == job_id)
        .values(state=QUEUED, lease_expires_at=None, error_code=None)
    )
