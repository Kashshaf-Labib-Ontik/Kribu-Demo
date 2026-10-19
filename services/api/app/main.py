from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import create_session_factory
from app.identity.errors import IdentityError
from app.identity.tokens import OidcTokenVerifier


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.database_engine = engine
    app.state.database_session_factory = create_session_factory(engine)
    app.state.token_verifier = OidcTokenVerifier(settings)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="KRIBU API",
        version="0.1.0",
        docs_url="/docs" if settings.environment == "development" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.cors_origins],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
    )

    @application.exception_handler(IdentityError)
    async def identity_error(request: Request, exc: IdentityError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content={
                "type": "about:blank",
                "title": "Unauthorized" if exc.status_code == 401 else "Forbidden",
                "status": exc.status_code,
                "detail": exc.safe_message,
                "code": exc.code,
                "correlation_id": request.state.correlation_id,
            },
        )

    @application.middleware("http")
    async def correlation_id(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        request.state.correlation_id = request_id[:128]
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    application.include_router(api_router, prefix="/v1")
    return application


app = create_app()
