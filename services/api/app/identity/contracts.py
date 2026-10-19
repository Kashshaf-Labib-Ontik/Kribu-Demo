from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RealmAccess(BaseModel):
    roles: list[str] = Field(default_factory=list)


class AccessTokenClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str = Field(min_length=1)
    preferred_username: str = Field(min_length=1)
    tenant_id: UUID
    department: str | None = None
    realm_access: RealmAccess


class CurrentUser(BaseModel):
    subject_id: str
    tenant_id: UUID
    username: str
    roles: frozenset[str]
    department: str | None = None


class IdentityResponse(BaseModel):
    user_id: UUID
    subject_id: str
    username: str
    display_name: str
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    department: str | None
    roles: list[str]
