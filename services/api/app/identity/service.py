from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.contracts import CurrentUser, IdentityResponse
from app.identity.errors import IdentityNotProvisionedError
from app.identity.models import Tenant, UserProfile


async def get_identity_profile(
    session: AsyncSession,
    current_user: CurrentUser,
) -> IdentityResponse:
    statement = (
        select(UserProfile, Tenant)
        .join(Tenant, Tenant.id == UserProfile.tenant_id)
        .where(
            UserProfile.external_subject == current_user.subject_id,
            UserProfile.is_active.is_(True),
        )
    )
    result = await session.execute(statement)
    row = result.one_or_none()
    if row is None:
        raise IdentityNotProvisionedError()

    profile, tenant = row
    if profile.tenant_id != current_user.tenant_id:
        raise IdentityNotProvisionedError()

    return IdentityResponse(
        user_id=profile.id,
        subject_id=current_user.subject_id,
        username=profile.username,
        display_name=profile.display_name,
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        department=profile.department,
        roles=sorted(current_user.roles),
    )
