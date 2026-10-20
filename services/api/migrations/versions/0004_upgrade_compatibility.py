"""Harden the Iteration 5 upgrade path and runtime grants.

This revision deliberately carries changes that were first developed by editing
already-published revisions.  Existing databases have recorded those revisions and
therefore need an explicit forward migration.

Revision ID: 0004_upgrade_compatibility
Revises: 0003_documents
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_upgrade_compatibility"
down_revision: str | None = "0003_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Some feature-branch databases already received this column through a rewritten
    # 0002; released Iteration 4 databases did not.  This keeps both paths upgradeable.
    op.execute(
        sa.text(
            "ALTER TABLE authorization_audit_events ADD COLUMN IF NOT EXISTS request_id VARCHAR(64)"
        )
    )

    op.create_unique_constraint(
        "uq_document_versions_tenant_id_id",
        "document_versions",
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_upload_requests_document_version",
        "upload_requests",
        "document_versions",
        ["tenant_id", "document_version_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )

    # Historical revisions granted broad writes.  The runtime only reads identity and
    # demo data, creates descriptors/ACLs for uploads, and appends authorization events.
    op.execute(sa.text("REVOKE INSERT, UPDATE, DELETE ON tenants FROM kribu_app"))
    op.execute(sa.text("REVOKE INSERT, UPDATE, DELETE ON user_profiles FROM kribu_app"))
    op.execute(sa.text("REVOKE INSERT, UPDATE, DELETE ON demo_resource_content FROM kribu_app"))
    op.execute(sa.text("REVOKE UPDATE, DELETE ON resource_descriptors FROM kribu_app"))
    op.execute(sa.text("REVOKE UPDATE, DELETE ON resource_acl_grants FROM kribu_app"))
    op.execute(sa.text("REVOKE UPDATE, DELETE ON authorization_audit_events FROM kribu_app"))

    op.execute(sa.text("GRANT SELECT ON tenants, user_profiles TO kribu_app"))
    op.execute(sa.text("GRANT SELECT ON demo_resource_content TO kribu_app"))
    op.execute(
        sa.text("GRANT SELECT, INSERT ON resource_descriptors, resource_acl_grants TO kribu_app")
    )
    op.execute(sa.text("GRANT SELECT, INSERT ON authorization_audit_events TO kribu_app"))


def downgrade() -> None:
    op.drop_constraint("fk_upload_requests_document_version", "upload_requests", type_="foreignkey")
    op.drop_constraint("uq_document_versions_tenant_id_id", "document_versions", type_="unique")
    op.drop_column("authorization_audit_events", "request_id")

    # Restore the grants issued by the historical revisions.
    op.execute(
        sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON tenants, user_profiles TO kribu_app")
    )
    op.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON resource_descriptors, "
            "resource_acl_grants, demo_resource_content TO kribu_app"
        )
    )
    op.execute(sa.text("GRANT SELECT, INSERT ON authorization_audit_events TO kribu_app"))
