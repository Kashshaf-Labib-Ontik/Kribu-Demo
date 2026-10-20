"""Row-level security and least-privilege grants for the runtime role (kribu_app)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

DEMO_TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
MIKE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
OTHER_RESOURCE = "10000000-0000-4000-8000-000000000004"
TENANT_TABLES = (
    "tenants",
    "user_profiles",
    "resource_descriptors",
    "resource_acl_grants",
    "demo_resource_content",
    "authorization_audit_events",
    "document_ingestion_jobs",
    "document_ingestion_outbox",
    "document_extractions",
    "document_content_blocks",
    "document_index_jobs",
    "document_index_outbox",
    "document_index_generations",
    "document_search_chunks",
    "document_index_heads",
    "retrieval_audit_events",
)


@pytest_asyncio.fixture
async def app_connection(app_dsn: str) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(app_dsn)
    try:
        yield connection
    finally:
        await connection.close()


async def in_tenant(connection: asyncpg.Connection, tenant_id: str, user_id: str = MIKE) -> None:
    await connection.execute(
        "SELECT set_config('app.tenant_id', $1, true), set_config('app.user_id', $2, true)",
        tenant_id,
        user_id,
    )


def test_seed_is_idempotent(seeded_database: dict[str, dict[str, int]]) -> None:
    # Historical migrations already contain these fixtures; the separate seed command
    # remains safe whether the rows exist or a future schema starts empty.
    assert seeded_database["first"]["tenants"] in {0, 2}
    assert seeded_database["first"]["resource_descriptors"] in {0, 4}
    assert all(count == 0 for count in seeded_database["second"].values())


def test_upgrade_compatibility_schema_and_constraints(owner_db: object) -> None:
    rows = owner_db.fetch(  # type: ignore[attr-defined]
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'authorization_audit_events' AND column_name = 'request_id'"
    )
    constraints = owner_db.fetch(  # type: ignore[attr-defined]
        "SELECT conname FROM pg_constraint WHERE conname = ANY($1::text[])",
        [
            "uq_document_versions_tenant_id_id",
            "fk_upload_requests_document_version",
        ],
    )

    assert [row["column_name"] for row in rows] == ["request_id"]
    assert {row["conname"] for row in constraints} == {
        "uq_document_versions_tenant_id_id",
        "fk_upload_requests_document_version",
    }


def test_derived_ingestion_tables_force_row_level_security(owner_db: object) -> None:
    rows = owner_db.fetch(  # type: ignore[attr-defined]
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY($1::text[]) ORDER BY relname",
        [
            "document_content_blocks",
            "document_extractions",
            "document_ingestion_jobs",
            "document_ingestion_outbox",
            "document_index_generations",
            "document_index_heads",
            "document_index_jobs",
            "document_index_outbox",
            "document_search_chunks",
            "retrieval_audit_events",
        ],
    )

    assert len(rows) == 10
    assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_no_tenant_context_sees_no_rows(
    app_connection: asyncpg.Connection, table: str
) -> None:
    assert await app_connection.fetchval(f'SELECT count(*) FROM "{table}"') == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("tenant_id", "expected"), [(DEMO_TENANT, 3), (OTHER_TENANT, 1)])
async def test_tenant_context_sees_only_own_resources(
    app_connection: asyncpg.Connection, tenant_id: str, expected: int
) -> None:
    async with app_connection.transaction():
        await in_tenant(app_connection, tenant_id)
        count = await app_connection.fetchval("SELECT count(*) FROM resource_descriptors")

    assert count == expected


@pytest.mark.asyncio
async def test_cross_tenant_audit_insert_is_blocked(app_connection: asyncpg.Connection) -> None:
    transaction = app_connection.transaction()
    await transaction.start()
    try:
        await in_tenant(app_connection, DEMO_TENANT)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_connection.execute(
                "INSERT INTO authorization_audit_events "
                "(id, tenant_id, actor_subject_id, action, resource_id, allowed, reason_code, "
                "correlation_id, input_metadata) "
                "VALUES ($1, $2, $3, 'resource.read', $4, false, 'test', 'x', '{}')",
                uuid4(),
                OTHER_TENANT,
                MIKE,
                uuid4(),
            )
    finally:
        await transaction.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE authorization_audit_events SET reason_code = 'tampered' WHERE false",
        "DELETE FROM authorization_audit_events WHERE false",
        "UPDATE resource_acl_grants SET action = 'resource.read' WHERE false",
        "UPDATE resource_descriptors SET classification = 'internal' WHERE false",
        "DELETE FROM resource_acl_grants WHERE false",
        "UPDATE user_profiles SET is_active = true WHERE false",
        "UPDATE demo_resource_content SET content = 'x' WHERE false",
        "UPDATE retrieval_audit_events SET result_count = 0 WHERE false",
        "DELETE FROM retrieval_audit_events WHERE false",
        "UPDATE document_search_chunks SET text = 'tampered' WHERE false",
        "DELETE FROM document_search_chunks WHERE false",
    ],
)
async def test_runtime_role_cannot_modify_authorization_data(
    app_connection: asyncpg.Connection, statement: str
) -> None:
    transaction = app_connection.transaction()
    await transaction.start()
    try:
        await in_tenant(app_connection, DEMO_TENANT)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_connection.execute(statement)
    finally:
        await transaction.rollback()


@pytest.mark.asyncio
async def test_runtime_role_cannot_create_grants_in_another_tenant(
    app_connection: asyncpg.Connection,
) -> None:
    """Uploads may insert ACL grants (0003), but only inside the caller's tenant context."""
    transaction = app_connection.transaction()
    await transaction.start()
    try:
        await in_tenant(app_connection, DEMO_TENANT)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_connection.execute(
                "INSERT INTO resource_acl_grants "
                "(id, tenant_id, resource_id, principal_type, principal_id, action) "
                "VALUES ($1, $2, $3, 'subject', $4, 'resource.read')",
                uuid4(),
                OTHER_TENANT,
                OTHER_RESOURCE,
                MIKE,
            )
    finally:
        await transaction.rollback()


