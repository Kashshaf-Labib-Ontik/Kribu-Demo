"""The Guard authorization step: one policy decision and one audit record, failing closed.

Every protected operation (reads, document create/version, later retrieval opens) calls
``authorize()``. It never holds a database connection while waiting on OPA: the audit write
runs in its own short tenant transaction.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import record_authorization_event
from app.identity.contracts import CurrentUser
from app.policy.client import OpaClient
from app.policy.contracts import (
    AuthorizationDecision,
    AuthorizationInput,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from app.policy.errors import PolicyUnavailableError

RESOURCE_READ = "resource.read"


def subject_attributes(current_user: CurrentUser, department: str | None) -> SubjectAttributes:
    """Trusted subject: identity from the verified token, department from the database."""
    return SubjectAttributes(
        tenant_id=current_user.tenant_id,
        subject_id=current_user.subject_id,
        roles=sorted(current_user.roles),
        department=department,
    )


def unavailable_resource(resource_id: UUID, tenant_id: UUID) -> ResourceAttributes:
    """Attributes for a missing resource, so absence still costs one policy decision."""
    return ResourceAttributes(
        id=resource_id,
        tenant_id=tenant_id,
        resource_type="unavailable",
        classification="unmapped",
        department=None,
        owner_subject_id=None,
        grants=[],
    )


async def authorize(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    opa_client: OpaClient,
    current_user: CurrentUser,
    subject: SubjectAttributes,
    action: str,
    resource: ResourceAttributes,
    purpose: str,
    correlation_id: str,
    resource_found: bool = True,
) -> AuthorizationDecision:
    """Evaluate ``action`` on ``resource`` and audit the outcome before returning it.

    Raises ``PolicyUnavailableError`` (after auditing it) when OPA cannot decide, and
    ``AuditUnavailableError`` when the decision cannot be recorded. A missing resource is
    always denied with ``resource_unavailable``.
    """
    policy_input = AuthorizationInput(
        subject=subject,
        action=action,
        resource=resource,
        environment=EnvironmentAttributes(purpose=purpose),
    )
    try:
        decision = await opa_client.evaluate(policy_input)
    except PolicyUnavailableError:
        await record_authorization_event(
            session_factory,
            current_user=current_user,
            action=action,
            resource_id=resource.id,
            correlation_id=correlation_id,
            allowed=False,
            reason_code="policy_unavailable",
            policy_version=None,
            policy_input=policy_input,
        )
        raise

    allowed = resource_found and decision.allow
    reason_code = decision.reason_code if resource_found else "resource_unavailable"
    await record_authorization_event(
        session_factory,
        current_user=current_user,
        action=action,
        resource_id=resource.id,
        correlation_id=correlation_id,
        allowed=allowed,
        reason_code=reason_code,
        policy_version=decision.policy_version,
        policy_input=policy_input,
    )
    return AuthorizationDecision(
        allow=allowed, reason_code=reason_code, policy_version=decision.policy_version
    )


async def audit_unprovisioned_identity(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    current_user: CurrentUser,
    action: str,
    resource_id: UUID,
    correlation_id: str,
) -> None:
    """Record a denial that happened before policy evaluation (no active profile)."""
    await record_authorization_event(
        session_factory,
        current_user=current_user,
        action=action,
        resource_id=resource_id,
        correlation_id=correlation_id,
        allowed=False,
        reason_code="identity_not_provisioned",
        policy_version=None,
        policy_input=None,
    )
