from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.errors import AuditUnavailableError
from app.identity.contracts import CurrentUser
from app.main import app
from app.policy.adapters import from_descriptor
from app.policy.authorization import authorize, subject_attributes, unavailable_resource
from app.policy.client import OpaClient
from app.policy.contracts import (
    AccessGrant,
    AuthorizationDecision,
    AuthorizationInput,
    ResourceAttributes,
)
from app.policy.errors import PolicyUnavailableError
from app.policy.models import ResourceDescriptor

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
SUBJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
SALARY_ID = UUID("10000000-0000-4000-8000-000000000001")


USER = CurrentUser(
    subject_id=SUBJECT_ID,
    tenant_id=TENANT_ID,
    username="mike",
    roles=frozenset({"employee"}),
    department="untrusted-token-department",
)
RESOURCE = ResourceAttributes(
    id=SALARY_ID,
    tenant_id=TENANT_ID,
    resource_type="employee_record",
    classification="restricted_hr",
    department="human-resources",
    owner_subject_id="roger-synthetic",
    grants=[AccessGrant(principal_type="role", principal_id="hr_manager", action="resource.read")],
)


def opa_returning(*, allow: bool) -> OpaClient:
    opa = Mock(spec=OpaClient)
    opa.evaluate = AsyncMock(
        return_value=AuthorizationDecision(
            allow=allow,
            reason_code="allowed" if allow else "access_denied",
            policy_version="guard-v1",
        )
    )
    return cast(OpaClient, opa)


async def run_authorize(opa: OpaClient, **overrides: object) -> AuthorizationDecision:
    arguments: dict[str, object] = {
        "session_factory": cast(async_sessionmaker[AsyncSession], Mock()),
        "opa_client": opa,
        "current_user": USER,
        "subject": subject_attributes(USER, "engineering"),
        "action": "document.create",
        "resource": RESOURCE,
        "purpose": "document_upload",
        "correlation_id": "authorize-test",
    }
    arguments.update(overrides)
    return await authorize(**arguments)  # type: ignore[arg-type]


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    recorder = AsyncMock()
    monkeypatch.setattr("app.policy.authorization.record_authorization_event", recorder)
    return recorder


@pytest.mark.asyncio
async def test_authorize_sends_action_purpose_and_database_department(audit: AsyncMock) -> None:
    opa = opa_returning(allow=True)

    decision = await run_authorize(opa)

    assert decision.allow is True
    policy_input = cast(AuthorizationInput, opa.evaluate.await_args.args[0])  # type: ignore[attr-defined]
    assert policy_input.action == "document.create"
    assert policy_input.environment.purpose == "document_upload"
    assert policy_input.subject.department == "engineering"
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"] == "document.create"
    assert audit.await_args.kwargs["allowed"] is True
    assert audit.await_args.kwargs["policy_version"] == "guard-v1"


@pytest.mark.asyncio
async def test_authorize_audits_denials(audit: AsyncMock) -> None:
    decision = await run_authorize(opa_returning(allow=False))

    assert decision.allow is False
    assert audit.await_args.kwargs["allowed"] is False
    assert audit.await_args.kwargs["reason_code"] == "access_denied"


@pytest.mark.asyncio
async def test_missing_resource_is_denied_even_if_policy_allows(audit: AsyncMock) -> None:
    decision = await run_authorize(
        opa_returning(allow=True),
        resource=unavailable_resource(SALARY_ID, TENANT_ID),
        resource_found=False,
    )

    assert decision.allow is False
    assert decision.reason_code == "resource_unavailable"
    assert audit.await_args.kwargs["allowed"] is False
    assert audit.await_args.kwargs["reason_code"] == "resource_unavailable"


@pytest.mark.asyncio
async def test_policy_outage_is_audited_then_raised(audit: AsyncMock) -> None:
    opa = opa_returning(allow=True)
    opa.evaluate.side_effect = PolicyUnavailableError()  # type: ignore[attr-defined]

    with pytest.raises(PolicyUnavailableError):
        await run_authorize(opa)

    assert audit.await_args.kwargs["reason_code"] == "policy_unavailable"
    assert audit.await_args.kwargs["policy_version"] is None
    assert audit.await_args.kwargs["allowed"] is False


@pytest.mark.asyncio
async def test_audit_failure_withholds_the_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.policy.authorization.record_authorization_event",
        AsyncMock(side_effect=AuditUnavailableError()),
    )

    with pytest.raises(AuditUnavailableError):
        await run_authorize(opa_returning(allow=True))


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"result": "guard-v0"}),
        httpx.Response(200, json=["guard-v1"]),
        httpx.Response(500, json={}),
        httpx.Response(200, text="not json"),
    ],
    ids=["wrong-version", "not-an-object", "server-error", "not-json"],
)
async def test_opa_readiness_fails_closed(response: httpx.Response) -> None:
    client = OpaClient("http://opa.test", 1, "guard-v1")
    response.request = httpx.Request("GET", "http://opa.test/v1/data/kribu/authz/policy_version")
    client._client.get = AsyncMock(return_value=response)  # type: ignore[method-assign]
    try:
        assert await client.ready() is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_opa_readiness_accepts_expected_version() -> None:
    client = OpaClient("http://opa.test", 1, "guard-v1")
    response = httpx.Response(
        200,
        json={"result": "guard-v1"},
        request=httpx.Request("GET", "http://opa.test/v1/data/kribu/authz/policy_version"),
    )
    client._client.get = AsyncMock(return_value=response)  # type: ignore[method-assign]
    try:
        assert await client.ready() is True
    finally:
        await client.close()


def test_unknown_classification_maps_to_unmapped() -> None:
    descriptor = ResourceDescriptor(
        id=SALARY_ID,
        tenant_id=TENANT_ID,
        resource_type="employee_record",
        classification="top_secret",
        department="human-resources",
        owner_subject_id=None,
        title="Synthetic",
    )

    assert from_descriptor(descriptor, []).classification == "unmapped"
