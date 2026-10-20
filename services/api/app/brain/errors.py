from app.core.errors import AppError


class RetrievalUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="retrieval_unavailable",
            message="Retrieval is temporarily unavailable.",
            status_code=503,
        )


class RetrievalAuditUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="retrieval_audit_unavailable",
            message="Retrieval could not be audited.",
            status_code=503,
        )
