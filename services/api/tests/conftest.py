"""Hermetic test settings.

This module runs before any test module imports ``app.main``, which builds the app (and
reads settings) at import time. Developer ``.env`` values and shell ``KRIBU_*`` variables
must never leak into tests, so both are removed here, at module level.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

from app.core.config import Settings, get_settings

# Integration-suite controls are read by tests/integration, never by Settings.
_PRESERVED = ("KRIBU_INTEGRATION", "KRIBU_TEST_")

for _name in [name for name in os.environ if name.startswith("KRIBU_")]:
    if not _name.startswith(_PRESERVED):
        del os.environ[_name]

os.environ.update(
    {
        "KRIBU_ENVIRONMENT": "test",
        "KRIBU_DATABASE_URL": (
            "postgresql+asyncpg://kribu_app:kribu_app_dev_only@localhost:5432/kribu_test"
        ),
        "KRIBU_OPA_URL": "http://localhost:8181",
        "KRIBU_DOCUMENT_STORE_PATH": tempfile.mkdtemp(prefix="kribu-test-store-"),
    }
)
Settings.model_config["env_file"] = None
get_settings.cache_clear()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration",
        action="store_true",
        help="run tests/integration against PostgreSQL and OPA (same as KRIBU_INTEGRATION=1)",
    )


@pytest.fixture(autouse=True)
def fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
