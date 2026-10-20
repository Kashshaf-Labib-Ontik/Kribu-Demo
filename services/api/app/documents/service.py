"""Document upload lifecycle: create, version, and read, all through the Guard.

Order for uploads: validate metadata and ACL -> hash and sniff the bytes -> idempotency
lookup (fingerprint includes the file hash) -> ``authorize()`` (audited) -> own-document
duplicate check -> store the original -> one insert transaction. No database connection is
held while OPA answers or while bytes are hashed or copied.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from app.documents.contracts import (
    DocumentIngestionStatusResponse,
    DocumentMetadataInput,
    DocumentPreviewBlockResponse,
    DocumentPreviewResponse,
    DocumentResponse,
    DocumentVersionResponse,
    GrantResponse,
    UploadResponse,
)
from app.documents.errors import (
    AclInvalidError,
    AclRequiredError,
    DocumentPreviewUnavailableError,
    IdempotencyKeyInvalidError,
    IdempotencyKeyRequiredError,
    IdempotencyKeyReusedError,
    MetadataInvalidError,
    UploadForbiddenError,
)
from app.documents.models import (
    Document,
    DocumentContentBlock,
    DocumentExtraction,
    DocumentIngestionJob,
    DocumentVersion,
    UploadRequest,
)
from app.documents.storage import ObjectStore
from app.documents.validation import AnalyzedFile, analyze_upload, display_filename
from app.identity.contracts import CurrentUser, IdentityResponse
from app.identity.errors import IdentityNotProvisionedError
from app.identity.models import UserProfile
from app.identity.service import get_identity_profile
from app.identity.tenancy import tenant_transaction
from app.ingestion.service import QUARANTINED, READY, queue_document_ingestion
from app.policy.adapters import from_descriptor
from app.policy.authorization import (
    RESOURCE_READ,
    audit_unprovisioned_identity,
    authorize,
    subject_attributes,
    unavailable_resource,
)
from app.policy.client import OpaClient
from app.policy.contracts import CANONICAL_ROLES, AccessGrant, ResourceAttributes
from app.policy.errors import ResourceNotFoundError
from app.policy.models import ResourceAclGrant, ResourceDescriptor
from app.policy.resources import load_resource

DOCUMENT_CREATE = "document.create"
DOCUMENT_VERSION_CREATE = "document.version.create"
UPLOAD_PURPOSE = "document_upload"
READ_PURPOSE = "document_read"
DOCUMENT_RESOURCE_TYPE = "document"
STORED = "stored"
IDEMPOTENCY_KEY_PATTERN = re.compile(r"[A-Za-z0-9._:-]{8,128}")
DUPLICATE_CANDIDATES = 20


@dataclass(frozen=True)
class DocumentContext:
    session_factory: async_sessionmaker[AsyncSession]
    opa_client: OpaClient
    store: ObjectStore
    current_user: CurrentUser
    correlation_id: str
    max_file_bytes: int


@dataclass(frozen=True)
class UploadOutcome:
    status_code: int
    body: dict[str, Any]
    ingestion_job_id: UUID | None = None


@dataclass(frozen=True)
class DownloadOutcome:
    content: bytes
    filename: str
    media_type: str


class _SameAsLatestError(Exception):
    """Raised inside the version transaction to roll back the counter bump.

    Carries the already-built response: the rollback expires ORM instances.
    """

    def __init__(self, outcome: UploadOutcome, version_id: UUID) -> None:
        super().__init__("upload matches the latest version")
        self.outcome = outcome
        self.version_id = version_id


# --- request validation ------------------------------------------------------------------


def require_idempotency_key(value: str | None) -> str:
    if value is None or not value.strip():
        raise IdempotencyKeyRequiredError()
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise IdempotencyKeyInvalidError()
    return value


def parse_metadata(raw: str) -> DocumentMetadataInput:
    try:
        return DocumentMetadataInput.model_validate_json(raw)
    except ValidationError as exc:
        if any(error["loc"][:1] == ("classification",) for error in exc.errors()):
            raise MetadataInvalidError("classification_invalid") from exc
        raise MetadataInvalidError() from exc


def requested_grants(metadata: DocumentMetadataInput) -> list[AccessGrant]:
    """Explicit read grants only (no implicit uploader access), deduplicated."""
    if not metadata.grants:
        raise AclRequiredError()
    grants: dict[tuple[str, str], AccessGrant] = {}
    for grant in metadata.grants:
        if grant.principal_type == "role" and grant.principal_id not in CANONICAL_ROLES:
            raise AclInvalidError()
        if grant.principal_type == "department" and grant.principal_id != metadata.department:
            raise AclInvalidError()
        grants[(grant.principal_type, grant.principal_id)] = AccessGrant(
            principal_type=grant.principal_type,
            principal_id=grant.principal_id,
            action=RESOURCE_READ,
        )
    return list(grants.values())


def request_fingerprint(route: str, target: str, payload: dict[str, Any], sha256: bytes) -> bytes:
    canonical = json.dumps(
        {"route": route, "target": target, "payload": payload, "sha256": sha256.hex()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).digest()


# --- shared helpers ----------------------------------------------------------------------


async def _analyze(context: DocumentContext, upload: UploadFile) -> tuple[AnalyzedFile, str]:
    filename = display_filename(upload.filename)
    analyzed = await run_in_threadpool(
        analyze_upload, upload.file, filename, context.max_file_bytes
    )
    return analyzed, filename


async def _find_request(
    session: AsyncSession, current_user: CurrentUser, key: str
) -> UploadRequest | None:
    return await session.scalar(
        select(UploadRequest).where(
            UploadRequest.tenant_id == current_user.tenant_id,
            UploadRequest.actor_subject_id == current_user.subject_id,
            UploadRequest.idempotency_key == key,
        )
    )


def _replay(previous: UploadRequest, fingerprint: bytes) -> UploadOutcome:
    if previous.request_fingerprint != fingerprint:
        raise IdempotencyKeyReusedError()
    return UploadOutcome(previous.response_status, previous.response_body)


def _upload_request(
    context: DocumentContext,
    *,
    key: str,
    route: str,
    fingerprint: bytes,
    outcome: UploadOutcome,
    version_id: UUID,
) -> UploadRequest:
    return UploadRequest(
        id=uuid4(),
        tenant_id=context.current_user.tenant_id,
        actor_subject_id=context.current_user.subject_id,
        idempotency_key=key,
        route=route,
        request_fingerprint=fingerprint,
        response_status=outcome.status_code,
        response_body=outcome.body,
        document_version_id=version_id,
    )


async def _remember(
    context: DocumentContext,
    *,
    key: str,
    route: str,
    fingerprint: bytes,
    outcome: UploadOutcome,
    version_id: UUID,
) -> UploadOutcome:
    """Store a no-write outcome (duplicate or same-as-latest) for idempotent replay."""
    record = _upload_request(
        context,
        key=key,
        route=route,
        fingerprint=fingerprint,
        outcome=outcome,
        version_id=version_id,
    )
    try:
        async with tenant_transaction(context.session_factory, context.current_user) as session:
            session.add(record)
    except IntegrityError as conflict:
        return await _concurrent_winner(context, key, fingerprint, conflict)
    return outcome


async def _concurrent_winner(
    context: DocumentContext, key: str, fingerprint: bytes, conflict: IntegrityError
) -> UploadOutcome:
    """A concurrent request with the same key committed first; answer as it did.

    With no stored request the conflict was something else, so it is re-raised unchanged.
    """
    async with tenant_transaction(context.session_factory, context.current_user) as session:
        previous = await _find_request(session, context.current_user, key)
    if previous is None:
        raise conflict
    return _replay(previous, fingerprint)


async def _active_subjects(session: AsyncSession, subject_ids: set[str]) -> set[str]:
    if not subject_ids:
        return set()
    rows = await session.scalars(
        select(UserProfile.external_subject).where(
            UserProfile.external_subject.in_(subject_ids), UserProfile.is_active.is_(True)
        )
    )
    return set(rows.all())


async def _own_duplicate(
    session: AsyncSession,
    current_user: CurrentUser,
    sha256: bytes,
    metadata: DocumentMetadataInput,
    grants: list[AccessGrant],
) -> DocumentVersion | None:
    """A document this caller created with the same bytes and the same access settings.

    Only the caller's own documents are compared, so nothing hidden is revealed. Access must
    match too, so a re-upload with a narrower ACL never resolves to a more widely shared copy.
    """
    candidates = (
        await session.scalars(
            select(DocumentVersion)
            .join(
                Document,
                (Document.id == DocumentVersion.document_id)
                & (Document.tenant_id == DocumentVersion.tenant_id),
            )
            .join(
                ResourceDescriptor,
                (ResourceDescriptor.id == Document.id)
                & (ResourceDescriptor.tenant_id == Document.tenant_id),
            )
            .where(
                DocumentVersion.tenant_id == current_user.tenant_id,
                DocumentVersion.sha256 == sha256,
                Document.created_by_subject_id == current_user.subject_id,
                ResourceDescriptor.classification == metadata.classification,
                ResourceDescriptor.department.is_not_distinct_from(metadata.department),
            )
            .order_by(Document.created_at, DocumentVersion.version_number)
            .limit(DUPLICATE_CANDIDATES)
        )
    ).all()
    if not candidates:
        return None
    rows = await session.execute(
        select(
            ResourceAclGrant.resource_id,
            ResourceAclGrant.principal_type,
            ResourceAclGrant.principal_id,
        ).where(
            ResourceAclGrant.tenant_id == current_user.tenant_id,
            ResourceAclGrant.resource_id.in_({candidate.document_id for candidate in candidates}),
            ResourceAclGrant.action == RESOURCE_READ,
        )
    )
    existing: dict[UUID, set[tuple[str, str]]] = defaultdict(set)
    for resource_id, principal_type, principal_id in rows:
        existing[resource_id].add((principal_type, principal_id))
    wanted = {(grant.principal_type, grant.principal_id) for grant in grants}
    return next((c for c in candidates if existing[c.document_id] == wanted), None)


def version_response(
    version: DocumentVersion, *, ingestion_status: str | None = None
) -> DocumentVersionResponse:
    return DocumentVersionResponse(
        id=version.id,
        version_number=version.version_number,
        sha256=version.sha256.hex(),
        size_bytes=version.size_bytes,
        media_type=version.media_type,
        original_filename=version.original_filename,
        status=version.status,
        ingestion_status=ingestion_status,
        created_at=version.created_at,
    )


def _upload_outcome(
    status_code: int,
    document_id: UUID,
    version: DocumentVersion,
    *,
    duplicate: bool = False,
    ingestion_job_id: UUID | None = None,
) -> UploadOutcome:
    body = UploadResponse(
        document_id=document_id,
        version=version_response(version, ingestion_status="queued" if ingestion_job_id else None),
        duplicate_of=document_id if duplicate else None,
    )
    return UploadOutcome(status_code, body.model_dump(mode="json"), ingestion_job_id)


def _new_version(
    context: DocumentContext,
    *,
    document_id: UUID,
    number: int,
    analyzed: AnalyzedFile,
    filename: str,
    key: str,
) -> DocumentVersion:
    return DocumentVersion(
        id=uuid4(),
        tenant_id=context.current_user.tenant_id,
        document_id=document_id,
        version_number=number,
        sha256=analyzed.sha256,
        size_bytes=analyzed.size_bytes,
        media_type=analyzed.media_type,
        original_filename=filename,
        storage_key=key,
        status=STORED,
        created_by_subject_id=context.current_user.subject_id,
        created_at=datetime.now(UTC),
    )


async def _audit_unprovisioned(context: DocumentContext, *, action: str, resource_id: UUID) -> None:
    await audit_unprovisioned_identity(
        session_factory=context.session_factory,
        current_user=context.current_user,
        action=action,
        resource_id=resource_id,
        correlation_id=context.correlation_id,
    )


# --- use cases ---------------------------------------------------------------------------


async def create_document(
    context: DocumentContext,
    *,
    metadata_json: str,
    upload: UploadFile,
    idempotency_key: str | None,
) -> UploadOutcome:
    user = context.current_user
    key = require_idempotency_key(idempotency_key)
    metadata = parse_metadata(metadata_json)
    grants = requested_grants(metadata)
    analyzed, filename = await _analyze(context, upload)
    fingerprint = request_fingerprint(
        DOCUMENT_CREATE, "new", metadata.model_dump(mode="json"), analyzed.sha256
    )
    document_id = uuid4()

    requested_subjects = {g.principal_id for g in grants if g.principal_type == "subject"}
    try:
        async with tenant_transaction(context.session_factory, user) as session:
            profile: IdentityResponse = await get_identity_profile(session, user)
            previous = await _find_request(session, user, key)
            active_subjects = await _active_subjects(session, requested_subjects)
            duplicate = await _own_duplicate(session, user, analyzed.sha256, metadata, grants)
    except IdentityNotProvisionedError:
        await _audit_unprovisioned(context, action=DOCUMENT_CREATE, resource_id=document_id)
        raise
    if previous is not None:
        return _replay(previous, fingerprint)

    decision = await authorize(
        session_factory=context.session_factory,
        opa_client=context.opa_client,
        current_user=user,
        subject=subject_attributes(user, profile.department),
        action=DOCUMENT_CREATE,
        resource=ResourceAttributes(
            id=document_id,
            tenant_id=user.tenant_id,
            resource_type=DOCUMENT_RESOURCE_TYPE,
            classification=metadata.classification,
            department=metadata.department,
            owner_subject_id=user.subject_id,
            grants=grants,
        ),
        purpose=UPLOAD_PURPOSE,
        correlation_id=context.correlation_id,
    )
    if not decision.allow:
        raise UploadForbiddenError()
    # Checked only after an allow, so callers who may not upload cannot probe for users.
    if requested_subjects - active_subjects:
        raise AclInvalidError()

    if duplicate is not None:
        outcome = _upload_outcome(200, duplicate.document_id, duplicate, duplicate=True)
        return await _remember(
            context,
            key=key,
            route=DOCUMENT_CREATE,
            fingerprint=fingerprint,
            outcome=outcome,
            version_id=duplicate.id,
        )

    stored_key = await run_in_threadpool(
        context.store.put, upload.file, tenant_id=user.tenant_id, sha256=analyzed.sha256
    )
    version = _new_version(
        context,
        document_id=document_id,
        number=1,
        analyzed=analyzed,
        filename=filename,
        key=stored_key,
    )
    try:
        async with tenant_transaction(context.session_factory, user) as session:
            session.add(
                ResourceDescriptor(
                    id=document_id,
                    tenant_id=user.tenant_id,
                    resource_type=DOCUMENT_RESOURCE_TYPE,
                    classification=metadata.classification,
                    department=metadata.department,
                    owner_subject_id=user.subject_id,
                    title=metadata.title,
                )
            )
            await session.flush()
            session.add_all(
                ResourceAclGrant(
                    id=uuid4(),
                    tenant_id=user.tenant_id,
                    resource_id=document_id,
                    principal_type=grant.principal_type,
                    principal_id=grant.principal_id,
                    action=grant.action,
                )
                for grant in grants
            )
            session.add(
                Document(
                    id=document_id,
                    tenant_id=user.tenant_id,
                    domain=metadata.domain,
                    project=metadata.project,
                    document_date=metadata.document_date,
                    latest_version_number=1,
                    created_by_subject_id=user.subject_id,
                    created_at=version.created_at,
                )
            )
            await session.flush()
            session.add(version)
            await session.flush()
            job_id = await queue_document_ingestion(
                session,
                current_user=user,
                document_id=document_id,
                version_id=version.id,
            )
            outcome = _upload_outcome(201, document_id, version, ingestion_job_id=job_id)
            session.add(
                _upload_request(
                    context,
                    key=key,
                    route=DOCUMENT_CREATE,
                    fingerprint=fingerprint,
                    outcome=outcome,
                    version_id=version.id,
                )
            )
    except IntegrityError as conflict:
        # The expected conflict is a concurrent request with the same Idempotency-Key.
        return await _concurrent_winner(context, key, fingerprint, conflict)
    return outcome


async def create_version(
    context: DocumentContext,
    *,
    document_id: UUID,
    upload: UploadFile,
    idempotency_key: str | None,
) -> UploadOutcome:
    user = context.current_user
    key = require_idempotency_key(idempotency_key)
    analyzed, filename = await _analyze(context, upload)
    fingerprint = request_fingerprint(
        DOCUMENT_VERSION_CREATE, str(document_id), {}, analyzed.sha256
    )

    try:
        async with tenant_transaction(context.session_factory, user) as session:
            profile: IdentityResponse = await get_identity_profile(session, user)
            previous = await _find_request(session, user, key)
            descriptor, grants = await load_resource(
                session, tenant_id=user.tenant_id, resource_id=document_id
            )
            document = await session.get(Document, document_id)
    except IdentityNotProvisionedError:
        await _audit_unprovisioned(context, action=DOCUMENT_VERSION_CREATE, resource_id=document_id)
        raise
    if previous is not None:
        return _replay(previous, fingerprint)

    found = descriptor is not None and document is not None
    decision = await authorize(
        session_factory=context.session_factory,
        opa_client=context.opa_client,
        current_user=user,
        subject=subject_attributes(user, profile.department),
        action=DOCUMENT_VERSION_CREATE,
        resource=(
            from_descriptor(descriptor, grants)
            if descriptor is not None and found
            else unavailable_resource(document_id, user.tenant_id)
        ),
        purpose=UPLOAD_PURPOSE,
        correlation_id=context.correlation_id,
        resource_found=found,
    )
    if not decision.allow:
        raise ResourceNotFoundError()

    stored_key = await run_in_threadpool(
        context.store.put, upload.file, tenant_id=user.tenant_id, sha256=analyzed.sha256
    )
    try:
        async with tenant_transaction(context.session_factory, user) as session:
            # Bumping the counter row-locks the document, serializing concurrent versions.
            number = (
                await session.execute(
                    update(Document)
                    .where(Document.id == document_id, Document.tenant_id == user.tenant_id)
                    .values(latest_version_number=Document.latest_version_number + 1)
                    .returning(Document.latest_version_number)
                )
            ).scalar_one()
            latest = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version_number == number - 1,
                )
            )
            if latest is not None and latest.sha256 == analyzed.sha256:
                raise _SameAsLatestError(_upload_outcome(200, document_id, latest), latest.id)
            version = _new_version(
                context,
                document_id=document_id,
                number=number,
                analyzed=analyzed,
                filename=filename,
                key=stored_key,
            )
            session.add(version)
            await session.flush()
            job_id = await queue_document_ingestion(
                session,
                current_user=user,
                document_id=document_id,
                version_id=version.id,
            )
            outcome = _upload_outcome(201, document_id, version, ingestion_job_id=job_id)
            session.add(
                _upload_request(
                    context,
                    key=key,
                    route=DOCUMENT_VERSION_CREATE,
                    fingerprint=fingerprint,
                    outcome=outcome,
                    version_id=version.id,
                )
            )
    except _SameAsLatestError as same:
        return await _remember(
            context,
            key=key,
            route=DOCUMENT_VERSION_CREATE,
            fingerprint=fingerprint,
            outcome=same.outcome,
            version_id=same.version_id,
        )
    except IntegrityError as conflict:
        return await _concurrent_winner(context, key, fingerprint, conflict)
    return outcome


async def read_document(context: DocumentContext, *, document_id: UUID) -> DocumentResponse:
    user = context.current_user
    try:
        async with tenant_transaction(context.session_factory, user) as session:
            profile: IdentityResponse = await get_identity_profile(session, user)
            descriptor, grants = await load_resource(
                session, tenant_id=user.tenant_id, resource_id=document_id
            )
            document = await session.get(Document, document_id)
    except IdentityNotProvisionedError:
        await _audit_unprovisioned(context, action=RESOURCE_READ, resource_id=document_id)
        raise

    found = descriptor is not None and document is not None
    decision = await authorize(
        session_factory=context.session_factory,
        opa_client=context.opa_client,
        current_user=user,
        subject=subject_attributes(user, profile.department),
        action=RESOURCE_READ,
        resource=(
            from_descriptor(descriptor, grants)
            if descriptor is not None and found
            else unavailable_resource(document_id, user.tenant_id)
        ),
        purpose=READ_PURPOSE,
        correlation_id=context.correlation_id,
        resource_found=found,
    )
    if not decision.allow or descriptor is None or document is None:
        raise ResourceNotFoundError()

    # Version metadata is loaded only after the allow decision is audited.
    async with tenant_transaction(context.session_factory, user) as session:
        versions = (
            await session.scalars(
                select(DocumentVersion)
                .where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.tenant_id == user.tenant_id,
                )
                .order_by(DocumentVersion.version_number)
            )
        ).all()
        jobs = (
            await session.scalars(
                select(DocumentIngestionJob).where(
                    DocumentIngestionJob.document_id == document_id,
                    DocumentIngestionJob.tenant_id == user.tenant_id,
                )
            )
        ).all()
    status_by_version = {job.document_version_id: job.state for job in jobs}
    return DocumentResponse(
        id=document.id,
        title=descriptor.title,
        classification=descriptor.classification,
        department=descriptor.department,
        domain=document.domain,
        project=document.project,
        document_date=document.document_date,
        latest_version_number=document.latest_version_number,
        created_at=document.created_at,
        grants=[
            GrantResponse(
                principal_type=grant.principal_type,
                principal_id=grant.principal_id,
                action=grant.action,
            )
            for grant in grants
        ],
        versions=[
            version_response(version, ingestion_status=status_by_version.get(version.id))
            for version in versions
        ],
    )


async def _authorize_document_read(context: DocumentContext, *, document_id: UUID) -> Document:
    """Run the Guard decision before loading version-derived data or original bytes."""
    user = context.current_user
    try:
        async with tenant_transaction(context.session_factory, user) as session:
            profile: IdentityResponse = await get_identity_profile(session, user)
            descriptor, grants = await load_resource(
                session, tenant_id=user.tenant_id, resource_id=document_id
            )
            document = await session.get(Document, document_id)
    except IdentityNotProvisionedError:
        await _audit_unprovisioned(context, action=RESOURCE_READ, resource_id=document_id)
        raise

    found = descriptor is not None and document is not None
    decision = await authorize(
        session_factory=context.session_factory,
        opa_client=context.opa_client,
        current_user=user,
        subject=subject_attributes(user, profile.department),
        action=RESOURCE_READ,
        resource=(
            from_descriptor(descriptor, grants)
            if descriptor is not None and found
            else unavailable_resource(document_id, user.tenant_id)
        ),
        purpose=READ_PURPOSE,
        correlation_id=context.correlation_id,
        resource_found=found,
    )
    if not decision.allow or document is None:
        raise ResourceNotFoundError()
    return document


async def read_document_preview(
    context: DocumentContext,
    *,
    document_id: UUID,
    version_id: UUID,
    cursor: int,
    limit: int,
) -> DocumentPreviewResponse | DocumentIngestionStatusResponse:
    await _authorize_document_read(context, document_id=document_id)
    user = context.current_user
    async with tenant_transaction(context.session_factory, user) as session:
        version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.tenant_id == user.tenant_id,
            )
        )
        if version is None:
            raise ResourceNotFoundError()
        job = await session.scalar(
            select(DocumentIngestionJob).where(
                DocumentIngestionJob.document_version_id == version_id,
                DocumentIngestionJob.tenant_id == user.tenant_id,
            )
        )
        if job is None or job.state in {"queued", "processing"}:
            return DocumentIngestionStatusResponse(
                document_id=document_id,
                version_id=version_id,
                status="processing" if job is not None and job.state == "processing" else "queued",
                retry_after_seconds=5,
            )
        if job.state == QUARANTINED:
            raise DocumentPreviewUnavailableError()
        extraction = await session.scalar(
            select(DocumentExtraction).where(
                DocumentExtraction.document_version_id == version_id,
                DocumentExtraction.tenant_id == user.tenant_id,
            )
        )
        if job.state != READY or extraction is None:
            raise DocumentPreviewUnavailableError()
        blocks = (
            await session.scalars(
                select(DocumentContentBlock)
                .where(
                    DocumentContentBlock.extraction_id == extraction.id,
                    DocumentContentBlock.tenant_id == user.tenant_id,
                    DocumentContentBlock.ordinal > cursor,
                )
                .order_by(DocumentContentBlock.ordinal)
                .limit(limit + 1)
            )
        ).all()
    page = blocks[:limit]
    return DocumentPreviewResponse(
        document_id=document_id,
        version_id=version_id,
        parser_name=extraction.parser_name,
        parser_version=extraction.parser_version,
        normalization_version=extraction.normalization_version,
        blocks=[
            DocumentPreviewBlockResponse(
                ordinal=block.ordinal,
                block_type=block.block_type,
                text=block.text,
                locator=block.locator,
            )
            for block in page
        ],
        next_cursor=page[-1].ordinal if len(blocks) > limit and page else None,
    )


async def download_document_version(
    context: DocumentContext, *, document_id: UUID, version_id: UUID
) -> DownloadOutcome:
    await _authorize_document_read(context, document_id=document_id)
    user = context.current_user
    async with tenant_transaction(context.session_factory, user) as session:
        version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.tenant_id == user.tenant_id,
            )
        )
    if version is None:
        raise ResourceNotFoundError()
    content = await run_in_threadpool(context.store.read, version.storage_key)
    return DownloadOutcome(
        content=content, filename=version.original_filename, media_type=version.media_type
    )
