from typing import cast
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.routes.health import get_database_engine
from app.main import app
from app.policy.client import OpaClient
from app.policy.dependencies import get_opa_client


def test_liveness_returns_service_identity() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "kribu-api",
        "version": "0.1.0",
    }
    assert response.headers["X-Correlation-ID"]


def test_liveness_preserves_correlation_id() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/v1/health/live",
            headers={"X-Correlation-ID": "test-correlation-id"},
        )

    assert response.headers["X-Correlation-ID"] == "test-correlation-id"


def test_readiness_returns_safe_problem_when_database_is_unavailable() -> None:
    failing_engine = Mock(spec=AsyncEngine)
    failing_engine.connect.side_effect = ConnectionRefusedError
    app.dependency_overrides[get_database_engine] = lambda: cast(AsyncEngine, failing_engine)

    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/health/ready",
                headers={"X-Correlation-ID": "readiness-test"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "type": "about:blank",
        "title": "Service Unavailable",
        "status": 503,
        "detail": "The database readiness check failed.",
        "code": "database_unavailable",
        "correlation_id": "readiness-test",
    }
    assert response.headers["content-type"] == "application/problem+json"


def test_readiness_returns_problem_when_policy_engine_is_not_ready() -> None:
    working_engine = Mock(spec=AsyncEngine)
    connection = AsyncMock()
    working_engine.connect.return_value.__aenter__ = AsyncMock(return_value=connection)
    working_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)
    opa_client = Mock(spec=OpaClient)
    opa_client.ready = AsyncMock(return_value=False)
    app.dependency_overrides[get_database_engine] = lambda: cast(AsyncEngine, working_engine)
    app.dependency_overrides[get_opa_client] = lambda: opa_client

    try:
        with TestClient(app) as client:
            response = client.get("/v1/health/ready", headers={"X-Correlation-ID": "opa-down"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["code"] == "authorization_unavailable"
    assert response.json()["correlation_id"] == "opa-down"
