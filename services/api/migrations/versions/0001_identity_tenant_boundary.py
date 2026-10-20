"""Establish tenant identity boundary.

Revision ID: 0001_identity_tenant
Revises:
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_identity_tenant"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEMO_TENANT_ID = "11111111-1111-4111-8111-111111111111"
ISOLATION_TENANT_ID = "22222222-2222-4222-8222-222222222222"


def upgrade() -> None:
    tenants = op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    user_profiles = op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_subject", sa.Text(), nullable=False),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("department", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_subject"),
        sa.UniqueConstraint(
            "tenant_id",
            "username",
            name="uq_user_profiles_tenant_username",
        ),
    )
    op.create_index("ix_user_profiles_tenant_id", "user_profiles", ["tenant_id"])

    op.bulk_insert(
        tenants,
        [
            {"id": DEMO_TENANT_ID, "slug": "kribu-demo", "name": "KRIBU Demo Software"},
            {
                "id": ISOLATION_TENANT_ID,
                "slug": "isolation-test",
                "name": "Isolation Test Organization",
            },
        ],
    )
    op.bulk_insert(
        user_profiles,
        [
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
                "tenant_id": DEMO_TENANT_ID,
                "external_subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
                "username": "mike",
                "display_name": "Mike Rahman",
                "department": "engineering",
            },
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
                "tenant_id": DEMO_TENANT_ID,
                "external_subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
                "username": "helen.hr",
                "display_name": "Helen Chowdhury",
                "department": "human-resources",
            },
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
                "tenant_id": DEMO_TENANT_ID,
                "external_subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
                "username": "priya.manager",
                "display_name": "Priya Sen",
                "department": "programs",
            },
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
                "tenant_id": ISOLATION_TENANT_ID,
                "external_subject": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
                "username": "evan.external",
                "display_name": "Evan Ahmed",
                "department": "engineering",
            },
        ],
    )

    for table_name, tenant_expression in (
        ("tenants", "id"),
        ("user_profiles", "tenant_id"),
    ):
        tenant_setting = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE POLICY "{table_name}_tenant_isolation" ON "{table_name}" '
                "FOR ALL TO kribu_app "
                f"USING ({tenant_expression} = {tenant_setting}) "
                f"WITH CHECK ({tenant_expression} = {tenant_setting})"
            )
        )
        op.execute(
            sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table_name}" TO kribu_app')
        )


def downgrade() -> None:
    op.drop_index("ix_user_profiles_tenant_id", table_name="user_profiles")
    op.drop_table("user_profiles")
    op.drop_table("tenants")
