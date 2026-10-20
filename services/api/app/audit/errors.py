from app.core.errors import AppError


class AuditUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="audit_unavailable",
            message="Authorization is temporarily unavailable.",
            status_code=503,
        )
