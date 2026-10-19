from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.contracts import CurrentUser
from app.identity.models import Tenant, UserProfile
from app.main import app
from app.policy.client import OpaClient
from app.policy.contracts import AuthorizationDecision, AuthorizationInput
from app.policy.errors import AuditUnavailableError, PolicyUnavailableError, ResourceNotFoundError
from app.policy.models import ResourceAclGrant, ResourceDescriptor
from app.policy.service import read_demo_resource

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
SUBJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
SALARY_ID = UUID("10000000-0000-4000-8000-000000000001")


def setup_read(
    *, allowed: bool
) -> tuple[AsyncSession, async_sessionmaker[AsyncSession], CurrentUser, OpaClient, AsyncMock]:
    user = CurrentUser(
        subject_id=SUBJECT_ID,
        tenant_id=TENANT_ID,
        username="mike",
        roles=frozenset({"employee"}),
        department="untrusted-token-department",
    )
    tenant = Tenant(id=TENANT_ID, slug="kribu-demo", name="KRIBU Demo Software")
    profile = UserProfile(
        id=UUID(SUBJECT_ID),
        tenant_id=TENANT_ID,
        external_subject=SUBJECT_ID,
        username="mike",
        display_name="Mike",
        department="engineering",
        is_active=True,
    )
    descriptor = ResourceDescriptor(
        id=SALARY_ID,
        tenant_id=TENANT_ID,
        resource_type="employee_record",
        classification="restricted_hr",
        department="human-resources",
        owner_subject_id="roger-synthetic",
        title="Synthetic salary record",
    )
    grant = ResourceAclGrant(
        id=UUID("20000000-0000-4000-8000-000000000001"),
        tenant_id=TENANT_ID,
        resource_id=SALARY_ID,
        principal_type="role",
        principal_id="hr_manager",
        action="resource.read",
    )
    row = Mock()
    row.one_or_none.return_value = (profile, tenant)
    grants_result = Mock()
    grants_result.all.return_value = [grant]
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = row
    session.scalar.side_effect = [descriptor, "SYNTHETIC ONLY: private content"]
    session.scalars.return_value = grants_result
    opa = Mock(spec=OpaClient)
    opa.evaluate = AsyncMock(
        return_value=AuthorizationDecision(
            allow=allowed,
            reason_code="allowed" if allowed else "access_denied",
            policy_version="guard-v1",
        )
    )
    audit = AsyncMock()
    return (
        session,
        cast(async_sessionmaker[AsyncSession], Mock()),
        user,
        cast(OpaClient, opa),
        audit,
    )


@pytest.mark.asyncio
async def test_denial_never_loads_content_and_uses_database_department(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, factory, user, opa, audit = setup_read(allowed=False)
    monkeypatch.setattr("app.policy.service.record_authorization_event", audit)

    with pytest.raises(ResourceNotFoundError):
        await read_demo_resource(session, factory, user, opa, SALARY_ID, "policy-test")

    assert session.scalar.await_count == 1
    policy_input = cast(AuthorizationInput, opa.evaluate.await_args.args[0])  # type: ignore[attr-defined]
    assert policy_input.subject.department == "engineering"
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["allowed"] is False


@pytest.mark.asyncio
async def test_allowed_read_fetches_content_after_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    session, factory, user, opa, audit = setup_read(allowed=True)
    monkeypatch.setattr("app.policy.service.record_authorization_event", audit)

    resource = await read_demo_resource(session, factory, user, opa, SALARY_ID, "policy-test")

    assert resource.content.startswith("SYNTHETIC ONLY")
    assert session.scalar.await_count == 2
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["allowed"] is True


@pytest.mark.asyncio
async def test_audit_failure_prevents_content_read(monkeypatch: pytest.MonkeyPatch) -> None:
    session, factory, user, opa, _ = setup_read(allowed=True)
    monkeypatch.setattr(
        "app.policy.service.record_authorization_event",
        AsyncMock(side_effect=AuditUnavailableError()),
    )

    with pytest.raises(AuditUnavailableError):
        await read_demo_resource(session, factory, user, opa, SALARY_ID, "policy-test")

    assert session.scalar.await_count == 1


@pytest.mark.asyncio
async def test_missing_resource_still_checks_policy_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, factory, user, opa, audit = setup_read(allowed=False)
    session.scalar.side_effect = [None]
    monkeypatch.setattr("app.policy.service.record_authorization_event", audit)

    with pytest.raises(ResourceNotFoundError):
        await read_demo_resource(session, factory, user, opa, SALARY_ID, "missing-test")

    assert session.scalar.await_count == 1
    opa.evaluate.assert_awaited_once()  # type: ignore[attr-defined]
    assert audit.await_args.kwargs["reason_code"] == "resource_unavailable"


@pytest.mark.asyncio
async def test_missing_resource_reports_policy_outage_without_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, factory, user, opa, audit = setup_read(allowed=False)
    session.scalar.side_effect = [None]
    opa.evaluate.side_effect = PolicyUnavailableError()  # type: ignore[attr-defined]
    monkeypatch.setattr("app.policy.service.record_authorization_event", audit)

    with pytest.raises(PolicyUnavailableError):
        await read_demo_resource(session, factory, user, opa, SALARY_ID, "outage-test")

    assert session.scalar.await_count == 1
    assert audit.await_args.kwargs["reason_code"] == "policy_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"result": True},
        {"result": {"allow": "yes"}},
        {"result": {"allow": True, "reason_code": "allowed", "policy_version": "wrong"}},
    ],
)
async def test_opa_malformed_or_missing_decision_fails_closed(payload: dict[str, object]) -> None:
    client = OpaClient("http://opa.test", 1, "guard-v1")
    response = httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", "http://opa.test/v1/data/kribu/authz/decision"),
    )
    client._client.post = AsyncMock(return_value=response)  # type: ignore[method-assign]
    policy_input = Mock(spec=AuthorizationInput)
    policy_input.model_dump.return_value = {}
    try:
        with pytest.raises(PolicyUnavailableError):
            await client.evaluate(cast(AuthorizationInput, policy_input))
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_opa_timeout_fails_closed() -> None:
    client = OpaClient("http://opa.test", 1, "guard-v1")
    client._client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))  # type: ignore[method-assign]
    policy_input = Mock(spec=AuthorizationInput)
    policy_input.model_dump.return_value = {}
    try:
        with pytest.raises(PolicyUnavailableError):
            await client.evaluate(cast(AuthorizationInput, policy_input))
    finally:
        await client.close()


def test_demo_resource_requires_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.get(f"/v1/demo/resources/{SALARY_ID}")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
