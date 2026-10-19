from __future__ import annotations


class ModelProviderError(Exception):
    """Safe model-provider error that can be mapped at an application boundary."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        provider_status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable
        self.provider_status_code = provider_status_code


class ModelProviderConfigurationError(ModelProviderError):
    def __init__(self, message: str = "The model provider is not configured.") -> None:
        super().__init__(code="model_provider_not_configured", message=message, retryable=False)


class ModelDataPolicyError(ModelProviderError):
    def __init__(self) -> None:
        super().__init__(
            code="model_data_policy_denied",
            message="Only synthetic demo data may be sent to this model provider.",
            retryable=False,
        )


class ModelProviderUnavailableError(ModelProviderError):
    def __init__(
        self,
        *,
        retryable: bool = True,
        provider_status_code: int | None = None,
    ) -> None:
        super().__init__(
            code="model_provider_unavailable",
            message="The model provider is temporarily unavailable.",
            retryable=retryable,
            provider_status_code=provider_status_code,
        )


class ModelProviderResponseError(ModelProviderError):
    def __init__(self) -> None:
        super().__init__(
            code="model_provider_invalid_response",
            message="The model provider returned an invalid response.",
            retryable=False,
        )
