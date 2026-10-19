"""PostgreSQL boundary for the runtime role: RLS isolation and least-privilege grants.

Every check connects as `kribu_app` (the role the API uses) and runs inside a
rolled-back transaction, so the shared integration database stays unchanged.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest

from scripts import seed_demo
from tests.integration.support import IntegrationDatabase

pytestmark = pytest.mark.integration

TENANT_TABLES = (
    "tenants",
    "user_profiles",
    "resource_descriptors",
    "resource_acl_grants",
    "demo_resource_content",
    "authorization_audit_events",
)

INSERT_AUDIT = (
    "INSERT INTO authorization_audit_events "
    "(id, tenant_id, actor_subject_id, action, resource_id, allowed, reason_code, "
    "correlation_id, input_metadata) "
    "VALUES ($1, $2, $3, 'resource.read', $4, false, 'test', 'boundary-test', '{}'::jsonb)"
)


async def _as_app(
    database: IntegrationDatabase,
    statement: str,
    *args: object,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
) -> object:
    connection = await asyncpg.connect(database.app_dsn)
    transaction = connection.transaction()
    await transaction.start()
    try:
        if tenant_id is not None:
            await connection.execute(
                "SELECT set_config('app.tenant_id', $1, true), set_config('app.user_id', $2, true)",
                str(tenant_id),
                str(user_id or ""),
            )
        return await connection.fetchval(statement, *args)
    finally:
        await transaction.rollback()
        await connection.close()


def as_app(database: IntegrationDatabase, statement: str, *args: object, **context: UUID) -> object:
    return asyncio.run(_as_app(database, statement, *args, **context))


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_no_tenant_context_sees_no_rows(
    integration_database: IntegrationDatabase, table: str
) -> None:
    assert as_app(integration_database, f'SELECT count(*) FROM "{table}"') == 0


@pytest.mark.parametrize(
    ("tenant_id", "expected"),
    [(seed_demo.DEMO_TENANT, 3), (seed_demo.OTHER_TENANT, 1)],
)
def test_tenant_context_sees_only_its_resources(
    integration_database: IntegrationDatabase, tenant_id: UUID, expected: int
) -> None:
    query = "SELECT count(*) FROM resource_descriptors"
    foreign = "SELECT count(*) FROM resource_descriptors WHERE tenant_id <> $1"

    assert as_app(integration_database, query, tenant_id=tenant_id) == expected
    assert as_app(integration_database, foreign, tenant_id, tenant_id=tenant_id) == 0


def test_runtime_role_can_append_audit_for_its_own_tenant(
    integration_database: IntegrationDatabase,
) -> None:
    as_app(
        integration_database,
        INSERT_AUDIT,
        uuid4(),
        seed_demo.DEMO_TENANT,
        str(seed_demo.MIKE),
        seed_demo.SALARY,
        tenant_id=seed_demo.DEMO_TENANT,
        user_id=seed_demo.MIKE,
    )


@pytest.mark.parametrize(
    ("row_tenant", "actor"),
    [
        (seed_demo.OTHER_TENANT, seed_demo.MIKE),
        (seed_demo.DEMO_TENANT, seed_demo.HELEN),
    ],
    ids=["cross-tenant", "forged-actor"],
)
def test_audit_insert_must_match_tenant_and_actor(
    integration_database: IntegrationDatabase, row_tenant: UUID, actor: UUID
) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        as_app(
            integration_database,
            INSERT_AUDIT,
            uuid4(),
            row_tenant,
            str(actor),
            seed_demo.SALARY,
            tenant_id=seed_demo.DEMO_TENANT,
            user_id=seed_demo.MIKE,
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE authorization_audit_events SET reason_code = 'tampered'",
        "DELETE FROM authorization_audit_events",
        "UPDATE resource_acl_grants SET principal_id = 'employee'",
        "INSERT INTO resource_acl_grants (id, tenant_id, resource_id, principal_type, "
        "principal_id, action) VALUES (gen_random_uuid(), "
        "'11111111-1111-4111-8111-111111111111', '10000000-0000-4000-8000-000000000001', "
        "'role', 'employee', 'resource.read')",
        "UPDATE resource_descriptors SET classification = 'internal'",
        "UPDATE user_profiles SET department = 'human-resources'",
        "UPDATE user_profiles SET is_active = true",
        "DELETE FROM demo_resource_content",
        "UPDATE tenants SET name = 'tampered'",
    ],
    ids=[
        "audit-update",
        "audit-delete",
        "grant-update",
        "grant-insert",
        "descriptor-update",
        "profile-department",
        "profile-reactivate",
        "content-delete",
        "tenant-update",
    ],
)
def test_runtime_role_cannot_rewrite_authorization_data(
    integration_database: IntegrationDatabase, statement: str
) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        as_app(
            integration_database,
            statement,
            tenant_id=seed_demo.DEMO_TENANT,
            user_id=seed_demo.MIKE,
        )


def test_seed_is_idempotent(integration_database: IntegrationDatabase) -> None:
    count = "SELECT count(*) FROM resource_acl_grants"
    before = integration_database.fetch(count)[0][0]

    asyncio.run(seed_demo.seed(integration_database.owner_url))

    assert integration_database.fetch(count)[0][0] == before == 4
