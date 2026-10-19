from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.policy.client import OpaClient
from app.policy.dependencies import get_opa_client
from app.schemas.health import HealthResponse

router = APIRouter()


def get_database_engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.database_engine)


@router.get("/live", response_model=HealthResponse)
async def liveness(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name, version="0.1.0")


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Required dependency unavailable"}
    },
)
async def readiness(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    engine: Annotated[AsyncEngine, Depends(get_database_engine)],
    opa_client: Annotated[OpaClient, Depends(get_opa_client)],
) -> HealthResponse | JSONResponse:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (OSError, SQLAlchemyError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "type": "about:blank",
                "title": "Service unavailable",
                "status": status.HTTP_503_SERVICE_UNAVAILABLE,
                "detail": "The database readiness check failed.",
                "code": "database_unavailable",
                "correlation_id": request.state.correlation_id,
            },
        )

    if not await opa_client.ready():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "type": "about:blank",
                "title": "Service unavailable",
                "status": status.HTTP_503_SERVICE_UNAVAILABLE,
                "detail": "The authorization readiness check failed.",
                "code": "authorization_unavailable",
                "correlation_id": request.state.correlation_id,
            },
        )

    return HealthResponse(status="ok", service=settings.service_name, version="0.1.0")
