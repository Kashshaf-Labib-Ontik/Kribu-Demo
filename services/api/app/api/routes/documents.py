from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.config import Settings, get_settings
from app.documents.contracts import DocumentResponse, UploadResponse
from app.documents.dependencies import get_object_store
from app.documents.errors import SingleFileRequiredError
from app.documents.service import DocumentContext, create_document, create_version, read_document
from app.documents.storage import ObjectStore
from app.identity.contracts import CurrentUser
from app.identity.dependencies import get_current_user, get_session_factory
from app.policy.client import OpaClient
from app.policy.dependencies import get_opa_client

router = APIRouter()

UPLOAD_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {"model": UploadResponse, "description": "Idempotent replay or existing duplicate"},
    201: {"model": UploadResponse, "description": "Stored a new document or version"},
}


def document_context(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    opa_client: Annotated[OpaClient, Depends(get_opa_client)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentContext:
    return DocumentContext(
        session_factory=session_factory,
        opa_client=opa_client,
        store=store,
        current_user=current_user,
        correlation_id=request.state.correlation_id,
        max_file_bytes=settings.upload_max_bytes,
    )


async def ensure_single_file(request: Request) -> None:
    form = await request.form()  # already parsed and cached by FastAPI
    files = [value for _, value in form.multi_items() if isinstance(value, StarletteUploadFile)]
    if len(files) != 1:
        raise SingleFileRequiredError()


@router.post("/uploads", status_code=201, responses=UPLOAD_RESPONSES)
async def upload_document(
    request: Request,
    context: Annotated[DocumentContext, Depends(document_context)],
    file: Annotated[UploadFile, File()],
    metadata: Annotated[str, Form(max_length=16_384)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    await ensure_single_file(request)
    outcome = await create_document(
        context, metadata_json=metadata, upload=file, idempotency_key=idempotency_key
    )
    return JSONResponse(status_code=outcome.status_code, content=outcome.body)


@router.post("/{document_id}/versions", status_code=201, responses=UPLOAD_RESPONSES)
async def upload_document_version(
    document_id: UUID,
    request: Request,
    context: Annotated[DocumentContext, Depends(document_context)],
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    await ensure_single_file(request)
    outcome = await create_version(
        context, document_id=document_id, upload=file, idempotency_key=idempotency_key
    )
    return JSONResponse(status_code=outcome.status_code, content=outcome.body)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    context: Annotated[DocumentContext, Depends(document_context)],
) -> DocumentResponse:
    return await read_document(context, document_id=document_id)
