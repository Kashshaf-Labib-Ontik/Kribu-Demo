"""Per-request correlation and request IDs, and the last-resort 500 problem response.

A pure ASGI middleware (not ``BaseHTTPMiddleware``): it sits inside Starlette's
``ServerErrorMiddleware``, so unhandled errors still get a problem body, correlation
headers, and (with CORS registered after it, i.e. outside it) CORS headers.
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import problem_response

logger = logging.getLogger(__name__)

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_correlation_id() -> str | None:
    return correlation_id_var.get()


def current_request_id() -> str | None:
    return request_id_var.get()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-correlation-id")
        correlation_id = (
            incoming if incoming and CORRELATION_ID_PATTERN.fullmatch(incoming) else str(uuid4())
        )
        request_id = str(uuid4())
        state = scope.setdefault("state", {})
        state["correlation_id"] = correlation_id
        state["request_id"] = request_id
        correlation_token = correlation_id_var.set(correlation_id)
        request_token = request_id_var.set(request_id)
        response_started = False

        async def send_with_ids(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["X-Correlation-ID"] = correlation_id
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_ids)
        except Exception:
            logger.exception("unhandled error while serving request")
            if response_started:
                raise
            response = problem_response(
                status_code=500,
                code="internal_error",
                detail="An unexpected error occurred.",
                correlation_id=correlation_id,
            )
            await response(scope, receive, send_with_ids)
        finally:
            correlation_id_var.reset(correlation_token)
            request_id_var.reset(request_token)
