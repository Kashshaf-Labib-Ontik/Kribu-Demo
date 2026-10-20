from __future__ import annotations

from collections.abc import AsyncIterator
from http import HTTPStatus
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.identity.contracts import CurrentUser
from app.identity.dependencies import get_current_user, get_tenant_session
from app.main import app

STUDIO_ORIGIN = "http://localhost:3000"
USER = CurrentUser(
    subject_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
    tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
    username="mike",
    roles=frozenset({"employee"}),
)


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client  # type: ignore[misc]
    app.dependency_overrides.clear()


def test_validation_error_is_a_problem_without_echoing_input(client: TestClient) -> None:
    async def session_override() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_tenant_session] = session_override

    response = client.get(
        "/v1/demo/resources/not-a-uuid-<script>", headers={"X-Correlation-ID": "invalid-path"}
    )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": HTTPStatus.UNPROCESSABLE_ENTITY.phrase,
        "status": 422,
        "detail": "The request is invalid.",
        "code": "request_invalid",
        "correlation_id": "invalid-path",
    }
    assert "<script>" not in response.text


def test_unhandled_error_returns_problem_with_correlation_and_cors(client: TestClient) -> None:
    def explode() -> CurrentUser:
        raise RuntimeError("database password is hunter2")

    app.dependency_overrides[get_current_user] = explode

    response = client.get(
        "/v1/identity/me",
        headers={"X-Correlation-ID": "boom", "Origin": STUDIO_ORIGIN},
    )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "An unexpected error occurred.",
        "code": "internal_error",
        "correlation_id": "boom",
    }
    assert "hunter2" not in response.text
    assert response.headers["X-Correlation-ID"] == "boom"
    assert UUID(response.headers["X-Request-ID"])
    assert response.headers["access-control-allow-origin"] == STUDIO_ORIGIN


@pytest.mark.parametrize(
    ("incoming", "kept"),
    [
        ("studio-req.42_A", True),
        ("x" * 128, True),
        ("x" * 129, False),
        ("has space", False),
        ("new\r\nline", False),
        ("semi;colon", False),
        ("", False),
    ],
)
def test_correlation_id_is_validated(client: TestClient, incoming: str, kept: bool) -> None:
    response = client.get("/v1/health/live", headers={"X-Correlation-ID": incoming})

    returned = response.headers["X-Correlation-ID"]
    if kept:
        assert returned == incoming
    else:
        assert UUID(returned)


def test_every_request_gets_a_fresh_server_request_id(client: TestClient) -> None:
    first = client.get("/v1/health/live", headers={"X-Correlation-ID": "same"})
    second = client.get("/v1/health/live", headers={"X-Correlation-ID": "same"})

    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    assert UUID(first.headers["X-Request-ID"])
