class PolicyError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


class ResourceNotFoundError(PolicyError):
    def __init__(self) -> None:
        super().__init__(
            code="resource_not_found",
            message="The resource is unavailable.",
            status_code=404,
        )


class PolicyUnavailableError(PolicyError):
    def __init__(self) -> None:
        super().__init__(
            code="authorization_unavailable",
            message="Authorization is temporarily unavailable.",
            status_code=503,
        )


class AuditUnavailableError(PolicyError):
    def __init__(self) -> None:
        super().__init__(
            code="audit_unavailable",
            message="Authorization is temporarily unavailable.",
            status_code=503,
        )
