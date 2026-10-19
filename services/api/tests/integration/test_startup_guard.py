"""The API refuses to run through a database role that bypasses RLS (D1/D20)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db_guard import UnsafeDatabaseRoleError
from app.main import create_app

pytestmark = pytest.mark.integration


def test_owner_role_refuses_to_start(
    seeded_database: dict[str, dict[str, int]],
    owner_sqlalchemy_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KRIBU_DATABASE_URL", owner_sqlalchemy_url)
    get_settings.cache_clear()

    with pytest.raises(UnsafeDatabaseRoleError), TestClient(create_app()):
        pass


def test_restricted_role_starts(api_client: TestClient) -> None:
    assert api_client.get("/v1/health/live").status_code == 200
