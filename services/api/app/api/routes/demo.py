from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.contracts import CurrentUser
from app.identity.dependencies import get_current_user, get_session_factory, get_tenant_session
from app.policy.client import OpaClient
from app.policy.contracts import DemoResourceResponse
from app.policy.dependencies import get_opa_client
from app.policy.service import read_demo_resource

router = APIRouter()


@router.get("/resources/{resource_id}", response_model=DemoResourceResponse)
async def get_demo_resource(
    resource_id: UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    opa_client: Annotated[OpaClient, Depends(get_opa_client)],
) -> DemoResourceResponse:
    return await read_demo_resource(
        session,
        session_factory,
        current_user,
        opa_client,
        resource_id,
        request.state.correlation_id,
    )
