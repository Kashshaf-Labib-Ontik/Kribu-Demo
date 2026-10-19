"""Add canonical resource attributes, ACL grants, demo content, and decision audit.

Schema only. Synthetic demo rows are inserted by ``scripts/seed_demo.py``.

Revision ID: 0002_guard_resources
Revises: 0001_identity_tenant
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_guard_resources"
down_revision: str | None = "0001_identity_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_tenant_rls(table_name: str, *, audit: bool = False) -> None:
    tenant_setting = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    user_setting = "current_setting('app.user_id', true)"
    op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
    if audit:
        op.execute(
            sa.text(
                f'CREATE POLICY "{table_name}_select" ON "{table_name}" FOR SELECT TO kribu_app '
                f"USING (tenant_id = {tenant_setting})"
            )
        )
        op.execute(
            sa.text(
                f'CREATE POLICY "{table_name}_insert" ON "{table_name}" FOR INSERT TO kribu_app '
                f"WITH CHECK (tenant_id = {tenant_setting} AND actor_subject_id = {user_setting})"
            )
        )
        op.execute(sa.text(f'GRANT SELECT, INSERT ON TABLE "{table_name}" TO kribu_app'))
    else:
        op.execute(
            sa.text(
                f'CREATE POLICY "{table_name}_tenant_isolation" ON "{table_name}" '
                f"FOR ALL TO kribu_app USING (tenant_id = {tenant_setting}) "
                f"WITH CHECK (tenant_id = {tenant_setting})"
            )
        )
        # Authorization metadata is read-only at runtime; feature migrations grant writes.
        op.execute(sa.text(f'GRANT SELECT ON TABLE "{table_name}" TO kribu_app'))


def upgrade() -> None:
    op.create_table(
        "resource_descriptors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("classification", sa.String(80), nullable=False),
        sa.Column("department", sa.String(120)),
        sa.Column("owner_subject_id", sa.Text()),
        sa.Column("title", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("ix_resource_descriptors_tenant_id", "resource_descriptors", ["tenant_id"])

    op.create_table(
        "resource_acl_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_type", sa.String(40), nullable=False),
        sa.Column("principal_id", sa.String(160), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource_descriptors.tenant_id", "resource_descriptors.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_resource_acl_grants_tenant_id", "resource_acl_grants", ["tenant_id"])
    op.create_index("ix_resource_acl_grants_resource_id", "resource_acl_grants", ["resource_id"])

    op.create_table(
        "demo_resource_content",
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource_descriptors.tenant_id", "resource_descriptors.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_demo_resource_content_tenant_id", "demo_resource_content", ["tenant_id"])

    op.create_table(
        "authorization_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_subject_id", sa.Text(), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(80)),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("input_metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_authorization_audit_events_tenant_id", "authorization_audit_events", ["tenant_id"]
    )

    for table_name in ("resource_descriptors", "resource_acl_grants", "demo_resource_content"):
        _enable_tenant_rls(table_name)
    _enable_tenant_rls("authorization_audit_events", audit=True)


def downgrade() -> None:
    op.drop_table("authorization_audit_events")
    op.drop_table("demo_resource_content")
    op.drop_table("resource_acl_grants")
    op.drop_table("resource_descriptors")
