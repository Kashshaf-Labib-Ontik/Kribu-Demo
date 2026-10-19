"""Insert the synthetic demo tenants, identities and Guard resources.

Idempotent: every insert uses ``ON CONFLICT DO NOTHING``, so reruns are safe.

Runs with ``KRIBU_MIGRATION_DATABASE_URL`` (the schema owner / bootstrap superuser), not the
runtime ``kribu_app`` role. RLS is forced on every tenant table and its policies apply only to
``kribu_app`` within one tenant context, so only an RLS-bypassing role can seed both tenants.
All content is fictional (``SYNTHETIC ONLY``).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.database import Base
from app.identity import models as identity_models  # noqa: F401
from app.policy import models as policy_models  # noqa: F401

DEMO_TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
SALARY = "10000000-0000-4000-8000-000000000001"
ENGINEERING = "10000000-0000-4000-8000-000000000002"
NGO = "10000000-0000-4000-8000-000000000003"
OTHER = "10000000-0000-4000-8000-000000000004"

TENANTS: list[dict[str, Any]] = [
    {"id": DEMO_TENANT, "slug": "kribu-demo", "name": "KRIBU Demo Software"},
    {"id": OTHER_TENANT, "slug": "isolation-test", "name": "Isolation Test Organization"},
]

USER_PROFILES: list[dict[str, Any]] = [
    {
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        "tenant_id": DEMO_TENANT,
        "external_subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        "username": "mike",
        "display_name": "Mike Rahman",
        "department": "engineering",
    },
    {
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        "tenant_id": DEMO_TENANT,
        "external_subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        "username": "helen.hr",
        "display_name": "Helen Chowdhury",
        "department": "human-resources",
    },
    {
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
        "tenant_id": DEMO_TENANT,
        "external_subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
        "username": "priya.manager",
        "display_name": "Priya Sen",
        "department": "programs",
    },
    {
        "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
        "tenant_id": OTHER_TENANT,
        "external_subject": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
        "username": "evan.external",
        "display_name": "Evan Ahmed",
        "department": "engineering",
    },
]

RESOURCE_DESCRIPTORS: list[dict[str, Any]] = [
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

RESOURCE_ACL_GRANTS: list[dict[str, Any]] = [
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
]

DEMO_RESOURCE_CONTENT: list[dict[str, Any]] = [
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
SEED_ROWS: tuple[tuple[str, list[dict[str, Any]]], ...] = (
    ("tenants", TENANTS),
    ("user_profiles", USER_PROFILES),
    ("resource_descriptors", RESOURCE_DESCRIPTORS),
    ("resource_acl_grants", RESOURCE_ACL_GRANTS),
    ("demo_resource_content", DEMO_RESOURCE_CONTENT),
)


async def seed_rows(connection: AsyncConnection) -> dict[str, int]:
    inserted: dict[str, int] = {}
    for table_name, rows in SEED_ROWS:
        table = Base.metadata.tables[table_name]
        result = await connection.execute(insert(table).values(rows).on_conflict_do_nothing())
        inserted[table_name] = result.rowcount
    return inserted


async def seed(database_url: str) -> dict[str, int]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            return await seed_rows(connection)
    finally:
        await engine.dispose()


def main() -> None:
    database_url = os.getenv("KRIBU_MIGRATION_DATABASE_URL")
    if not database_url:
        raise SystemExit("KRIBU_MIGRATION_DATABASE_URL is required to seed demo data.")
    inserted = asyncio.run(seed(database_url))
    print(json.dumps({"seeded": inserted}))


if __name__ == "__main__":
    main()
