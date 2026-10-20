"""Allow the tenant-scoped outbox INSERT RETURNING path.

The application creates an ingestion job and its outbox row atomically. SQLAlchemy
returns server-generated timestamps from that insert, which PostgreSQL treats as a
read. Existing databases that already applied revision 0005 need this narrow grant
and SELECT policy; fresh installs receive the same rules through 0005 and this
revision remains idempotent for them.

Revision ID: 0006_outbox_returning
Revises: 0005_document_provenance
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_outbox_returning"
down_revision: str | None = "0005_document_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "CREATE POLICY document_ingestion_outbox_select ON document_ingestion_outbox "
            "FOR SELECT TO kribu_app USING "
            "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    )
    op.execute(sa.text("GRANT SELECT, INSERT ON document_ingestion_outbox TO kribu_app"))


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY document_ingestion_outbox_select ON document_ingestion_outbox"))
    op.execute(sa.text("REVOKE SELECT ON document_ingestion_outbox FROM kribu_app"))
