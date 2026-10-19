"""Shared test configuration.

`app.main` builds the FastAPI app at import time, so the process environment is
isolated here, before any test module imports it. Developer `.env` files and
shell `KRIBU_*` variables never reach the tests. `KRIBU_TEST_*` variables are
harness knobs for the integration suite and are kept.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from app.core.config import Settings, get_settings
from tests.tokens import AUDIENCE, ISSUER

TEST_ENVIRONMENT = {
    "KRIBU_ENVIRONMENT": "test",
    "KRIBU_DATABASE_URL": (
        "postgresql+asyncpg://kribu_app:kribu_app_test_only@localhost:5432/kribu_unit_tests"
    ),
    "KRIBU_OIDC_ISSUER_URL": ISSUER,
    "KRIBU_OIDC_JWKS_URL": "http://jwks.test/certs",
    "KRIBU_OIDC_AUDIENCE": AUDIENCE,
    "KRIBU_OPA_URL": "http://opa.test:8181",
}

for _name in [name for name in os.environ if name.startswith("KRIBU_")]:
    if not _name.startswith("KRIBU_TEST_"):
        del os.environ[_name]
os.environ.update(TEST_ENVIRONMENT)
Settings.model_config["env_file"] = None
get_settings.cache_clear()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run tests marked 'integration' (needs PostgreSQL and OPA; see README).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(reason="integration test: pass --run-integration")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_integration)


@pytest.fixture(autouse=True)
def fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
