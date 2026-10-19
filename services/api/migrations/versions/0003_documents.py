"""Add document upload lifecycle: documents, immutable versions, and upload idempotency.

A document is a Guard resource: its ``resource_descriptors`` row and ACL grants are the
authorization anchor, and every version inherits that ACL. Versions are append-only for the
runtime role; the only runtime UPDATE is the per-document version counter.

Revision ID: 0003_documents
Revises: 0002_guard_resources
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_documents"
down_revision: str | None = "0002_guard_resources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
SUBJECT = "current_setting('app.user_id', true)"


def _policy(
    table: str, name: str, command: str, clause: str, *, restrictive: bool = False
) -> None:
    kind = "AS RESTRICTIVE " if restrictive else ""
    op.execute(
        sa.text(
            f'CREATE POLICY "{table}_{name}" ON "{table}" {kind}'
            f"FOR {command} TO kribu_app {clause}"
        )
    )


def _force_rls(table: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_resource_acl_grants_principal_action",
        "resource_acl_grants",
        ["tenant_id", "resource_id", "principal_type", "principal_id", "action"],
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(40)),
        sa.Column("project", sa.String(200)),
        sa.Column("document_date", sa.Date()),
        sa.Column("latest_version_number", sa.Integer(), nullable=False),
        sa.Column("created_by_subject_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "id"],
            ["resource_descriptors.tenant_id", "resource_descriptors.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.CheckConstraint("domain IN ('ngo', 'hr', 'complaints')", name="ck_documents_domain"),
        sa.CheckConstraint("latest_version_number >= 1", name="ck_documents_latest_version"),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("sha256", postgresql.BYTEA(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by_subject_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("document_id", "version_number"),
        sa.CheckConstraint("octet_length(sha256) = 32", name="ck_document_versions_sha256"),
        sa.CheckConstraint("size_bytes > 0", name="ck_document_versions_size"),
        sa.CheckConstraint("version_number >= 1", name="ck_document_versions_number"),
        sa.CheckConstraint("status IN ('stored')", name="ck_document_versions_status"),
    )
    op.create_index(
        "ix_document_versions_tenant_sha256", "document_versions", ["tenant_id", "sha256"]
    )

    op.create_table(
        "upload_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_subject_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("route", sa.String(40), nullable=False),
        sa.Column("request_fingerprint", postgresql.BYTEA(), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "actor_subject_id", "idempotency_key"),
    )

    # Runtime writes are tenant-scoped and attributed to the acting subject.
    _force_rls("documents")
    _policy("documents", "select", "SELECT", f"USING (tenant_id = {TENANT})")
    _policy(
        "documents",
        "insert",
        "INSERT",
        f"WITH CHECK (tenant_id = {TENANT} AND created_by_subject_id = {SUBJECT})",
    )
    _policy(
        "documents",
        "update",
        "UPDATE",
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})",
    )
    op.execute(sa.text('GRANT SELECT, INSERT ON TABLE "documents" TO kribu_app'))
    op.execute(sa.text('GRANT UPDATE (latest_version_number) ON TABLE "documents" TO kribu_app'))
    # The counter only ever advances by one, whoever issues the UPDATE.
    op.execute(
        sa.text(
            """
            CREATE FUNCTION documents_version_counter_guard() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.latest_version_number <> OLD.latest_version_number + 1 THEN
                    RAISE EXCEPTION 'latest_version_number may only advance by one'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER documents_version_counter_guard "
            "BEFORE UPDATE OF latest_version_number ON documents "
            "FOR EACH ROW EXECUTE FUNCTION documents_version_counter_guard()"
        )
    )

    _force_rls("document_versions")
    _policy("document_versions", "select", "SELECT", f"USING (tenant_id = {TENANT})")
    _policy(
        "document_versions",
        "insert",
        "INSERT",
        f"WITH CHECK (tenant_id = {TENANT} AND created_by_subject_id = {SUBJECT})",
    )
    op.execute(sa.text('GRANT SELECT, INSERT ON TABLE "document_versions" TO kribu_app'))

    # Stored upload responses are private to the subject that sent the request.
    actor_scope = f"tenant_id = {TENANT} AND actor_subject_id = {SUBJECT}"
    _force_rls("upload_requests")
    _policy("upload_requests", "select", "SELECT", f"USING ({actor_scope})")
    _policy("upload_requests", "insert", "INSERT", f"WITH CHECK ({actor_scope})")
    op.execute(sa.text('GRANT SELECT, INSERT ON TABLE "upload_requests" TO kribu_app'))

    # Uploads create the Guard resource and its ACL. The 0002 FOR ALL policies scope rows to the
    # tenant; these restrictive policies also bind new rows to the acting subject, so the runtime
    # role cannot forge an owner or grant itself access to someone else's resource.
    _policy(
        "resource_descriptors",
        "insert_owner",
        "INSERT",
        f"WITH CHECK (owner_subject_id = {SUBJECT})",
        restrictive=True,
    )
    _policy(
        "resource_acl_grants",
        "insert_owner",
        "INSERT",
        "WITH CHECK (resource_id IN (SELECT d.id FROM resource_descriptors d "
        f"WHERE d.tenant_id = {TENANT} AND d.owner_subject_id = {SUBJECT}))",
        restrictive=True,
    )
    op.execute(sa.text('GRANT INSERT ON TABLE "resource_descriptors" TO kribu_app'))
    op.execute(sa.text('GRANT INSERT ON TABLE "resource_acl_grants" TO kribu_app'))


def downgrade() -> None:
    op.execute(sa.text('REVOKE INSERT ON TABLE "resource_acl_grants" FROM kribu_app'))
    op.execute(sa.text('REVOKE INSERT ON TABLE "resource_descriptors" FROM kribu_app'))
    op.execute(
        sa.text('DROP POLICY "resource_acl_grants_insert_owner" ON "resource_acl_grants"')
    )
    op.execute(
        sa.text('DROP POLICY "resource_descriptors_insert_owner" ON "resource_descriptors"')
    )
    op.drop_table("upload_requests")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.execute(sa.text("DROP FUNCTION documents_version_counter_guard()"))
    op.drop_constraint(
        "uq_resource_acl_grants_principal_action", "resource_acl_grants", type_="unique"
    )
