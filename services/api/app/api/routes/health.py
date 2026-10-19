from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.version import API_VERSION
from app.policy.client import OpaClient
from app.policy.dependencies import get_opa_client
from app.schemas.health import HealthResponse

router = APIRouter()


class DatabaseNotReadyError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="database_unavailable",
            message="The database readiness check failed.",
            status_code=503,
        )


class AuthorizationNotReadyError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="authorization_unavailable",
            message="The authorization readiness check failed.",
            status_code=503,
        )


def get_database_engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.database_engine)


@router.get("/live", response_model=HealthResponse)
async def liveness(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name, version=API_VERSION)


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Required dependency unavailable"}
    },
)
async def readiness(
    settings: Annotated[Settings, Depends(get_settings)],
    engine: Annotated[AsyncEngine, Depends(get_database_engine)],
    opa_client: Annotated[OpaClient, Depends(get_opa_client)],
) -> HealthResponse:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (OSError, SQLAlchemyError) as exc:
        raise DatabaseNotReadyError() from exc

    if not await opa_client.ready():
        raise AuthorizationNotReadyError()

    return HealthResponse(status="ok", service=settings.service_name, version=API_VERSION)
