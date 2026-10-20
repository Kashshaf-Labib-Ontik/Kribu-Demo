from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

Classification = Literal["internal", "restricted_hr"]
Domain = Literal["ngo", "hr", "complaints"]
PrincipalType = Literal["subject", "role", "department"]


def normalize_text(value: str) -> str:
    """NFC + trim, so Bangla and other composed text compares and indexes consistently."""
    return unicodedata.normalize("NFC", value).strip()


def _is_control(character: str) -> bool:
    # Only Cc: format characters (Cf) such as ZWJ/ZWNJ are meaningful in Bangla text.
    return unicodedata.category(character) == "Cc"


def strip_control_characters(value: str) -> str:
    return "".join(character for character in value if not _is_control(character))


def clean_text(value: str) -> str:
    """Normalized text without control characters (PostgreSQL rejects NUL in text)."""
    if any(_is_control(character) for character in value):
        raise ValueError("control characters are not allowed")
    return normalize_text(value)


NormalizedText = Annotated[str, AfterValidator(clean_text)]


class GrantInput(BaseModel):
    """A read grant requested at upload. The action is always ``resource.read``."""

    model_config = ConfigDict(extra="forbid")

    principal_type: PrincipalType
    principal_id: Annotated[NormalizedText, Field(min_length=1, max_length=160)]


class DocumentMetadataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[NormalizedText, Field(min_length=1, max_length=200)]
    classification: Classification
    department: Annotated[NormalizedText, Field(min_length=1, max_length=120)] | None = None
    domain: Domain | None = None
    project: Annotated[NormalizedText, Field(min_length=1, max_length=200)] | None = None
    document_date: date | None = None
    grants: list[GrantInput] = Field(default_factory=list, max_length=50)


class GrantResponse(BaseModel):
    principal_type: str
    principal_id: str
    action: str


class DocumentVersionResponse(BaseModel):
    id: UUID
    version_number: int
    sha256: str
    size_bytes: int
    media_type: str
    original_filename: str
    status: str
    ingestion_status: str | None = None
    created_at: datetime


class DocumentResponse(BaseModel):
    id: UUID
    title: str
    classification: str
    department: str | None
    domain: str | None
    project: str | None
    document_date: date | None
    latest_version_number: int
    created_at: datetime
    grants: list[GrantResponse]
    versions: list[DocumentVersionResponse]


class UploadResponse(BaseModel):
    document_id: UUID
    version: DocumentVersionResponse
    duplicate_of: UUID | None = None


class DocumentIngestionStatusResponse(BaseModel):
    document_id: UUID
    version_id: UUID
    status: Literal["queued", "processing", "ready", "quarantined"]
    retry_after_seconds: int | None = None


class DocumentPreviewBlockResponse(BaseModel):
    ordinal: int
    block_type: str
    text: str
    locator: dict[str, object]


class DocumentPreviewResponse(BaseModel):
    document_id: UUID
    version_id: UUID
    parser_name: str
    parser_version: str
    normalization_version: str
    blocks: list[DocumentPreviewBlockResponse]
    next_cursor: int | None = None
