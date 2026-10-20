"""Integration fixtures: real PostgreSQL (RLS, grants) and real OPA, test-signed tokens.

Enabled only with ``KRIBU_INTEGRATION=1``. Each session recreates the dedicated
``kribu_test`` database (never the developer ``kribu`` database), migrates it to head as the
owner role, seeds it twice (idempotency), and serves the API as the restricted ``kribu_app``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from urllib.parse import urlsplit, urlunsplit

import asyncpg  # type: ignore[import-untyped]
import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import PyJWK

from app.core.config import Settings, get_settings
from app.identity.dependencies import get_token_verifier
from app.identity.tokens import OidcTokenVerifier
from app.main import create_app
from scripts.seed_demo import seed

INTEGRATION_ENABLED = os.getenv("KRIBU_INTEGRATION") == "1"
TEST_DATABASE = "kribu_test"
ISSUER = "http://issuer.integration.test/realms/kribu-demo"
AUDIENCE = "kribu-api"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
API_ROOT = Path(__file__).resolve().parents[2]

OWNER_URL = os.getenv(
    "KRIBU_TEST_OWNER_DATABASE_URL", "postgresql://kribu:kribu_dev_only@localhost:5432/kribu"
)
APP_PASSWORD = os.getenv("KRIBU_TEST_APP_DB_PASSWORD", "kribu_app_dev_only")
OPA_URL = os.getenv("KRIBU_TEST_OPA_URL", "http://localhost:8181")


def database_url(base: str, database: str, *, user: str | None = None) -> str:
    parts = urlsplit(base)
    netloc = parts.netloc
    if user is not None:
        netloc = f"{user}:{APP_PASSWORD}@{parts.hostname}:{parts.port or 5432}"
    return urlunsplit((parts.scheme, netloc, f"/{database}", "", ""))


OWNER_TEST_DSN = database_url(OWNER_URL, TEST_DATABASE)
APP_TEST_DSN = database_url(OWNER_URL, TEST_DATABASE, user="kribu_app")


def as_sqlalchemy(dsn: str) -> str:
    return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


async def owner_execute(sql: str, *args: object) -> None:
    connection = await asyncpg.connect(OWNER_TEST_DSN)
    try:
        await connection.execute(sql, *args)
    finally:
        await connection.close()


async def owner_fetch(sql: str, *args: object) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(OWNER_TEST_DSN)
    try:
        return list(await connection.fetch(sql, *args))
    finally:
        await connection.close()


async def _recreate_database() -> None:
    connection = await asyncpg.connect(OWNER_URL)
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
        await connection.execute(f'GRANT CONNECT ON DATABASE "{TEST_DATABASE}" TO kribu_app')
    finally:
        await connection.close()
    await owner_execute("GRANT USAGE ON SCHEMA public TO kribu_app")


@pytest.fixture(scope="session")
def seeded_database(pytestconfig: pytest.Config) -> dict[str, dict[str, int]]:
    if not (INTEGRATION_ENABLED or pytestconfig.getoption("--integration")):
        pytest.skip("pass --integration or set KRIBU_INTEGRATION=1 to run integration tests")
    run(_recreate_database())
    previous = os.environ.get("KRIBU_MIGRATION_DATABASE_URL")
    os.environ["KRIBU_MIGRATION_DATABASE_URL"] = as_sqlalchemy(OWNER_TEST_DSN)
    try:
        # No ini file: alembic's fileConfig would reconfigure logging inside pytest.
        config = Config()
        config.set_main_option("script_location", str(API_ROOT / "migrations"))
        # Prove a new database reaches head and can be rebuilt from its downgrade path.
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        # Then reproduce the published Iteration 4 -> current-head upgrade boundary.
        command.upgrade(config, "0004_upgrade_compatibility")
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("KRIBU_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["KRIBU_MIGRATION_DATABASE_URL"] = previous
    first = run(seed(as_sqlalchemy(OWNER_TEST_DSN)))
    second = run(seed(as_sqlalchemy(OWNER_TEST_DSN)))
    return {"first": first, "second": second}


def create_token(
    *,
    subject: str,
    username: str,
    tenant_id: str,
    roles: list[str],
    department: str | None,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "preferred_username": username,
        "tenant_id": tenant_id,
        "realm_access": {"roles": roles},
    }
    if department is not None:
        claims["department"] = department
    return jwt.encode(claims, SIGNING_KEY, algorithm="RS256", headers={"kid": "integration"})


def build_verifier() -> OidcTokenVerifier:
    settings = Settings(
        _env_file=None,
        oidc_issuer_url=ISSUER,
        oidc_jwks_url="http://jwks.integration.test/certs",
        oidc_audience=AUDIENCE,
        oidc_clock_skew_seconds=0,
    )
    verifier = OidcTokenVerifier(settings)
    verifier._jwks_client.get_signing_key_from_jwt = Mock(  # type: ignore[method-assign]
        return_value=PyJWK.from_dict(
            jwt.algorithms.RSAAlgorithm.to_jwk(SIGNING_KEY.public_key(), as_dict=True)
        )
    )
    return verifier


@pytest.fixture
def document_store(tmp_path: Path) -> Path:
    return tmp_path / "documents"


@pytest.fixture
def api_client_factory(
    seeded_database: dict[str, dict[str, int]],
    monkeypatch: pytest.MonkeyPatch,
    document_store: Path,
) -> Iterator[Callable[..., TestClient]]:
    """Build a TestClient wired to kribu_test as kribu_app, with optional overrides."""
    clients: list[TestClient] = []

    def factory(
        *,
        opa_url: str = OPA_URL,
        store_path: Path | None = None,
        upload_max_bytes: int | None = None,
    ) -> TestClient:
        monkeypatch.setenv("KRIBU_DATABASE_URL", as_sqlalchemy(APP_TEST_DSN))
        monkeypatch.setenv("KRIBU_OPA_URL", opa_url)
        monkeypatch.setenv("KRIBU_DOCUMENT_STORE_PATH", str(store_path or document_store))
        if upload_max_bytes is not None:
            monkeypatch.setenv("KRIBU_UPLOAD_MAX_BYTES", str(upload_max_bytes))
        get_settings.cache_clear()
        application = create_app()
        verifier = build_verifier()
        application.dependency_overrides[get_token_verifier] = lambda: verifier
        client = TestClient(application)
        client.__enter__()
        # The upload guard authenticates before routing, from app.state.
        application.state.token_verifier = verifier
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def api_client(api_client_factory: Callable[..., TestClient]) -> TestClient:
    return api_client_factory()


@pytest.fixture
def token_for() -> Callable[..., str]:
    return create_token


@pytest.fixture
def owner_db(seeded_database: dict[str, dict[str, int]]) -> Any:
    """Owner-role helpers bound to kribu_test (RLS-bypassing; for setup and assertions)."""

    class OwnerDatabase:
        @staticmethod
        def execute(sql: str, *args: object) -> None:
            run(owner_execute(sql, *args))

        @staticmethod
        def fetch(sql: str, *args: object) -> list[asyncpg.Record]:
            return list(run(owner_fetch(sql, *args)))

    return OwnerDatabase()


@pytest.fixture
def app_dsn(seeded_database: dict[str, dict[str, int]]) -> str:
    """asyncpg DSN for the restricted runtime role on kribu_test."""
    return APP_TEST_DSN


@pytest.fixture
def owner_sqlalchemy_url(seeded_database: dict[str, dict[str, int]]) -> str:
    """SQLAlchemy URL for the schema owner (a superuser in Compose and CI)."""
    return as_sqlalchemy(OWNER_TEST_DSN)
