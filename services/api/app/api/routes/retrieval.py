from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.brain.contracts import RetrievalRequest, RetrievalResponse
from app.brain.dependencies import get_embedding_provider
from app.brain.embeddings import EmbeddingProvider
from app.brain.service import RetrievalContext, search
from app.core.config import Settings, get_settings
from app.identity.contracts import CurrentUser
from app.identity.dependencies import get_current_user, get_session_factory
from app.policy.client import OpaClient
from app.policy.dependencies import get_opa_client

router = APIRouter()


def retrieval_context(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    opa_client: Annotated[OpaClient, Depends(get_opa_client)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RetrievalContext:
    return RetrievalContext(
        session_factory=session_factory,
        opa_client=opa_client,
        embedding_provider=embedding_provider,
        current_user=current_user,
        correlation_id=request.state.correlation_id,
        settings=settings,
    )


@router.post("/search", response_model=RetrievalResponse)
async def search_documents(
    body: RetrievalRequest,
    context: Annotated[RetrievalContext, Depends(retrieval_context)],
) -> RetrievalResponse:
    return await search(context, body)
