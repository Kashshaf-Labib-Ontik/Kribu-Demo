from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Realm roles seeded in infra/keycloak/kribu-demo-realm.json; role grants must name one.
CANONICAL_ROLES = frozenset(
    {"employee", "manager", "hr_manager", "approver", "administrator", "auditor"}
)


class SubjectAttributes(BaseModel):
    tenant_id: UUID
    subject_id: str
    roles: list[str]
    department: str | None


class AccessGrant(BaseModel):
    principal_type: str
    principal_id: str
    action: str


class ResourceAttributes(BaseModel):
    id: UUID
    tenant_id: UUID
    resource_type: str
    classification: str
    department: str | None
    owner_subject_id: str | None
    grants: list[AccessGrant]


class EnvironmentAttributes(BaseModel):
    purpose: str


class AuthorizationInput(BaseModel):
    subject: SubjectAttributes
    action: str
    resource: ResourceAttributes
    environment: EnvironmentAttributes


class AuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    allow: bool
    reason_code: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)


class OpaResponse(BaseModel):
    result: AuthorizationDecision


class DemoResourceResponse(BaseModel):
    id: UUID
    resource_type: str
    title: str
    content: str
