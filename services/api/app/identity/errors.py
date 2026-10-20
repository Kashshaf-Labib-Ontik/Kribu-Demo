from __future__ import annotations

from app.core.errors import AppError


class IdentityError(AppError):
    pass


class AuthenticationRequiredError(IdentityError):
    def __init__(self) -> None:
        super().__init__(
            code="authentication_required",
            message="A valid access token is required.",
            status_code=401,
        )


class InvalidAccessTokenError(IdentityError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_access_token",
            message="The access token is invalid or expired.",
            status_code=401,
        )


class IdentityProviderUnavailableError(IdentityError):
    def __init__(self) -> None:
        super().__init__(
            code="identity_provider_unavailable",
            message="The identity provider is temporarily unavailable.",
            status_code=503,
        )


class IdentityNotProvisionedError(IdentityError):
    def __init__(self) -> None:
        super().__init__(
            code="identity_not_provisioned",
            message="This identity is not provisioned for KRIBU.",
            status_code=403,
        )
