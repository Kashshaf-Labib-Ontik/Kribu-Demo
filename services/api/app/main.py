from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import create_session_factory
from app.core.db_guard import assert_restricted_role
from app.core.errors import AppError, problem_response
from app.core.logging import configure_logging
from app.core.request_context import RequestContextMiddleware
from app.core.version import API_VERSION
from app.identity.tokens import OidcTokenVerifier
from app.policy.client import OpaClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        await assert_restricted_role(engine)
    except BaseException:
        await engine.dispose()
        raise
    app.state.database_engine = engine
    app.state.database_session_factory = create_session_factory(engine)
    app.state.token_verifier = OidcTokenVerifier(settings)
    app.state.opa_client = OpaClient(
        str(settings.opa_url),
        settings.opa_timeout_seconds,
        settings.opa_policy_version,
    )
    yield
    await app.state.opa_client.close()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    application = FastAPI(
        title="KRIBU API",
        version=API_VERSION,
        docs_url="/docs" if settings.environment == "development" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    # Added first, so CORS (added next) wraps it and 500 problems keep CORS headers.
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        # pydantic renders AnyHttpUrl with a trailing "/"; browser Origin headers have none.
        allow_origins=[str(origin).rstrip("/") for origin in settings.cors_origins],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID", "X-Request-ID"],
    )

    @application.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem_response(
            status_code=exc.status_code,
            code=exc.code,
            detail=exc.safe_message,
            correlation_id=request.state.correlation_id,
            headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo the rejected input back to the caller.
        return problem_response(
            status_code=422,
            code="request_invalid",
            detail="The request is invalid.",
            correlation_id=request.state.correlation_id,
        )

    application.include_router(api_router, prefix="/v1")
    return application


app = create_app()
