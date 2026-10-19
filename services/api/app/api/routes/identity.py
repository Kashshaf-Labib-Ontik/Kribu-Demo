from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.contracts import CurrentUser, IdentityResponse
from app.identity.dependencies import get_current_user, get_tenant_session
from app.identity.service import get_identity_profile

router = APIRouter()


@router.get("/me", response_model=IdentityResponse)
async def read_current_identity(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> IdentityResponse:
    return await get_identity_profile(session, current_user)
