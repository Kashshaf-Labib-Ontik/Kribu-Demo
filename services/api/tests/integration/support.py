"""Helpers shared by the integration tests (users, tokens, owner-role DB access)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy.engine import make_url

from scripts import seed_demo
from tests.tokens import create_token


@dataclass(frozen=True)
class DemoUser:
    subject: UUID
    tenant_id: UUID
    department: str
    roles: tuple[str, ...]


# Mirrors infra/keycloak/kribu-demo-realm.json (roles and attributes per user).
DEMO_USERS = {
    "mike": DemoUser(seed_demo.MIKE, seed_demo.DEMO_TENANT, "engineering", ("employee",)),
    "helen.hr": DemoUser(
        seed_demo.HELEN, seed_demo.DEMO_TENANT, "human-resources", ("hr_manager",)
    ),
    "priya.manager": DemoUser(
        seed_demo.PRIYA, seed_demo.DEMO_TENANT, "programs", ("manager", "approver")
    ),
    "evan.external": DemoUser(seed_demo.EVAN, seed_demo.OTHER_TENANT, "engineering", ("employee",)),
}


def bearer(username: str, **claim_overrides: object) -> dict[str, str]:
    user = DEMO_USERS[username]
    claims: dict[str, object] = {
        "sub": str(user.subject),
        "preferred_username": username,
        "tenant_id": str(user.tenant_id),
        "department": user.department,
        "realm_access": {"roles": list(user.roles)},
    }
    claims.update(claim_overrides)
    return {"Authorization": f"Bearer {create_token(**claims)}"}


@dataclass(frozen=True)
class IntegrationDatabase:
    owner_url: str
    owner_dsn: str
    app_url: str
    app_dsn: str

    def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        """Read as the owner role (bypasses RLS) to inspect what the API wrote."""
        return asyncio.run(fetch_sql(self.owner_dsn, query, *args))

    def execute_as_owner(self, statement: str) -> None:
        asyncio.run(execute_sql(self.owner_dsn, statement))


def asyncpg_dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


async def fetch_sql(dsn: str, query: str, *args: Any) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(dsn)
    try:
        return list(await connection.fetch(query, *args))
    finally:
        await connection.close()


async def execute_sql(dsn: str, statement: str) -> None:
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(statement)
    finally:
        await connection.close()
