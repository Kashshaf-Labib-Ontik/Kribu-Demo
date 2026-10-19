"""Seed the synthetic KRIBU demo tenants, users, resources and content.

Run after `alembic upgrade head`:

    uv run python -m scripts.seed_demo

The seed is idempotent (existing rows are left untouched). It connects with
`KRIBU_MIGRATION_DATABASE_URL`, the schema-owner role used by migrations. That
role must bypass row-level security: tenant policies apply only to `kribu_app`
and are FORCEd, so no other role can write rows for both demo tenants. The
runtime `kribu_app` role only has SELECT on these tables.

All names, records and amounts are fictional.
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.identity.models import Tenant, UserProfile
from app.policy.models import DemoResourceContent, ResourceAclGrant, ResourceDescriptor

DEMO_TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = UUID("22222222-2222-4222-8222-222222222222")

MIKE = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
HELEN = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2")
PRIYA = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3")
EVAN = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1")

SALARY = UUID("10000000-0000-4000-8000-000000000001")
ENGINEERING = UUID("10000000-0000-4000-8000-000000000002")
NGO = UUID("10000000-0000-4000-8000-000000000003")
OTHER = UUID("10000000-0000-4000-8000-000000000004")

TENANTS = [
    {"id": DEMO_TENANT, "slug": "kribu-demo", "name": "KRIBU Demo Software"},
    {"id": OTHER_TENANT, "slug": "isolation-test", "name": "Isolation Test Organization"},
]

USER_PROFILES = [
    {
        "id": MIKE,
        "tenant_id": DEMO_TENANT,
        "external_subject": str(MIKE),
        "username": "mike",
        "display_name": "Mike Rahman",
        "department": "engineering",
    },
    {
        "id": HELEN,
        "tenant_id": DEMO_TENANT,
        "external_subject": str(HELEN),
        "username": "helen.hr",
        "display_name": "Helen Chowdhury",
        "department": "human-resources",
    },
    {
        "id": PRIYA,
        "tenant_id": DEMO_TENANT,
        "external_subject": str(PRIYA),
        "username": "priya.manager",
        "display_name": "Priya Sen",
        "department": "programs",
    },
    {
        "id": EVAN,
        "tenant_id": OTHER_TENANT,
        "external_subject": str(EVAN),
        "username": "evan.external",
        "display_name": "Evan Ahmed",
        "department": "engineering",
    },
]

RESOURCE_DESCRIPTORS = [
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
]

RESOURCE_ACL_GRANTS = [
    {
        "id": UUID("20000000-0000-4000-8000-000000000001"),
        "tenant_id": DEMO_TENANT,
        "resource_id": SALARY,
        "principal_type": "role",
        "principal_id": "hr_manager",
        "action": "resource.read",
    },
    {
        "id": UUID("20000000-0000-4000-8000-000000000002"),
        "tenant_id": DEMO_TENANT,
        "resource_id": ENGINEERING,
        "principal_type": "department",
        "principal_id": "engineering",
        "action": "resource.read",
    },
    {
        "id": UUID("20000000-0000-4000-8000-000000000003"),
        "tenant_id": DEMO_TENANT,
        "resource_id": NGO,
        "principal_type": "department",
        "principal_id": "programs",
        "action": "resource.read",
    },
    {
        "id": UUID("20000000-0000-4000-8000-000000000004"),
        "tenant_id": OTHER_TENANT,
        "resource_id": OTHER,
        "principal_type": "department",
        "principal_id": "engineering",
        "action": "resource.read",
    },
]

DEMO_RESOURCE_CONTENT = [
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
]

# Parent tables first so foreign keys resolve.
SEED_ROWS: list[tuple[Table, list[dict[str, object]]]] = [
    (Tenant.__table__, TENANTS),
    (UserProfile.__table__, USER_PROFILES),
    (ResourceDescriptor.__table__, RESOURCE_DESCRIPTORS),
    (ResourceAclGrant.__table__, RESOURCE_ACL_GRANTS),
    (DemoResourceContent.__table__, DEMO_RESOURCE_CONTENT),
]


async def seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for table, rows in SEED_ROWS:
                await connection.execute(insert(table).on_conflict_do_nothing(), rows)
    finally:
        await engine.dispose()


def main() -> None:
    database_url = os.getenv("KRIBU_MIGRATION_DATABASE_URL")
    if not database_url:
        raise SystemExit("KRIBU_MIGRATION_DATABASE_URL is required to seed demo data.")
    asyncio.run(seed(database_url))
    row_count = sum(len(rows) for _, rows in SEED_ROWS)
    print(f"Seeded {row_count} synthetic demo rows (existing rows kept).")


if __name__ == "__main__":
    main()
