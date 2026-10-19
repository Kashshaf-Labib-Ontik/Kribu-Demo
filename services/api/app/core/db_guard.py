"""Refuse to serve requests through a database role that bypasses row-level security."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 5.0

# A role is a member of itself, so pg_has_role also covers direct table ownership.
ROLE_CHECK = text(
    "SELECT r.rolsuper, r.rolbypassrls, "
    "EXISTS (SELECT 1 FROM pg_tables t WHERE t.schemaname = 'public' "
    "AND pg_has_role(current_user, t.tableowner, 'MEMBER')) AS owns_tables "
    "FROM pg_roles r WHERE r.rolname = current_user"
)


class UnsafeDatabaseRoleError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "refusing to start: the database role bypasses RLS "
            "(superuser, BYPASSRLS, or table owner); use the restricted kribu_app role"
        )


async def assert_restricted_role(
    engine: AsyncEngine, timeout_seconds: float = CHECK_TIMEOUT_SECONDS
) -> None:
    """Raise if the runtime role could bypass RLS.

    An unreachable database is logged and tolerated so readiness reports 503 instead of the
    process crash-looping; the check runs again on the next start.
    """
    try:
        async with asyncio.timeout(timeout_seconds), engine.connect() as connection:
            row = (await connection.execute(ROLE_CHECK)).one()
    except (OSError, SQLAlchemyError, TimeoutError):
        logger.warning("database role check skipped: database unreachable", exc_info=True)
        return
    if row.rolsuper or row.rolbypassrls or row.owns_tables:
        raise UnsafeDatabaseRoleError()
