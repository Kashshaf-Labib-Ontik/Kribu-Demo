"""Safe application errors and the RFC 9457 problem-details response."""

from __future__ import annotations

from http import HTTPStatus

from fastapi.responses import JSONResponse

PROBLEM_MEDIA_TYPE = "application/problem+json"


class AppError(Exception):
    """An error whose code and message are safe to return to API callers."""

    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def problem_response(
    *,
    status_code: int,
    code: str,
    detail: str,
    correlation_id: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        media_type=PROBLEM_MEDIA_TYPE,
        content={
            "type": "about:blank",
            "title": HTTPStatus(status_code).phrase,
            "status": status_code,
            "detail": detail,
            "code": code,
            "correlation_id": correlation_id,
        },
    )
