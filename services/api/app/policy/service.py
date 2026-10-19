from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import record_authorization_event
from app.identity.contracts import CurrentUser
from app.identity.service import get_identity_profile
from app.policy.adapters import from_demo_descriptor
from app.policy.client import OpaClient
from app.policy.contracts import (
    AuthorizationInput,
    DemoResourceResponse,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from app.policy.errors import PolicyUnavailableError, ResourceNotFoundError
from app.policy.models import DemoResourceContent, ResourceAclGrant, ResourceDescriptor


async def read_demo_resource(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    current_user: CurrentUser,
    opa_client: OpaClient,
    resource_id: UUID,
    correlation_id: str,
) -> DemoResourceResponse:
    profile = await get_identity_profile(session, current_user)
    subject = SubjectAttributes(
        tenant_id=current_user.tenant_id,
        subject_id=current_user.subject_id,
        roles=sorted(current_user.roles),
        department=profile.department,
    )
    descriptor = await session.scalar(
        select(ResourceDescriptor).where(
            ResourceDescriptor.id == resource_id,
            ResourceDescriptor.tenant_id == current_user.tenant_id,
        )
    )
    if descriptor is None:
        resource = ResourceAttributes(
            id=resource_id,
            tenant_id=current_user.tenant_id,
            resource_type="unavailable",
            classification="unmapped",
            department=None,
            owner_subject_id=None,
            grants=[],
        )
    else:
        grants = list(
            (
                await session.scalars(
                    select(ResourceAclGrant).where(
                        ResourceAclGrant.resource_id == resource_id,
                        ResourceAclGrant.tenant_id == current_user.tenant_id,
                    )
                )
            ).all()
        )
        resource = from_demo_descriptor(descriptor, grants)
    policy_input = AuthorizationInput(
        subject=subject,
        action="resource.read",
        resource=resource,
        environment=EnvironmentAttributes(purpose="demo_resource_read"),
    )
    try:
        decision = await opa_client.evaluate(policy_input)
    except PolicyUnavailableError:
        await record_authorization_event(
            session_factory,
            current_user=current_user,
            resource_id=resource_id,
            correlation_id=correlation_id,
            allowed=False,
            reason_code="policy_unavailable",
            policy_version=None,
            policy_input=policy_input,
        )
        raise

    await record_authorization_event(
        session_factory,
        current_user=current_user,
        resource_id=resource_id,
        correlation_id=correlation_id,
        allowed=descriptor is not None and decision.allow,
        reason_code="resource_unavailable" if descriptor is None else decision.reason_code,
        policy_version=decision.policy_version,
        policy_input=policy_input,
    )
    if descriptor is None or not decision.allow:
        raise ResourceNotFoundError()

    content = await session.scalar(
        select(DemoResourceContent.content).where(
            DemoResourceContent.resource_id == resource_id,
            DemoResourceContent.tenant_id == current_user.tenant_id,
        )
    )
    if content is None:
        raise ResourceNotFoundError()
    return DemoResourceResponse(
        id=descriptor.id,
        resource_type=descriptor.resource_type,
        title=descriptor.title,
        content=content,
    )
