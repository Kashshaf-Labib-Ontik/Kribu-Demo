"""Authorization-first hybrid retrieval over active document index generations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import monotonic
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.errors import ModelProviderError
from app.brain.contracts import (
    Evidence,
    IndexContractResponse,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalScores,
    SourceReference,
)
from app.brain.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    INDEX_CONTRACT,
    EmbeddingProvider,
)
from app.brain.errors import RetrievalAuditUnavailableError, RetrievalUnavailableError
from app.brain.models import (
    DocumentIndexGeneration,
    DocumentIndexHead,
    DocumentSearchChunk,
    RetrievalAuditEvent,
)
from app.core.config import Settings
from app.documents.models import Document, DocumentVersion
from app.identity.contracts import CurrentUser, IdentityResponse
from app.identity.errors import IdentityNotProvisionedError
from app.identity.service import get_identity_profile
from app.identity.tenancy import tenant_transaction
from app.policy.adapters import from_descriptor
from app.policy.authorization import (
    RESOURCE_READ,
    audit_unprovisioned_identity,
    authorize,
    subject_attributes,
)
from app.policy.client import OpaClient
from app.policy.contracts import ResourceAttributes
from app.policy.models import ResourceAclGrant, ResourceDescriptor

RETRIEVAL_PURPOSE = "authorized_retrieval"


@dataclass(frozen=True)
class RetrievalContext:
    session_factory: async_sessionmaker[AsyncSession]
    opa_client: OpaClient
    embedding_provider: EmbeddingProvider
    current_user: CurrentUser
    correlation_id: str
    settings: Settings


@dataclass
class _Candidate:
    document: Document
    version: DocumentVersion
    descriptor: ResourceDescriptor
    generation: DocumentIndexGeneration
    grants: list[ResourceAclGrant]


@dataclass
class _Ranked:
    chunk: DocumentSearchChunk
    title: str
    lexical_rank: int | None = None
    semantic_rank: int | None = None

    def score(self, rrf_k: int) -> float:
        value = 0.0
        if self.lexical_rank is not None:
            value += 1 / (rrf_k + self.lexical_rank)
        if self.semantic_rank is not None:
            value += 1 / (rrf_k + self.semantic_rank)
        return value


async def search(context: RetrievalContext, request: RetrievalRequest) -> RetrievalResponse:
    started = monotonic()
    retrieval_id = uuid4()
    user = context.current_user
    try:
        async with tenant_transaction(context.session_factory, user) as session:
            profile: IdentityResponse = await get_identity_profile(session, user)
            candidates = await _load_candidates(session, request)
    except IdentityNotProvisionedError:
        await audit_unprovisioned_identity(
            session_factory=context.session_factory,
            current_user=user,
            action=RESOURCE_READ,
            resource_id=retrieval_id,
            correlation_id=context.correlation_id,
        )
        raise

    allowed: list[_Candidate] = []
    policy_versions: set[str] = set()
    subject = subject_attributes(user, profile.department)
    for candidate in candidates:
        resource: ResourceAttributes = from_descriptor(candidate.descriptor, candidate.grants)
        decision = await authorize(
            session_factory=context.session_factory,
            opa_client=context.opa_client,
            current_user=user,
            subject=subject,
            action=RESOURCE_READ,
            resource=resource,
            purpose=RETRIEVAL_PURPOSE,
            correlation_id=context.correlation_id,
        )
        policy_versions.add(decision.policy_version)
        if decision.allow:
            allowed.append(candidate)

    if not allowed:
        response = _response(retrieval_id, [])
        await _record_retrieval(
            context,
            retrieval_id=retrieval_id,
            request=request,
            evidence=[],
            policy_version=_policy_version(policy_versions),
            duration_ms=_elapsed_ms(started),
        )
        return response

    try:
        query_vector = await context.embedding_provider.embed_query(request.query)
    except ModelProviderError as exc:
        raise RetrievalUnavailableError() from exc
    if len(query_vector) != EMBEDDING_DIMENSION:
        raise RetrievalUnavailableError()

    allowed_ids = [candidate.document.id for candidate in allowed]
    async with tenant_transaction(context.session_factory, user) as session:
        ranked = await _hybrid_candidates(
            session,
            request=request,
            allowed_document_ids=allowed_ids,
            query_vector=query_vector,
            candidate_limit=context.settings.retrieval_candidate_limit,
        )
    evidence = _fuse(
        ranked,
        limit=request.limit,
        rrf_k=context.settings.retrieval_rrf_k,
        per_document=context.settings.retrieval_max_chunks_per_document,
    )
    await _record_retrieval(
        context,
        retrieval_id=retrieval_id,
        request=request,
        evidence=evidence,
        policy_version=_policy_version(policy_versions),
        duration_ms=_elapsed_ms(started),
    )
    return _response(retrieval_id, evidence)


async def _load_candidates(session: AsyncSession, request: RetrievalRequest) -> list[_Candidate]:
    statement = (
        select(
            Document,
            DocumentVersion,
            ResourceDescriptor,
            DocumentIndexGeneration,
            ResourceAclGrant,
        )
        .join(
            DocumentVersion,
            and_(
                DocumentVersion.tenant_id == Document.tenant_id,
                DocumentVersion.document_id == Document.id,
                DocumentVersion.version_number == Document.latest_version_number,
            ),
        )
        .join(
            DocumentIndexHead,
            and_(
                DocumentIndexHead.tenant_id == DocumentVersion.tenant_id,
                DocumentIndexHead.document_version_id == DocumentVersion.id,
            ),
        )
        .join(
            DocumentIndexGeneration,
            and_(
                DocumentIndexGeneration.tenant_id == DocumentIndexHead.tenant_id,
                DocumentIndexGeneration.id == DocumentIndexHead.active_generation_id,
                DocumentIndexGeneration.state == "ready",
                DocumentIndexGeneration.index_contract == INDEX_CONTRACT,
            ),
        )
        .join(
            ResourceDescriptor,
            and_(
                ResourceDescriptor.tenant_id == Document.tenant_id,
                ResourceDescriptor.id == Document.id,
            ),
        )
        .outerjoin(
            ResourceAclGrant,
            and_(
                ResourceAclGrant.tenant_id == ResourceDescriptor.tenant_id,
                ResourceAclGrant.resource_id == ResourceDescriptor.id,
            ),
        )
        .order_by(Document.id)
    )
    filters = request.filters
    if filters.domain is not None:
        statement = statement.where(Document.domain == filters.domain)
    if filters.project is not None:
        statement = statement.where(func.lower(Document.project) == filters.project.lower())
    if filters.document_date_from is not None:
        statement = statement.where(Document.document_date >= filters.document_date_from)
    if filters.document_date_to is not None:
        statement = statement.where(Document.document_date <= filters.document_date_to)

    grouped: dict[UUID, _Candidate] = {}
    for document, version, descriptor, generation, grant in (
        await session.execute(statement)
    ).all():
        candidate = grouped.get(document.id)
        if candidate is None:
            candidate = _Candidate(document, version, descriptor, generation, [])
            grouped[document.id] = candidate
        if grant is not None:
            candidate.grants.append(grant)
    return list(grouped.values())


async def _hybrid_candidates(
    session: AsyncSession,
    *,
    request: RetrievalRequest,
    allowed_document_ids: list[UUID],
    query_vector: list[float],
    candidate_limit: int,
) -> dict[UUID, _Ranked]:
    await session.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
    query = func.websearch_to_tsquery("english", request.query)
    lexical_score = func.ts_rank_cd(DocumentSearchChunk.search_vector, query)
    lexical = (
        await session.execute(
            select(DocumentSearchChunk, ResourceDescriptor.title, lexical_score.label("score"))
            .join(
                DocumentIndexHead,
                DocumentIndexHead.active_generation_id == DocumentSearchChunk.generation_id,
            )
            .join(
                DocumentIndexGeneration,
                DocumentIndexGeneration.id == DocumentSearchChunk.generation_id,
            )
            .join(ResourceDescriptor, ResourceDescriptor.id == DocumentSearchChunk.document_id)
            .where(
                DocumentSearchChunk.document_id.in_(allowed_document_ids),
                DocumentSearchChunk.search_vector.op("@@")(query),
                DocumentIndexGeneration.index_contract == INDEX_CONTRACT,
                DocumentIndexGeneration.state == "ready",
            )
            .order_by(lexical_score.desc(), DocumentSearchChunk.id)
            .limit(candidate_limit)
        )
    ).all()
    distance = DocumentSearchChunk.embedding.cosine_distance(query_vector)
    semantic = (
        await session.execute(
            select(DocumentSearchChunk, ResourceDescriptor.title, distance.label("distance"))
            .join(
                DocumentIndexHead,
                DocumentIndexHead.active_generation_id == DocumentSearchChunk.generation_id,
            )
            .join(
                DocumentIndexGeneration,
                DocumentIndexGeneration.id == DocumentSearchChunk.generation_id,
            )
            .join(ResourceDescriptor, ResourceDescriptor.id == DocumentSearchChunk.document_id)
            .where(
                DocumentSearchChunk.document_id.in_(allowed_document_ids),
                DocumentIndexGeneration.index_contract == INDEX_CONTRACT,
                DocumentIndexGeneration.state == "ready",
            )
            .order_by(distance, DocumentSearchChunk.id)
            .limit(candidate_limit)
        )
    ).all()

    ranked: dict[UUID, _Ranked] = {}
    for rank, (raw_chunk, raw_title, _) in enumerate(lexical, start=1):
        chunk = cast(DocumentSearchChunk, raw_chunk)
        title = cast(str, raw_title)
        ranked[chunk.id] = _Ranked(chunk=chunk, title=title, lexical_rank=rank)
    for rank, (raw_chunk, raw_title, _) in enumerate(semantic, start=1):
        chunk = cast(DocumentSearchChunk, raw_chunk)
        title = cast(str, raw_title)
        item = ranked.setdefault(chunk.id, _Ranked(chunk=chunk, title=title))
        item.semantic_rank = rank
    return ranked


def _fuse(
    ranked: dict[UUID, _Ranked], *, limit: int, rrf_k: int, per_document: int
) -> list[Evidence]:
    ordered = sorted(ranked.values(), key=lambda item: (-item.score(rrf_k), str(item.chunk.id)))
    counts: defaultdict[UUID, int] = defaultdict(int)
    evidence: list[Evidence] = []
    for item in ordered:
        if counts[item.chunk.document_id] >= per_document:
            continue
        counts[item.chunk.document_id] += 1
        evidence.append(
            Evidence(
                rank=len(evidence) + 1,
                chunk_id=item.chunk.id,
                document_id=item.chunk.document_id,
                version_id=item.chunk.document_version_id,
                title=item.title,
                excerpt=item.chunk.text,
                source_references=[
                    SourceReference.model_validate(reference)
                    for reference in item.chunk.source_references
                ],
                scores=RetrievalScores(
                    lexical_rank=item.lexical_rank,
                    semantic_rank=item.semantic_rank,
                    fusion_score=round(item.score(rrf_k), 8),
                ),
            )
        )
        if len(evidence) >= limit:
            break
    return evidence


async def _record_retrieval(
    context: RetrievalContext,
    *,
    retrieval_id: UUID,
    request: RetrievalRequest,
    evidence: list[Evidence],
    policy_version: str | None,
    duration_ms: int,
) -> None:
    try:
        async with tenant_transaction(context.session_factory, context.current_user) as session:
            session.add(
                RetrievalAuditEvent(
                    id=uuid4(),
                    tenant_id=context.current_user.tenant_id,
                    actor_subject_id=context.current_user.subject_id,
                    retrieval_id=retrieval_id,
                    correlation_id=context.correlation_id,
                    mode="hybrid",
                    policy_version=policy_version,
                    embedding_provider=EMBEDDING_PROVIDER,
                    embedding_model=EMBEDDING_MODEL,
                    embedding_dimension=EMBEDDING_DIMENSION,
                    chunker_version="structure-v1",
                    safe_filters=request.filters.model_dump(mode="json", exclude_none=True),
                    evidence_ids=[str(item.chunk_id) for item in evidence],
                    result_count=len(evidence),
                    duration_ms=duration_ms,
                )
            )
    except SQLAlchemyError as exc:
        raise RetrievalAuditUnavailableError() from exc


def _response(retrieval_id: UUID, evidence: list[Evidence]) -> RetrievalResponse:
    return RetrievalResponse(
        retrieval_id=retrieval_id,
        evidence=evidence,
        index_contract=IndexContractResponse(
            provider=EMBEDDING_PROVIDER,
            model=EMBEDDING_MODEL,
            dimension=EMBEDDING_DIMENSION,
            chunker_version="structure-v1",
        ),
    )


def _policy_version(versions: set[str]) -> str | None:
    return next(iter(versions)) if len(versions) == 1 else None


def _elapsed_ms(started: float) -> int:
    return max(0, round((monotonic() - started) * 1000))
