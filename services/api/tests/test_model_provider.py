from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.ai.contracts import SyntheticPrompt, ToolDefinition
from app.ai.errors import (
    ModelDataPolicyError,
    ModelProviderConfigurationError,
    ModelProviderUnavailableError,
)
from app.ai.gemini import GeminiModelProvider
from app.core.config import Settings


class DemoAnswer(BaseModel):
    answer: str


def test_prompt_rejects_non_synthetic_classification() -> None:
    with pytest.raises(ValidationError):
        SyntheticPrompt(content="private record", data_classification="confidential")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_provider_rechecks_synthetic_policy_at_call_boundary() -> None:
    provider = GeminiModelProvider(Settings(), client=_client_with_response(Mock()))
    bypassed_prompt = SyntheticPrompt.model_construct(
        content="private record", data_classification="confidential"
    )

    with pytest.raises(ModelDataPolicyError):
        await provider.generate_structured(prompt=bypassed_prompt, response_model=DemoAnswer)


def test_provider_rejects_placeholder_key() -> None:
    settings = Settings(gemini_api_key="replace_with_google_ai_studio_key")

    with pytest.raises(ModelProviderConfigurationError) as captured:
        GeminiModelProvider(settings)

    assert captured.value.code == "model_provider_not_configured"


def test_provider_rejects_demo_configuration_in_production() -> None:
    settings = Settings(environment="production", gemini_api_key="valid-looking-demo-key")

    with pytest.raises(ModelProviderConfigurationError):
        GeminiModelProvider(settings)


@pytest.mark.asyncio
async def test_structured_output_records_safe_metadata() -> None:
    response = types.GenerateContentResponse(
        parsed=DemoAnswer(answer="Milestone M-17 is delayed."),
        model_version="gemini-test-version",
        response_id="response-1",
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10,
            candidates_token_count=6,
            total_token_count=16,
        ),
    )
    client = _client_with_response(response)
    provider = GeminiModelProvider(Settings(), client=client)

    result = await provider.generate_structured(
        prompt=SyntheticPrompt(content="Synthetic milestone M-17 is delayed."),
        response_model=DemoAnswer,
    )

    assert result.output.answer == "Milestone M-17 is delayed."
    assert result.metadata.model_dump() == {
        "provider": "gemini",
        "requested_model": "gemini-3.8-flash",
        "resolved_model": "gemini-test-version",
        "response_id": "response-1",
        "latency_ms": result.metadata.latency_ms,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 6,
            "total_tokens": 16,
            "cached_input_tokens": None,
        },
    }


@pytest.mark.asyncio
async def test_quota_failure_is_safe_retryable_and_records_status() -> None:
    client = Mock()
    client.aio.models.generate_content = AsyncMock(
        side_effect=errors.ClientError(429, {"error": {"message": "quota exhausted"}})
    )
    provider = GeminiModelProvider(Settings(), client=cast(genai.Client, client))

    with pytest.raises(ModelProviderUnavailableError) as captured:
        await provider.generate_structured(
            prompt=SyntheticPrompt(content="Synthetic milestone M-17 is delayed."),
            response_model=DemoAnswer,
        )

    assert captured.value.code == "model_provider_unavailable"
    assert captured.value.retryable is True
    assert captured.value.provider_status_code == 429
    assert "quota exhausted" not in str(captured.value)


@pytest.mark.asyncio
async def test_streaming_emits_text_then_completion_metadata() -> None:
    async def response_stream():  # type: ignore[no-untyped-def]
        yield types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model", parts=[types.Part.from_text(text="Milestone M-17")]
                    )
                )
            ]
        )
        yield types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model", parts=[types.Part.from_text(text=" is delayed.")]
                    )
                )
            ],
            usage_metadata=types.GenerateContentResponseUsageMetadata(total_token_count=12),
        )

    client = Mock()
    client.aio.models.generate_content_stream = AsyncMock(return_value=response_stream())
    provider = GeminiModelProvider(Settings(), client=cast(genai.Client, client))

    events = [
        event
        async for event in provider.stream_text(
            prompt=SyntheticPrompt(content="Summarize synthetic milestone M-17.")
        )
    ]

    assert [event.event for event in events] == ["text_delta", "text_delta", "complete"]
    assert "".join(event.text for event in events) == "Milestone M-17 is delayed."
    assert events[-1].metadata is not None
    assert events[-1].metadata.usage.total_tokens == 12


@pytest.mark.asyncio
async def test_tool_selection_returns_declared_call_without_executing_it() -> None:
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="get_demo_milestone",
                                args={"milestone_id": "M-17"},
                            )
                        )
                    ],
                )
            )
        ]
    )
    client = _client_with_response(response)
    provider = GeminiModelProvider(Settings(), client=client)

    result = await provider.select_tool(
        prompt=SyntheticPrompt(content="Retrieve synthetic milestone M-17."),
        tools=[
            ToolDefinition(
                name="get_demo_milestone",
                description="Retrieve a synthetic milestone.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"milestone_id": {"type": "string"}},
                    "required": ["milestone_id"],
                },
            )
        ],
    )

    assert result.call.name == "get_demo_milestone"
    assert result.call.arguments == {"milestone_id": "M-17"}


def _client_with_response(response: types.GenerateContentResponse) -> genai.Client:
    client = Mock()
    client.aio.models.generate_content = AsyncMock(return_value=response)
    return cast(genai.Client, client)
