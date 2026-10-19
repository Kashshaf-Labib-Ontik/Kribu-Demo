from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.contracts import CurrentUser
from app.identity.errors import IdentityNotProvisionedError
from app.identity.service import get_identity_profile
from app.identity.tenancy import tenant_transaction
from app.policy.adapters import from_descriptor
from app.policy.authorization import (
    RESOURCE_READ,
    audit_unprovisioned_identity,
    authorize,
    subject_attributes,
    unavailable_resource,
)
from app.policy.client import OpaClient
from app.policy.contracts import DemoResourceResponse
from app.policy.errors import ResourceNotFoundError
from app.policy.models import DemoResourceContent
from app.policy.resources import load_resource

DEMO_READ_PURPOSE = "demo_resource_read"


async def read_demo_resource(
    session_factory: async_sessionmaker[AsyncSession],
    current_user: CurrentUser,
    opa_client: OpaClient,
    resource_id: UUID,
    correlation_id: str,
) -> DemoResourceResponse:
    # tx1: identity and resource attributes, released before the policy call.
    try:
        async with tenant_transaction(session_factory, current_user) as session:
            profile = await get_identity_profile(session, current_user)
            descriptor, grants = await load_resource(
                session, tenant_id=current_user.tenant_id, resource_id=resource_id
            )
    except IdentityNotProvisionedError:
        await audit_unprovisioned_identity(
            session_factory=session_factory,
            current_user=current_user,
            action=RESOURCE_READ,
            resource_id=resource_id,
            correlation_id=correlation_id,
        )
        raise

    resource = (
        from_descriptor(descriptor, grants)
        if descriptor is not None
        else unavailable_resource(resource_id, current_user.tenant_id)
    )

    # Policy decision and its audit record; no connection is held while OPA answers.
    decision = await authorize(
        session_factory=session_factory,
        opa_client=opa_client,
        current_user=current_user,
        subject=subject_attributes(current_user, profile.department),
        action=RESOURCE_READ,
        resource=resource,
        purpose=DEMO_READ_PURPOSE,
        correlation_id=correlation_id,
        resource_found=descriptor is not None,
    )
    if descriptor is None or not decision.allow:
        raise ResourceNotFoundError()

    # Content is read only after the allow decision is durably audited.
    async with tenant_transaction(session_factory, current_user) as session:
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