SALARY_RESOURCE = "10000000-0000-4000-8000-000000000001"
HELEN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"
INSERT_DESCRIPTOR = (
    "INSERT INTO resource_descriptors "
    "(id, tenant_id, resource_type, classification, department, owner_subject_id, title) "
    "VALUES ($1, $2, 'document', 'internal', 'engineering', $3, 'Synthetic')"
)
INSERT_GRANT = (
    "INSERT INTO resource_acl_grants "
    "(id, tenant_id, resource_id, principal_type, principal_id, action) "
    "VALUES ($1, $2, $3, 'subject', $4, 'resource.read')"
)


@pytest.mark.asyncio
async def test_runtime_role_cannot_forge_a_resource_owner(
    app_connection: asyncpg.Connection,
) -> None:
    transaction = app_connection.transaction()
    await transaction.start()
    try:
        await in_tenant(app_connection, DEMO_TENANT)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_connection.execute(INSERT_DESCRIPTOR, uuid4(), DEMO_TENANT, HELEN)
    finally:
        await transaction.rollback()


@pytest.mark.asyncio
async def test_runtime_role_cannot_grant_itself_access_to_another_owners_resource(
    app_connection: asyncpg.Connection,
) -> None:
    transaction = app_connection.transaction()
    await transaction.start()
    try:
        await in_tenant(app_connection, DEMO_TENANT)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_connection.execute(INSERT_GRANT, uuid4(), DEMO_TENANT, SALARY_RESOURCE, MIKE)
    finally:
        await transaction.rollback()


@pytest.mark.asyncio
async def test_runtime_role_may_create_its_own_resource_and_grants(
    app_connection: asyncpg.Connection,
) -> None:
    resource_id = uuid4()
    transaction = app_connection.transaction()
    await transaction.start()
    try:
        await in_tenant(app_connection, DEMO_TENANT)
        await app_connection.execute(INSERT_DESCRIPTOR, resource_id, DEMO_TENANT, MIKE)
        await app_connection.execute(INSERT_GRANT, uuid4(), DEMO_TENANT, resource_id, HELEN)
    finally:
        await transaction.rollback()
