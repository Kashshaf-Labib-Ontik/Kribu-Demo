from app.core.errors import AppError


class PolicyError(AppError):
    pass


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
