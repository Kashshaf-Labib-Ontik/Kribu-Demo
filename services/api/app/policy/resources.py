from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.policy.models import ResourceAclGrant, ResourceDescriptor


async def load_resource(
    session: AsyncSession, *, tenant_id: UUID, resource_id: UUID
) -> tuple[ResourceDescriptor | None, list[ResourceAclGrant]]:
    """A tenant's resource descriptor and all of its ACL grants, in one query."""
    rows = (
        await session.execute(
            select(ResourceDescriptor, ResourceAclGrant)
            .outerjoin(
                ResourceAclGrant,
                and_(
                    ResourceAclGrant.resource_id == ResourceDescriptor.id,
                    ResourceAclGrant.tenant_id == ResourceDescriptor.tenant_id,
                ),
            )
            .where(ResourceDescriptor.id == resource_id, ResourceDescriptor.tenant_id == tenant_id)
        )
    ).all()
    if not rows:
        return None, []
    return rows[0][0], [grant for _, grant in rows if grant is not None]
