from __future__ import annotations

from app.policy.contracts import AccessGrant, ResourceAttributes
from app.policy.models import ResourceAclGrant, ResourceDescriptor

DEMO_CLASSIFICATIONS = {"internal": "internal", "restricted_hr": "restricted_hr"}


def from_demo_descriptor(
    descriptor: ResourceDescriptor,
    grants: list[ResourceAclGrant],
) -> ResourceAttributes:
    """Map trusted synthetic-source metadata to the canonical Guard contract."""
    return ResourceAttributes(
        id=descriptor.id,
        tenant_id=descriptor.tenant_id,
        resource_type=descriptor.resource_type,
        classification=DEMO_CLASSIFICATIONS.get(descriptor.classification, "unmapped"),
        department=descriptor.department,
        owner_subject_id=descriptor.owner_subject_id,
        grants=[
            AccessGrant(
                principal_type=grant.principal_type,
                principal_id=grant.principal_id,
                action=grant.action,
            )
            for grant in grants
        ],
    )
