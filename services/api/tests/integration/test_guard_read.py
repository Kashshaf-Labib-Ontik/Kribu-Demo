"""Guard protected-read behavior against real PostgreSQL and OPA.

Pins the Iteration 4 contract before the Guard refactor: the decision matrix, forged
caller attributes, identical safe 404s, audit-before-content, audit failure blocking
content, OPA outage handling, and the database department overriding the token.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

DEMO_TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
SALARY = "10000000-0000-4000-8000-000000000001"
ENGINEERING = "10000000-0000-4000-8000-000000000002"
NGO = "10000000-0000-4000-8000-000000000003"
OTHER = "10000000-0000-4000-8000-000000000004"

USERS: dict[str, dict[str, Any]] = {
    "mike": {
        "subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        "tenant_id": DEMO_TENANT,
        "roles": ["employee"],
        "department": "engineering",
    },
    "helen.hr": {
        "subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        "tenant_id": DEMO_TENANT,
        "roles": ["hr_manager"],
        "department": "human-resources",
    },
    "priya.manager": {
        "subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
        "tenant_id": DEMO_TENANT,
        "roles": ["manager", "approver"],
        "department": "programs",
    },
    "evan.external": {
        "subject": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
        "tenant_id": OTHER_TENANT,
        "roles": ["employee"],
        "department": "engineering",
    },
}

# Ported from scripts/verify_guard.py CHECKS: (user, resource, expected status).
MATRIX = [
    ("mike", SALARY, 404),
    ("mike", ENGINEERING, 200),
    ("helen.hr", SALARY, 200),
    ("helen.hr", ENGINEERING, 404),
    ("priya.manager", NGO, 200),
    ("priya.manager", SALARY, 404),
    ("evan.external", OTHER, 200),
    ("evan.external", SALARY, 404),
]


def bearer(token_for: Callable[..., str], username: str, **overrides: Any) -> dict[str, str]:
    user = {**USERS[username], **overrides}
    token = token_for(
        subject=user["subject"],
        username=username,
        tenant_id=user["tenant_id"],
        roles=user["roles"],
        department=user["department"],
    )
    return {"Authorization": f"Bearer {token}"}


def read(client: TestClient, resource_id: str, headers: dict[str, str], correlation_id: str) -> Any:
    return client.get(
        f"/v1/demo/resources/{resource_id}",
        headers={**headers, "X-Correlation-ID": correlation_id},
    )


@pytest.mark.parametrize(("username", "resource_id", "expected"), MATRIX)
def test_guard_matrix_matches_policy_and_audits_every_decision(
    api_client: TestClient,
    token_for: Callable[..., str],
    owner_db: Any,
    username: str,
    resource_id: str,
    expected: int,
) -> None:
    correlation_id = f"matrix-{uuid4()}"

    response = read(api_client, resource_id, bearer(token_for, username), correlation_id)

    assert response.status_code == expected
    if expected == 200:
        assert response.json()["content"].startswith("SYNTHETIC ONLY")
    rows = owner_db.fetch(
        "SELECT allowed, action, actor_subject_id, tenant_id::text AS tenant_id "
        "FROM authorization_audit_events WHERE correlation_id = $1",
        correlation_id,
    )
    assert len(rows) == 1
    assert rows[0]["allowed"] is (expected == 200)
    assert rows[0]["action"] == "resource.read"
    assert rows[0]["actor_subject_id"] == USERS[username]["subject"]
    assert rows[0]["tenant_id"] == USERS[username]["tenant_id"]


def test_anonymous_read_is_rejected(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/demo/resources/{SALARY}")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_forged_query_attributes_do_not_change_the_decision(
    api_client: TestClient, token_for: Callable[..., str]
) -> None:
    response = api_client.get(
        f"/v1/demo/resources/{SALARY}",
        params={"tenant_id": DEMO_TENANT, "roles": "hr_manager", "department": "human-resources"},
        headers=bearer(token_for, "mike"),
    )

    assert response.status_code == 404


def test_denied_and_missing_resources_return_identical_bodies(
    api_client: TestClient, token_for: Callable[..., str]
) -> None:
    headers = bearer(token_for, "mike")

    denied = read(api_client, SALARY, headers, "same-correlation")
    missing = read(api_client, str(uuid4()), headers, "same-correlation")
    cross_tenant = read(api_client, OTHER, headers, "same-correlation")

    assert denied.status_code == missing.status_code == cross_tenant.status_code == 404
    assert denied.json() == missing.json() == cross_tenant.json()


def test_database_department_overrides_token_department(
    api_client: TestClient, token_for: Callable[..., str]
) -> None:
    forged = bearer(token_for, "mike", department="programs")

    assert read(api_client, NGO, forged, f"dept-{uuid4()}").status_code == 404
    assert read(api_client, ENGINEERING, forged, f"dept-{uuid4()}").status_code == 200


def test_audit_failure_blocks_content(
    api_client: TestClient, token_for: Callable[..., str], owner_db: Any
) -> None:
    owner_db.execute("REVOKE INSERT ON authorization_audit_events FROM kribu_app")
    try:
        response = read(api_client, SALARY, bearer(token_for, "helen.hr"), f"audit-{uuid4()}")
    finally:
        owner_db.execute("GRANT INSERT ON authorization_audit_events TO kribu_app")

    assert response.status_code == 503
    assert response.json()["code"] == "audit_unavailable"
    assert "SYNTHETIC" not in response.text


def test_policy_outage_returns_503_and_is_audited(
    api_client_factory: Callable[..., TestClient], token_for: Callable[..., str], owner_db: Any
) -> None:
    client = api_client_factory(opa_url="http://127.0.0.1:9")
    correlation_id = f"opa-down-{uuid4()}"

    response = read(client, SALARY, bearer(token_for, "helen.hr"), correlation_id)

    assert response.status_code == 503
    assert response.json()["code"] == "authorization_unavailable"
    assert "SYNTHETIC" not in response.text
    rows = owner_db.fetch(
        "SELECT allowed, reason_code, policy_version FROM authorization_audit_events "
        "WHERE correlation_id = $1",
        correlation_id,
    )
    assert [(row["allowed"], row["reason_code"], row["policy_version"]) for row in rows] == [
        (False, "policy_unavailable", None)
    ]
