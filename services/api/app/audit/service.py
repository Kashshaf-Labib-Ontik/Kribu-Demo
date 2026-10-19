from __future__ import annotations

import logging
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.errors import AuditUnavailableError
from app.audit.models import AuthorizationAuditEvent
from app.core.request_context import current_request_id
from app.identity.contracts import CurrentUser
from app.identity.tenancy import tenant_transaction
from app.policy.contracts import AuthorizationInput

logger = logging.getLogger(__name__)


async def record_authorization_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    current_user: CurrentUser,
    action: str,
    resource_id: UUID,
    correlation_id: str,
    allowed: bool,
    reason_code: str,
    policy_version: str | None,
    policy_input: AuthorizationInput | None,
) -> None:
    metadata = policy_input.model_dump(mode="json") if policy_input is not None else {}
    try:
        async with tenant_transaction(session_factory, current_user) as session:
            session.add(
                AuthorizationAuditEvent(
                    id=uuid4(),
                    tenant_id=current_user.tenant_id,
                    actor_subject_id=current_user.subject_id,
                    action=action,
                    resource_id=resource_id,
                    allowed=allowed,
                    reason_code=reason_code,
                    policy_version=policy_version,
                    correlation_id=correlation_id,
                    request_id=current_request_id(),
                    input_metadata=metadata,
                )
            )
    except (OSError, SQLAlchemyError) as exc:
        logger.warning("authorization audit write failed", exc_info=True)
        raise AuditUnavailableError() from exc
