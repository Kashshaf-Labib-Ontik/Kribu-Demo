from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from app.core.db_guard import UnsafeDatabaseRoleError, assert_restricted_role


def engine_returning(
    row: SimpleNamespace | None = None, error: Exception | None = None
) -> MagicMock:
    connection = AsyncMock()
    result = MagicMock()
    result.one.return_value = row
    connection.execute.return_value = result
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=connection, side_effect=error)
    context.__aexit__ = AsyncMock(return_value=None)
    engine = MagicMock()
    engine.connect.return_value = context
    return engine


def role(*, superuser: bool = False, bypass: bool = False, owner: bool = False) -> SimpleNamespace:
    return SimpleNamespace(rolsuper=superuser, rolbypassrls=bypass, owns_tables=owner)


@pytest.mark.asyncio
async def test_restricted_role_is_accepted() -> None:
    await assert_restricted_role(engine_returning(role()))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe",
    [role(superuser=True), role(bypass=True), role(owner=True)],
    ids=["superuser", "bypassrls", "table-owner"],
)
async def test_rls_bypassing_role_refuses_to_start(unsafe: SimpleNamespace) -> None:
    with pytest.raises(UnsafeDatabaseRoleError, match="bypasses RLS"):
        await assert_restricted_role(engine_returning(unsafe))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [ConnectionRefusedError(), OperationalError("SELECT 1", {}, Exception("down")), TimeoutError()],
)
async def test_unreachable_database_is_tolerated(error: Exception) -> None:
    await assert_restricted_role(engine_returning(error=error))
