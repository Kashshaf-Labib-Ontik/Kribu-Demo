from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DocumentIndexJob(Base):
    __tablename__ = "document_index_jobs"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "document_id"], ["documents.tenant_id", "documents.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "extraction_id"],
            ["document_extractions.tenant_id", "document_extractions.id"],
        ),
        UniqueConstraint("tenant_id", "id", name="uq_document_index_jobs_tenant_id_id"),
        UniqueConstraint("tenant_id", "document_version_id", "index_contract"),
        Index("ix_document_index_jobs_dispatch", "state", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    extraction_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    actor_subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    index_contract: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentIndexOutbox(Base):
    __tablename__ = "document_index_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["document_index_jobs.tenant_id", "document_index_jobs.id"],
        ),
        UniqueConstraint("tenant_id", "job_id"),
        Index("ix_document_index_outbox_available", "available_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    publish_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentIndexGeneration(Base):
    __tablename__ = "document_index_generations"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "document_id"], ["documents.tenant_id", "documents.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "extraction_id"],
            ["document_extractions.tenant_id", "document_extractions.id"],
        ),
        UniqueConstraint("tenant_id", "id", name="uq_document_index_generations_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "id",
            "document_version_id",
            name="uq_document_index_generations_head_target",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    extraction_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    index_contract: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentSearchChunk(Base):
    __tablename__ = "document_search_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "generation_id"],
            ["document_index_generations.tenant_id", "document_index_generations.id"],
        ),
        UniqueConstraint("tenant_id", "generation_id", "ordinal"),
        Index(
            "ix_document_search_chunks_lookup",
            "tenant_id",
            "document_id",
            "document_version_id",
            "generation_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    generation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    search_vector: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentIndexHead(Base):
    __tablename__ = "document_index_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "active_generation_id", "document_version_id"],
            [
                "document_index_generations.tenant_id",
                "document_index_generations.id",
                "document_index_generations.document_version_id",
            ],
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    active_generation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RetrievalAuditEvent(Base):
    __tablename__ = "retrieval_audit_events"
    __table_args__ = (UniqueConstraint("tenant_id", "retrieval_id"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    actor_subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    policy_version: Mapped[str | None] = mapped_column(String(80))
    embedding_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(80), nullable=False)
    safe_filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
