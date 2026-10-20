from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.contracts import CurrentUser
from app.identity.errors import AuthenticationRequiredError
from app.identity.tenancy import tenant_transaction
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
    async with tenant_transaction(session_factory, current_user) as session:
        yield session
