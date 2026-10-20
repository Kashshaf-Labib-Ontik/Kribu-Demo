"""Add durable document ingestion, normalized blocks, and exact source provenance.

Original uploads remain immutable ``document_versions`` rows.  This revision stores derived
content separately, so a failed parser cannot make a partial representation appear complete.

Revision ID: 0005_document_provenance
Revises: 0004_upgrade_compatibility
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_document_provenance"
down_revision: str | None = "0004_upgrade_compatibility"
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
    op.create_table(
        "document_ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_subject_id", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("tenant_id", "id", name="uq_document_ingestion_jobs_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "document_version_id"),
        sa.CheckConstraint(
            "state IN ('queued', 'processing', 'ready', 'quarantined')",
            name="ck_document_ingestion_jobs_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_document_ingestion_jobs_attempts"),
    )
    op.create_index(
        "ix_document_ingestion_jobs_dispatch",
        "document_ingestion_jobs",
        ["state", "lease_expires_at"],
    )

    op.create_table(
        "document_ingestion_outbox",
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
            ["document_ingestion_jobs.tenant_id", "document_ingestion_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "job_id"),
        sa.CheckConstraint(
            "publish_attempt_count >= 0", name="ck_document_ingestion_outbox_attempts"
        ),
    )
    op.create_index(
        "ix_document_ingestion_outbox_available", "document_ingestion_outbox", ["available_at"]
    )

    op.create_table(
        "document_extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parser_name", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("normalization_version", sa.String(40), nullable=False),
        sa.Column("block_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
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
        sa.UniqueConstraint("tenant_id", "id", name="uq_document_extractions_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "document_version_id"),
        sa.CheckConstraint("block_count >= 0", name="ck_document_extractions_block_count"),
    )

    op.create_table(
        "document_content_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(40), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "extraction_id"],
            ["document_extractions.tenant_id", "document_extractions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "extraction_id", "ordinal"),
        sa.CheckConstraint("ordinal >= 1", name="ck_document_content_blocks_ordinal"),
    )
    op.create_index(
        "ix_document_content_blocks_preview",
        "document_content_blocks",
        ["tenant_id", "document_version_id", "ordinal"],
    )

    for table in (
        "document_ingestion_jobs",
        "document_ingestion_outbox",
        "document_extractions",
        "document_content_blocks",
    ):
        _force_rls(table)

    _policy("document_ingestion_jobs", "select", "SELECT", f"USING (tenant_id = {TENANT})")
    _policy(
        "document_ingestion_jobs",
        "insert",
        "INSERT",
        f"WITH CHECK (tenant_id = {TENANT} AND actor_subject_id = {SUBJECT})",
    )
    _policy(
        "document_ingestion_jobs",
        "update",
        "UPDATE",
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})",
    )
    _policy("document_ingestion_outbox", "insert", "INSERT", f"WITH CHECK (tenant_id = {TENANT})")
    _policy("document_extractions", "select", "SELECT", f"USING (tenant_id = {TENANT})")
    _policy("document_extractions", "insert", "INSERT", f"WITH CHECK (tenant_id = {TENANT})")
    _policy("document_content_blocks", "select", "SELECT", f"USING (tenant_id = {TENANT})")
    _policy("document_content_blocks", "insert", "INSERT", f"WITH CHECK (tenant_id = {TENANT})")

    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON document_ingestion_jobs TO kribu_app"))
    op.execute(sa.text("GRANT INSERT ON document_ingestion_outbox TO kribu_app"))
    op.execute(
        sa.text(
            "GRANT SELECT, INSERT ON document_extractions, document_content_blocks TO kribu_app"
        )
    )


def downgrade() -> None:
    op.drop_table("document_content_blocks")
    op.drop_table("document_extractions")
    op.drop_table("document_ingestion_outbox")
    op.drop_table("document_ingestion_jobs")
