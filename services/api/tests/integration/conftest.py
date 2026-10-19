"""Integration fixtures: a throwaway PostgreSQL database plus the real OPA.

Preconditions (README "Integration tests"; CI does the same):
- PostgreSQL reachable as the schema-owner role (`KRIBU_TEST_OWNER_DATABASE_URL`)
- the `kribu_app` role exists (compose `db-bootstrap` or the CI bootstrap step)
- OPA serving `policies/rego` (`KRIBU_TEST_OPA_URL`, see `compose.integration.yaml`)

Each session drops and recreates `kribu_integration`, runs Alembic and the demo
seed, then exercises the real API in-process. Tokens are signed locally; only
the JWKS lookup is replaced, so issuer, audience and claim checks still run.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.identity.dependencies import get_token_verifier
from app.main import create_app
from scripts import seed_demo
from tests.integration.support import IntegrationDatabase, asyncpg_dsn, execute_sql
from tests.tokens import create_verifier

API_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE = "kribu_integration"
OWNER_URL = os.getenv(
    "KRIBU_TEST_OWNER_DATABASE_URL",
    "postgresql+asyncpg://kribu:kribu_dev_only@127.0.0.1:15432/kribu",
)
APP_PASSWORD = os.getenv("KRIBU_TEST_APP_DB_PASSWORD", "kribu_app_dev_only")
OPA_URL = os.getenv("KRIBU_TEST_OPA_URL", "http://127.0.0.1:18181")


async def _recreate_database(admin_dsn: str, test_dsn: str) -> None:
    admin = await asyncpg.connect(admin_dsn)
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = 'kribu_app'"):
            pytest.fail("Role kribu_app is missing; run the compose db-bootstrap service first.")
        await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
        await admin.execute(f'GRANT CONNECT ON DATABASE "{TEST_DATABASE}" TO kribu_app')
    finally:
        await admin.close()
    await execute_sql(test_dsn, "GRANT USAGE ON SCHEMA public TO kribu_app")


async def _drop_database(admin_dsn: str) -> None:
    await execute_sql(admin_dsn, f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')


@pytest.fixture(scope="session")
def integration_database() -> Iterator[IntegrationDatabase]:
    owner = make_url(OWNER_URL)
    test_owner_url = owner.set(database=TEST_DATABASE).render_as_string(hide_password=False)
    test_app_url = (
        owner.set(username="kribu_app", password=APP_PASSWORD, database=TEST_DATABASE)
    ).render_as_string(hide_password=False)
    database = IntegrationDatabase(
        owner_url=test_owner_url,
        owner_dsn=asyncpg_dsn(test_owner_url),
        app_url=test_app_url,
        app_dsn=asyncpg_dsn(test_app_url),
    )

    asyncio.run(_recreate_database(asyncpg_dsn(OWNER_URL), database.owner_dsn))
    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env={**os.environ, "KRIBU_MIGRATION_DATABASE_URL": test_owner_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if migration.returncode != 0:
        pytest.fail(f"alembic upgrade failed:\n{migration.stderr}")
    asyncio.run(seed_demo.seed(test_owner_url))

    yield database

    asyncio.run(_drop_database(asyncpg_dsn(OWNER_URL)))


@pytest.fixture
def api(
    integration_database: IntegrationDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., TestClient]]:
    """Factory for an in-process API wired to the integration database and OPA."""
    clients: list[TestClient] = []

    def make(*, opa_url: str = OPA_URL) -> TestClient:
        monkeypatch.setenv("KRIBU_DATABASE_URL", integration_database.app_url)
        monkeypatch.setenv("KRIBU_OPA_URL", opa_url)
        get_settings.cache_clear()
        application = create_app()
        verifier = create_verifier()
        application.dependency_overrides[get_token_verifier] = lambda: verifier
        client = TestClient(application)
        client.__enter__()
        clients.append(client)
        return client

    yield make

    for client in clients:
        client.__exit__(None, None, None)
