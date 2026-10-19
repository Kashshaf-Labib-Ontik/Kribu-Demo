from __future__ import annotations


class IdentityError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


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


class IdentityNotProvisionedError(IdentityError):
    def __init__(self) -> None:
        super().__init__(
            code="identity_not_provisioned",
            message="This identity is not provisioned for KRIBU.",
            status_code=403,
        )
