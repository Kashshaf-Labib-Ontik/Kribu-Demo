"""Transaction-scoped tenant context for PostgreSQL row-level security."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.contracts import CurrentUser

_SET_CONTEXT = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true), "
    "set_config('app.user_id', :user_id, true)"
)


async def set_tenant_context(session: AsyncSession, current_user: CurrentUser) -> None:
    """Bind tenant and subject to the current transaction only (``is_local = true``)."""
    await session.execute(
        _SET_CONTEXT,
        {"tenant_id": str(current_user.tenant_id), "user_id": current_user.subject_id},
    )


@asynccontextmanager
async def tenant_transaction(
    session_factory: async_sessionmaker[AsyncSession], current_user: CurrentUser
) -> AsyncIterator[AsyncSession]:
    """One short transaction with the caller's tenant context; commits on clean exit."""
    async with session_factory() as session, session.begin():
        await set_tenant_context(session, current_user)
        yield session
