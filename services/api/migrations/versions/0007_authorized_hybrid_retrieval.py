"""Add durable retrieval indexes, exact provenance, and append-only retrieval audits.

Revision ID: 0007_hybrid_retrieval
Revises: 0006_outbox_returning
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_hybrid_retrieval"
down_revision: str | None = "0006_outbox_returning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
SUBJECT = "current_setting('app.user_id', true)"


def _policy(table: str, name: str, command: str, clause: str) -> None:
    op.execute(
        sa.text(f'CREATE POLICY "{table}_{name}" ON "{table}" FOR {command} TO kribu_app {clause}')
    )


def _force_rls(table: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.create_table(
        "document_index_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_subject_id", sa.Text(), nullable=False),
        sa.Column("index_contract", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "extraction_id"],
            ["document_extractions.tenant_id", "document_extractions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_document_index_jobs_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "document_version_id", "index_contract"),
        sa.CheckConstraint(
            "state IN ('queued', 'processing', 'ready', 'failed')",
            name="ck_document_index_jobs_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_document_index_jobs_attempts"),
    )
    op.create_index(
        "ix_document_index_jobs_dispatch",
        "document_index_jobs",
        ["state", "lease_expires_at"],
    )

    op.create_table(
        "document_index_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("publish_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["document_index_jobs.tenant_id", "document_index_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "job_id"),
        sa.CheckConstraint("publish_attempt_count >= 0", name="ck_document_index_outbox_attempts"),
    )
    op.create_index(
        "ix_document_index_outbox_available",
        "document_index_outbox",
        ["available_at"],
    )

    op.create_table(
        "document_index_generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunker_version", sa.String(80), nullable=False),
        sa.Column("embedding_provider", sa.String(40), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("index_contract", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "extraction_id"],
            ["document_extractions.tenant_id", "document_extractions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_document_index_generations_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "document_version_id",
            name="uq_document_index_generations_head_target",
        ),
        sa.CheckConstraint(
            "state IN ('ready', 'superseded', 'failed')",
            name="ck_document_index_generations_state",
        ),
        sa.CheckConstraint("embedding_dimension = 768", name="ck_document_index_dimension"),
        sa.CheckConstraint("chunk_count >= 0", name="ck_document_index_chunk_count"),
    )

    op.create_table(
        "document_search_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_references", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "generation_id"],
            ["document_index_generations.tenant_id", "document_index_generations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "generation_id", "ordinal"),
        sa.CheckConstraint("ordinal >= 1", name="ck_document_search_chunks_ordinal"),
    )
    # Alembic has no built-in pgvector type. Convert the placeholder in the same migration.
    op.execute(
        sa.text(
            "ALTER TABLE document_search_chunks ALTER COLUMN embedding "
            "TYPE vector(768) USING embedding::vector"
        )
    )
    op.create_index(
        "ix_document_search_chunks_lookup",
        "document_search_chunks",
        ["tenant_id", "document_id", "document_version_id", "generation_id"],
    )
    op.create_index(
        "ix_document_search_chunks_fts",
        "document_search_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_document_search_chunks_embedding_hnsw "
            "ON document_search_chunks USING hnsw (embedding vector_cosine_ops)"
        )
    )

    op.create_table(
        "document_index_heads",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("active_generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_version_id"],
            ["document_versions.tenant_id", "document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "active_generation_id", "document_version_id"],
            [
                "document_index_generations.tenant_id",
                "document_index_generations.id",
                "document_index_generations.document_version_id",
            ],
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "retrieval_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_subject_id", sa.Text(), nullable=False),
        sa.Column("retrieval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("policy_version", sa.String(80)),
        sa.Column("embedding_provider", sa.String(40), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("chunker_version", sa.String(80), nullable=False),
        sa.Column("safe_filters", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "retrieval_id"),
        sa.CheckConstraint("mode = 'hybrid'", name="ck_retrieval_audit_mode"),
        sa.CheckConstraint("result_count >= 0", name="ck_retrieval_audit_result_count"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_retrieval_audit_duration"),
    )

    tables = (
        "document_index_jobs",
        "document_index_outbox",
        "document_index_generations",
        "document_search_chunks",
        "document_index_heads",
        "retrieval_audit_events",
    )
    for table in tables:
        _force_rls(table)
        _policy(table, "select", "SELECT", f"USING (tenant_id = {TENANT})")

    _policy(
        "document_index_jobs",
        "insert",
        "INSERT",
        f"WITH CHECK (tenant_id = {TENANT} AND actor_subject_id = {SUBJECT})",
    )
    _policy(
        "document_index_jobs",
        "update",
        "UPDATE",
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})",
    )
    _policy("document_index_outbox", "insert", "INSERT", f"WITH CHECK (tenant_id = {TENANT})")
    _policy(
        "document_index_outbox",
        "update",
        "UPDATE",
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})",
    )
    _policy("document_index_generations", "insert", "INSERT", f"WITH CHECK (tenant_id = {TENANT})")
    _policy(
        "document_index_generations",
        "update",
        "UPDATE",
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})",
    )
    _policy("document_search_chunks", "insert", "INSERT", f"WITH CHECK (tenant_id = {TENANT})")
    _policy("document_index_heads", "insert", "INSERT", f"WITH CHECK (tenant_id = {TENANT})")
    _policy(
        "document_index_heads",
        "update",
        "UPDATE",
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})",
    )
    _policy(
        "retrieval_audit_events",
        "insert",
        "INSERT",
        f"WITH CHECK (tenant_id = {TENANT} AND actor_subject_id = {SUBJECT})",
    )

    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON document_index_jobs TO kribu_app"))
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON document_index_outbox TO kribu_app"))
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON document_index_generations TO kribu_app"))
    op.execute(sa.text("GRANT SELECT, INSERT ON document_search_chunks TO kribu_app"))
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON document_index_heads TO kribu_app"))
    op.execute(sa.text("GRANT SELECT, INSERT ON retrieval_audit_events TO kribu_app"))

    # Existing Iteration 6 extractions are queued without touching immutable originals.
    op.execute(
        sa.text(
            """
            WITH pending AS (
                SELECT gen_random_uuid() AS job_id,
                       e.tenant_id,
                       e.document_id,
                       e.document_version_id,
                       e.id AS extraction_id,
                       j.actor_subject_id
                FROM document_extractions e
                JOIN document_ingestion_jobs j
                  ON j.tenant_id = e.tenant_id
                 AND j.document_version_id = e.document_version_id
                WHERE j.state = 'ready'
            ), inserted AS (
                INSERT INTO document_index_jobs (
                    id, tenant_id, document_id, document_version_id, extraction_id,
                    actor_subject_id, index_contract, state
                )
                SELECT job_id, tenant_id, document_id, document_version_id, extraction_id,
                       actor_subject_id,
                       'gemini:gemini-embedding-2:768:question-answering-v1:structure-v1',
                       'queued'
                FROM pending
                ON CONFLICT (tenant_id, document_version_id, index_contract) DO NOTHING
                RETURNING id, tenant_id
            )
            INSERT INTO document_index_outbox (id, tenant_id, job_id)
            SELECT gen_random_uuid(), tenant_id, id FROM inserted
            """
        )
    )


def downgrade() -> None:
    op.drop_table("retrieval_audit_events")
    op.drop_table("document_index_heads")
    op.drop_index("ix_document_search_chunks_embedding_hnsw", table_name="document_search_chunks")
    op.drop_table("document_search_chunks")
    op.drop_table("document_index_generations")
    op.drop_table("document_index_outbox")
    op.drop_table("document_index_jobs")
