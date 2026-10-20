from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.documents.upload_guard import MULTIPART_OVERHEAD_BYTES, UploadGuardMiddleware
from app.identity.errors import IdentityProviderUnavailableError, InvalidAccessTokenError

MAX_FILE = 1000
MAX_BODY = MAX_FILE + MULTIPART_OVERHEAD_BYTES
UPLOAD = "/v1/documents/uploads"


def build_app(verify: AsyncMock) -> tuple[Callable[..., Awaitable[None]], dict[str, int]]:
    seen = {"calls": 0, "bytes": 0}

    async def upload(request: Request) -> JSONResponse:
        seen["calls"] += 1
        body = await request.body()  # raises once the guard cuts the stream
        seen["bytes"] = len(body)
        return JSONResponse({"received": len(body)})

    inner = Starlette(
        routes=[
            Route(UPLOAD, upload, methods=["POST"]),
            Route("/v1/documents/{document_id}/versions", upload, methods=["POST"]),
            Route("/v1/health/live", upload, methods=["POST", "GET"]),
        ]
    )
    inner.state.token_verifier = AsyncMock(verify=verify)
    inner.state.token_verifier.verify = verify
    guard = UploadGuardMiddleware(inner, max_file_bytes=MAX_FILE)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        scope["app"] = inner
        scope.setdefault("state", {})["correlation_id"] = "guard-test"
        await guard(scope, receive, send)

    return app, seen


async def call(
    app: Callable[..., Awaitable[None]],
    *,
    path: str = UPLOAD,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    chunks: list[bytes] | None = None,
) -> tuple[int, dict[str, str], dict[str, Any]]:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "query_string": b"",
    }
    pending = list(chunks or [b""])
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        if pending:
            body = pending.pop(0)
            return {"type": "http.request", "body": body, "more_body": bool(pending)}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    response_headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    is_json = "json" in response_headers.get("content-type", "")
    return start["status"], response_headers, json.loads(body) if is_json else {}


BEARER = {"Authorization": "Bearer good-token"}


@pytest.mark.asyncio
async def test_missing_token_is_rejected_before_reading_the_body() -> None:
    app, seen = build_app(AsyncMock())

    status, headers, body = await call(app, chunks=[b"x" * 10])

    assert status == 401
    assert body["code"] == "authentication_required"
    assert headers["www-authenticate"] == "Bearer"
    assert headers["content-type"] == "application/problem+json"
    assert body["correlation_id"] == "guard-test"
    assert seen["calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (InvalidAccessTokenError(), 401, "invalid_access_token"),
        (IdentityProviderUnavailableError(), 503, "identity_provider_unavailable"),
    ],
)
async def test_token_failures_are_rejected_before_reading_the_body(
    error: Exception, status: int, code: str
) -> None:
    app, seen = build_app(AsyncMock(side_effect=error))

    actual_status, _, body = await call(app, headers=BEARER, chunks=[b"x"])

    assert (actual_status, body["code"]) == (status, code)
    assert seen["calls"] == 0


@pytest.mark.asyncio
async def test_declared_oversize_is_rejected_before_reading_the_body() -> None:
    app, seen = build_app(AsyncMock())

    status, headers, body = await call(
        app, headers={**BEARER, "Content-Length": str(MAX_BODY + 1)}, chunks=[b"x"]
    )

    assert status == 413
    assert body["code"] == "upload_too_large"
    assert headers["connection"] == "close"
    assert seen["calls"] == 0


@pytest.mark.asyncio
async def test_streamed_oversize_without_length_is_cut_off_with_413() -> None:
    app, seen = build_app(AsyncMock())
    chunks = [b"x" * 40_000, b"x" * 40_000, b"x" * 40_000]  # no Content-Length, > MAX_BODY

    status, _, body = await call(app, headers=BEARER, chunks=chunks)

    assert status == 413
    assert body["code"] == "upload_too_large"
    assert seen["bytes"] == 0  # the endpoint never received a complete body


@pytest.mark.asyncio
async def test_body_exactly_at_the_limit_passes() -> None:
    app, seen = build_app(AsyncMock())

    status, _, body = await call(app, headers=BEARER, chunks=[b"x" * MAX_BODY])

    assert status == 200
    assert body == {"received": MAX_BODY}


@pytest.mark.asyncio
async def test_version_uploads_are_guarded_too() -> None:
    app, seen = build_app(AsyncMock())

    status, _, _ = await call(app, path="/v1/documents/abc/versions", chunks=[b"x"])

    assert status == 401
    assert seen["calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "method"), [("/v1/health/live", "POST"), (UPLOAD, "GET")])
async def test_other_routes_and_methods_are_not_guarded(path: str, method: str) -> None:
    app, seen = build_app(AsyncMock())

    status, _, _ = await call(app, path=path, method=method, chunks=[b"x" * (MAX_BODY + 10)])

    assert status in {200, 405}
    assert seen["calls"] == (1 if status == 200 else 0)
