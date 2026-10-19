from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.contracts import CurrentUser
from app.identity.errors import AuthenticationRequiredError
from app.identity.tokens import OidcTokenVerifier

bearer_scheme = HTTPBearer(auto_error=False)


def get_token_verifier(request: Request) -> OidcTokenVerifier:
    return cast(OidcTokenVerifier, request.app.state.token_verifier)


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.database_session_factory)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    verifier: Annotated[OidcTokenVerifier, Depends(get_token_verifier)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationRequiredError()
    return await verifier.verify(credentials.credentials)


async def get_tenant_session(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session_factory: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_session_factory),
    ],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session, session.begin():
        await set_tenant_context(session, current_user)
        yield session


async def set_tenant_context(session: AsyncSession, current_user: CurrentUser) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(current_user.tenant_id)},
    )
    await session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": current_user.subject_id},
    )
