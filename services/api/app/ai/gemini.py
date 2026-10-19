from __future__ import annotations

from collections.abc import AsyncIterator
from time import monotonic
from typing import cast

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.ai.contracts import (
    ModelCallMetadata,
    ModelStreamEvent,
    ModelUsage,
    StructuredModelResult,
    StructuredOutputT,
    SyntheticPrompt,
    ToolCall,
    ToolDefinition,
    ToolSelectionResult,
)
from app.ai.errors import (
    ModelDataPolicyError,
    ModelProviderConfigurationError,
    ModelProviderResponseError,
    ModelProviderUnavailableError,
)
from app.core.config import Settings

_RETRYABLE_STATUS_CODES = [408, 429, 500, 502, 503, 504]


class GeminiModelProvider:
    """Google Gemini adapter restricted to synthetic demo content."""

    def __init__(self, settings: Settings, *, client: genai.Client | None = None) -> None:
        if settings.environment == "production":
            raise ModelProviderConfigurationError(
                "The Gemini demo provider is disabled in production."
            )
        if settings.model_data_policy != "synthetic_only":
            raise ModelProviderConfigurationError("The synthetic-only data policy is required.")

        api_key = settings.gemini_api_key
        if client is None and (api_key is None or not api_key.get_secret_value().strip()):
            raise ModelProviderConfigurationError("A backend Gemini API key is required.")
        if (
            client is None
            and api_key is not None
            and _looks_like_placeholder(api_key.get_secret_value())
        ):
            raise ModelProviderConfigurationError("Replace the placeholder Gemini API key.")

        self._model = settings.gemini_model
        self._max_output_tokens = settings.gemini_max_output_tokens
        self._temperature = settings.gemini_temperature
        self._client = client or genai.Client(
            api_key=api_key.get_secret_value() if api_key is not None else None,
            http_options=types.HttpOptions(
                timeout=int(settings.gemini_timeout_seconds * 1_000),
                retry_options=types.HttpRetryOptions(
                    attempts=settings.gemini_retry_attempts,
                    initial_delay=0.5,
                    exp_base=2,
                    max_delay=4,
                    jitter=0.2,
                    http_status_codes=_RETRYABLE_STATUS_CODES,
                ),
            ),
        )

    async def generate_structured(
        self,
        *,
        prompt: SyntheticPrompt,
        response_model: type[StructuredOutputT],
    ) -> StructuredModelResult[StructuredOutputT]:
        _enforce_synthetic(prompt)
        started_at = monotonic()
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt.content,
                config=types.GenerateContentConfig(
                    temperature=self._temperature,
                    max_output_tokens=self._max_output_tokens,
                    response_mime_type="application/json",
                    response_schema=response_model,
                ),
            )
            parsed = response.parsed
            if isinstance(parsed, response_model):
                output = parsed
            elif response.text:
                output = response_model.model_validate_json(response.text)
            else:
                raise ModelProviderResponseError
        except (ValidationError, ModelProviderResponseError):
            raise ModelProviderResponseError from None
        except Exception as error:
            raise _map_provider_error(error) from None

        return StructuredModelResult[StructuredOutputT](
            output=output,
            metadata=_metadata(response, self._model, started_at),
        )

    async def stream_text(
        self,
        *,
        prompt: SyntheticPrompt,
    ) -> AsyncIterator[ModelStreamEvent]:
        _enforce_synthetic(prompt)
        started_at = monotonic()
        final_response: types.GenerateContentResponse | None = None
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=prompt.content,
                config=types.GenerateContentConfig(
                    temperature=self._temperature,
                    max_output_tokens=self._max_output_tokens,
                ),
            )
            async for response in stream:
                final_response = response
                if response.text:
                    yield ModelStreamEvent(event="text_delta", text=response.text)
        except Exception as error:
            raise _map_provider_error(error) from None

        if final_response is None:
            raise ModelProviderResponseError
        yield ModelStreamEvent(
            event="complete",
            metadata=_metadata(final_response, self._model, started_at),
        )

    async def select_tool(
        self,
        *,
        prompt: SyntheticPrompt,
        tools: list[ToolDefinition],
    ) -> ToolSelectionResult:
        _enforce_synthetic(prompt)
        if not tools:
            raise ValueError("At least one tool definition is required.")

        started_at = monotonic()
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters_json_schema,
            )
            for tool in tools
        ]
        names = [tool.name for tool in tools]
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt.content,
                config=types.GenerateContentConfig(
                    temperature=self._temperature,
                    max_output_tokens=self._max_output_tokens,
                    tools=[types.Tool(function_declarations=declarations)],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode=types.FunctionCallingConfigMode.ANY,
                            allowed_function_names=names,
                        )
                    ),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            function_calls = response.function_calls or []
            if len(function_calls) != 1:
                raise ModelProviderResponseError
            selected = function_calls[0]
            if selected.name not in names:
                raise ModelProviderResponseError
            arguments = cast(dict[str, object], selected.args or {})
        except ModelProviderResponseError:
            raise
        except Exception as error:
            raise _map_provider_error(error) from None

        return ToolSelectionResult(
            call=ToolCall(name=selected.name, arguments=arguments),
            metadata=_metadata(response, self._model, started_at),
        )

    async def close(self) -> None:
        await self._client.aio.aclose()
        self._client.close()


def _looks_like_placeholder(api_key: str) -> bool:
    normalized = api_key.strip().lower()
    return normalized.startswith(("replace_", "your_", "example", "changeme"))


def _enforce_synthetic(prompt: SyntheticPrompt) -> None:
    if prompt.data_classification != "synthetic":
        raise ModelDataPolicyError


def _metadata(
    response: types.GenerateContentResponse,
    requested_model: str,
    started_at: float,
) -> ModelCallMetadata:
    usage = response.usage_metadata
    return ModelCallMetadata(
        provider="gemini",
        requested_model=requested_model,
        resolved_model=response.model_version,
        response_id=response.response_id,
        latency_ms=round((monotonic() - started_at) * 1_000),
        usage=ModelUsage(
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
            total_tokens=usage.total_token_count if usage else None,
            cached_input_tokens=usage.cached_content_token_count if usage else None,
        ),
    )


def _map_provider_error(error: Exception) -> ModelProviderUnavailableError:
    if isinstance(error, errors.APIError):
        status_code = error.code
        return ModelProviderUnavailableError(
            retryable=status_code in _RETRYABLE_STATUS_CODES,
            provider_status_code=status_code,
        )
    if isinstance(error, (OSError, TimeoutError)):
        return ModelProviderUnavailableError(retryable=True)
    return ModelProviderUnavailableError(retryable=False)
