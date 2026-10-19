"""End-to-end Guard behavior through the real API, PostgreSQL (RLS) and OPA.

These pin the protected-read contract before the Guard refactor:
  1. denied and missing resources return the same 404 body
  2. every decision writes an audit row before any content is read
  3. an audit failure blocks content
  4. a policy outage fails closed (503) and is audited
  5. the subject's department comes from the database, not the token
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from scripts import seed_demo
from scripts.verify_guard import CHECKS, Check
from tests.integration.support import IntegrationDatabase, bearer

pytestmark = pytest.mark.integration

UNREACHABLE_OPA_URL = "http://127.0.0.1:9"


def audit_rows(database: IntegrationDatabase, correlation_id: str) -> list[dict[str, object]]:
    rows = database.fetch(
        "SELECT tenant_id, actor_subject_id, action, resource_id, allowed, reason_code, "
        "policy_version FROM authorization_audit_events WHERE correlation_id = $1",
        correlation_id,
    )
    return [dict(row) for row in rows]


@pytest.mark.parametrize(
    "check", CHECKS, ids=lambda check: f"{check.username}-{check.expected_status}"
)
def test_guard_decision_matrix_is_enforced_and_audited(
    api: Callable[..., TestClient],
    integration_database: IntegrationDatabase,
    check: Check,
) -> None:
    client = api()
    correlation_id = f"matrix-{uuid4()}"

    response = client.get(
        f"/v1/demo/resources/{check.resource_id}",
        headers={**bearer(check.username), "X-Correlation-ID": correlation_id},
    )

    assert response.status_code == check.expected_status
    if response.status_code == 200:
        assert response.json()["content"].startswith("SYNTHETIC ONLY")
    else:
        assert "SYNTHETIC" not in response.text
    [row] = audit_rows(integration_database, correlation_id)
    assert row["allowed"] is (response.status_code == 200)
    assert row["action"] == "resource.read"
    assert row["policy_version"] == "guard-v1"


def test_anonymous_read_is_rejected(api: Callable[..., TestClient]) -> None:
    response = api().get(f"/v1/demo/resources/{seed_demo.SALARY}")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_caller_supplied_tenant_and_role_parameters_are_ignored(
    api: Callable[..., TestClient],
) -> None:
    response = api().get(
        f"/v1/demo/resources/{seed_demo.SALARY}",
        params={"tenant_id": str(seed_demo.DEMO_TENANT), "roles": "hr_manager"},
        headers={**bearer("mike"), "X-Tenant-ID": str(seed_demo.DEMO_TENANT)},
    )

    assert response.status_code == 404


def test_denied_and_missing_resources_are_indistinguishable(
    api: Callable[..., TestClient],
) -> None:
    client = api()
    headers = {**bearer("mike"), "X-Correlation-ID": "same-shape"}

    denied = client.get(f"/v1/demo/resources/{seed_demo.SALARY}", headers=headers)
    missing = client.get(f"/v1/demo/resources/{uuid4()}", headers=headers)
    other_tenant = client.get(f"/v1/demo/resources/{seed_demo.OTHER}", headers=headers)

    assert denied.status_code == missing.status_code == other_tenant.status_code == 404
    assert denied.json() == missing.json() == other_tenant.json()


def test_missing_resource_is_audited_as_unavailable(
    api: Callable[..., TestClient],
    integration_database: IntegrationDatabase,
) -> None:
    correlation_id = f"missing-{uuid4()}"

    api().get(
        f"/v1/demo/resources/{uuid4()}",
        headers={**bearer("mike"), "X-Correlation-ID": correlation_id},
    )

    [row] = audit_rows(integration_database, correlation_id)
    assert row["allowed"] is False
    assert row["reason_code"] == "resource_unavailable"


def test_department_comes_from_the_database_not_the_token(
    api: Callable[..., TestClient],
) -> None:
    # Mike's token claims the programs department; his profile says engineering.
    response = api().get(
        f"/v1/demo/resources/{seed_demo.NGO}",
        headers=bearer("mike", department="programs"),
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "claims",
    [
        {"tenant_id": str(seed_demo.OTHER_TENANT)},
        {"sub": "cccccccc-cccc-4ccc-8ccc-ccccccccccc1"},
    ],
    ids=["token-tenant-mismatch", "unprovisioned-subject"],
)
def test_unprovisioned_identity_is_forbidden_without_content(
    api: Callable[..., TestClient], claims: dict[str, str]
) -> None:
    response = api().get(
        f"/v1/demo/resources/{seed_demo.ENGINEERING}", headers=bearer("mike", **claims)
    )

    assert response.status_code == 403
    assert response.json()["code"] == "identity_not_provisioned"
    assert "SYNTHETIC" not in response.text


def test_deactivated_profile_is_forbidden_without_content(
    api: Callable[..., TestClient],
    integration_database: IntegrationDatabase,
) -> None:
    client = api()
    integration_database.execute_as_owner(
        f"UPDATE user_profiles SET is_active = false WHERE id = '{seed_demo.MIKE}'"
    )
    try:
        response = client.get(f"/v1/demo/resources/{seed_demo.ENGINEERING}", headers=bearer("mike"))
    finally:
        integration_database.execute_as_owner(
            f"UPDATE user_profiles SET is_active = true WHERE id = '{seed_demo.MIKE}'"
        )

    assert response.status_code == 403
    assert response.json()["code"] == "identity_not_provisioned"
    assert "SYNTHETIC" not in response.text


def test_audit_failure_blocks_content(
    api: Callable[..., TestClient],
    integration_database: IntegrationDatabase,
) -> None:
    client = api()
    integration_database.execute_as_owner(
        "REVOKE INSERT ON authorization_audit_events FROM kribu_app"
    )
    try:
        response = client.get(f"/v1/demo/resources/{seed_demo.SALARY}", headers=bearer("helen.hr"))
    finally:
        integration_database.execute_as_owner(
            "GRANT INSERT ON authorization_audit_events TO kribu_app"
        )

    assert response.status_code == 503
    assert response.json()["code"] == "audit_unavailable"
    assert "SYNTHETIC" not in response.text


def test_policy_outage_fails_closed_and_is_audited(
    api: Callable[..., TestClient],
    integration_database: IntegrationDatabase,
) -> None:
    correlation_id = f"outage-{uuid4()}"

    response = api(opa_url=UNREACHABLE_OPA_URL).get(
        f"/v1/demo/resources/{seed_demo.SALARY}",
        headers={**bearer("helen.hr"), "X-Correlation-ID": correlation_id},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "authorization_unavailable"
    assert "SYNTHETIC" not in response.text
    [row] = audit_rows(integration_database, correlation_id)
    assert row["allowed"] is False
    assert row["reason_code"] == "policy_unavailable"
    assert row["policy_version"] is None


def test_readiness_reports_policy_outage(api: Callable[..., TestClient]) -> None:
    assert api().get("/v1/health/ready").status_code == 200
    assert api(opa_url=UNREACHABLE_OPA_URL).get("/v1/health/ready").status_code == 503
