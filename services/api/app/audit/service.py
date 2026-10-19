from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuthorizationAuditEvent
from app.identity.contracts import CurrentUser
from app.identity.dependencies import set_tenant_context
from app.policy.contracts import AuthorizationInput
from app.policy.errors import AuditUnavailableError


async def record_authorization_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    current_user: CurrentUser,
    resource_id: UUID,
    correlation_id: str,
    allowed: bool,
    reason_code: str,
    policy_version: str | None,
    policy_input: AuthorizationInput | None,
) -> None:
    metadata = policy_input.model_dump(mode="json") if policy_input is not None else {}
    try:
        async with session_factory() as session, session.begin():
            await set_tenant_context(session, current_user)
            session.add(
                AuthorizationAuditEvent(
                    id=uuid4(),
                    tenant_id=current_user.tenant_id,
                    actor_subject_id=current_user.subject_id,
                    action="resource.read",
                    resource_id=resource_id,
                    allowed=allowed,
                    reason_code=reason_code,
                    policy_version=policy_version,
                    correlation_id=correlation_id,
                    input_metadata=metadata,
                )
            )
    except (OSError, SQLAlchemyError) as exc:
        raise AuditUnavailableError() from exc
