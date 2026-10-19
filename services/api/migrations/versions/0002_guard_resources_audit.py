"""Add canonical resource attributes, ACL grants, demo content, and decision audit.

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

DEMO_TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
SALARY = "10000000-0000-4000-8000-000000000001"
ENGINEERING = "10000000-0000-4000-8000-000000000002"
NGO = "10000000-0000-4000-8000-000000000003"
OTHER = "10000000-0000-4000-8000-000000000004"


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
        op.execute(
            sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table_name}" TO kribu_app')
        )


def upgrade() -> None:
    descriptors = op.create_table(
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

    grants = op.create_table(
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

    content = op.create_table(
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

    op.bulk_insert(
        descriptors,
        [
            {
                "id": SALARY,
                "tenant_id": DEMO_TENANT,
                "resource_type": "employee_record",
                "classification": "restricted_hr",
                "department": "human-resources",
                "owner_subject_id": "roger-synthetic",
                "title": "Synthetic Roger Albert salary revision",
            },
            {
                "id": ENGINEERING,
                "tenant_id": DEMO_TENANT,
                "resource_type": "team_record",
                "classification": "internal",
                "department": "engineering",
                "owner_subject_id": None,
                "title": "Synthetic engineering handbook",
            },
            {
                "id": NGO,
                "tenant_id": DEMO_TENANT,
                "resource_type": "project_report",
                "classification": "internal",
                "department": "programs",
                "owner_subject_id": None,
                "title": "Synthetic NGO progress note",
            },
            {
                "id": OTHER,
                "tenant_id": OTHER_TENANT,
                "resource_type": "team_record",
                "classification": "internal",
                "department": "engineering",
                "owner_subject_id": None,
                "title": "Synthetic second-tenant handbook",
            },
        ],
    )
    op.bulk_insert(
        grants,
        [
            {
                "id": "20000000-0000-4000-8000-000000000001",
                "tenant_id": DEMO_TENANT,
                "resource_id": SALARY,
                "principal_type": "role",
                "principal_id": "hr_manager",
                "action": "resource.read",
            },
            {
                "id": "20000000-0000-4000-8000-000000000002",
                "tenant_id": DEMO_TENANT,
                "resource_id": ENGINEERING,
                "principal_type": "department",
                "principal_id": "engineering",
                "action": "resource.read",
            },
            {
                "id": "20000000-0000-4000-8000-000000000003",
                "tenant_id": DEMO_TENANT,
                "resource_id": NGO,
                "principal_type": "department",
                "principal_id": "programs",
                "action": "resource.read",
            },
            {
                "id": "20000000-0000-4000-8000-000000000004",
                "tenant_id": OTHER_TENANT,
                "resource_id": OTHER,
                "principal_type": "department",
                "principal_id": "engineering",
                "action": "resource.read",
            },
        ],
    )
    op.bulk_insert(
        content,
        [
            {
                "resource_id": SALARY,
                "tenant_id": DEMO_TENANT,
                "content": (
                    "SYNTHETIC ONLY: Roger Albert salary revision, "
                    "BDT 145,000 per month. This is fictional demo data."
                ),
            },
            {
                "resource_id": ENGINEERING,
                "tenant_id": DEMO_TENANT,
                "content": "SYNTHETIC ONLY: Engineering handbook for the KRIBU demo tenant.",
            },
            {
                "resource_id": NGO,
                "tenant_id": DEMO_TENANT,
                "content": "SYNTHETIC ONLY: NGO program progress note for the KRIBU demo tenant.",
            },
            {
                "resource_id": OTHER,
                "tenant_id": OTHER_TENANT,
                "content": "SYNTHETIC ONLY: Engineering handbook for the isolation tenant.",
            },
        ],
    )

    for table_name in ("resource_descriptors", "resource_acl_grants", "demo_resource_content"):
        _enable_tenant_rls(table_name)
    _enable_tenant_rls("authorization_audit_events", audit=True)


def downgrade() -> None:
    op.drop_table("authorization_audit_events")
    op.drop_table("demo_resource_content")
    op.drop_table("resource_acl_grants")
    op.drop_table("resource_descriptors")
