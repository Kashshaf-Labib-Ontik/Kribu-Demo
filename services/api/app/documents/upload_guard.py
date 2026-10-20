"""Authenticate and size-limit upload requests before their bodies are read.

FastAPI parses the whole multipart body (spooling file parts to disk without a size cap)
before resolving dependencies such as authentication. This pure ASGI guard runs first for
the upload routes: no valid bearer token means 401 with zero body bytes read; a declared or
streamed body over the limit means 413 and the body is not consumed any further. Route-level
authentication still runs afterwards as defense in depth.
"""

from __future__ import annotations

import re

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import AppError, problem_response
from app.documents.errors import UploadTooLargeError
from app.identity.errors import AuthenticationRequiredError
from app.identity.tokens import OidcTokenVerifier

UPLOAD_PATH = re.compile(r"/v1/documents/(?:uploads|[^/]+/versions)")
MULTIPART_OVERHEAD_BYTES = 64 * 1024


class _BodyLimitExceeded(Exception):
    pass


class UploadGuardMiddleware:
    def __init__(self, app: ASGIApp, *, max_file_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_file_bytes + MULTIPART_OVERHEAD_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not UPLOAD_PATH.fullmatch(scope["path"])
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        try:
            await self._authenticate(scope, headers)
        except AppError as error:
            await self._reject(error, scope, receive, send)
            return
        if self._declared_length(headers) > self.max_body_bytes:
            await self._reject(UploadTooLargeError(), scope, receive, send)
            return
        await self._stream_with_limit(scope, receive, send)

    async def _stream_with_limit(self, scope: Scope, receive: Receive, send: Send) -> None:
        received = 0
        exceeded = False
        replaced = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    exceeded = True
                    raise _BodyLimitExceeded()
            return message

        async def send_413_once() -> None:
            nonlocal replaced
            if not replaced:
                replaced = True
                await self._reject(UploadTooLargeError(), scope, receive, send)

        async def guarded_send(message: Message) -> None:
            # FastAPI reports body-parsing failures as its own 400; swap in the 413.
            if exceeded:
                await send_413_once()
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded:
            await send_413_once()

    @staticmethod
    async def _authenticate(scope: Scope, headers: Headers) -> None:
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationRequiredError()
        verifier: OidcTokenVerifier = scope["app"].state.token_verifier
        await verifier.verify(token.strip())

    @staticmethod
    def _declared_length(headers: Headers) -> int:
        try:
            return int(headers.get("content-length", "0"))
        except ValueError:
            return 0

    @staticmethod
    async def _reject(error: AppError, scope: Scope, receive: Receive, send: Send) -> None:
        response_headers = {"Connection": "close"}
        if error.status_code == 401:
            response_headers["WWW-Authenticate"] = "Bearer"
        response = problem_response(
            status_code=error.status_code,
            code=error.code,
            detail=error.safe_message,
            correlation_id=scope.get("state", {}).get("correlation_id", ""),
            headers=response_headers,
        )
        await response(scope, receive, send)
