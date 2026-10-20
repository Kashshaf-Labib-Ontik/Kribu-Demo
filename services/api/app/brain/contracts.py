from __future__ import annotations

import unicodedata
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _normalize_query(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


QueryText = Annotated[str, AfterValidator(_normalize_query), Field(min_length=1, max_length=1000)]


class RetrievalFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["ngo", "hr", "complaints"] | None = None
    project: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def ordered_dates(self) -> RetrievalFilters:
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must not exceed document_date_to")
        return self


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: QueryText
    limit: int = Field(default=8, ge=1, le=20)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class SourceReference(BaseModel):
    block_id: UUID
    locator: dict[str, object]
    start_character: int | None = None
    end_character: int | None = None


class RetrievalScores(BaseModel):
    lexical_rank: int | None
    semantic_rank: int | None
    fusion_score: float


class Evidence(BaseModel):
    rank: int
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    title: str
    excerpt: str
    source_references: list[SourceReference]
    scores: RetrievalScores
    untrusted_source: Literal[True] = True


class IndexContractResponse(BaseModel):
    provider: str
    model: str
    dimension: int
    chunker_version: str


class RetrievalResponse(BaseModel):
    retrieval_id: UUID
    mode: Literal["hybrid"] = "hybrid"
    evidence: list[Evidence]
    index_contract: IndexContractResponse


class ChunkDraft(BaseModel):
    ordinal: int
    text: str
    source_references: list[SourceReference]
    content_hash: bytes
