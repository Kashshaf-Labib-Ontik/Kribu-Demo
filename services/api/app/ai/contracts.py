from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class SyntheticPrompt(BaseModel):
    """Explicit trust-boundary wrapper for content sent to the demo provider."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(min_length=1, max_length=100_000)
    data_classification: Literal["synthetic"] = "synthetic"


class ModelUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None


class ModelCallMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    requested_model: str
    resolved_model: str | None = None
    response_id: str | None = None
    latency_ms: int = Field(ge=0)
    usage: ModelUsage


class StructuredModelResult(BaseModel, Generic[StructuredOutputT]):
    model_config = ConfigDict(frozen=True)

    output: StructuredOutputT
    metadata: ModelCallMetadata


class ModelStreamEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event: Literal["text_delta", "complete"]
    text: str = ""
    metadata: ModelCallMetadata | None = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
    description: str = Field(min_length=1, max_length=1_000)
    parameters_json_schema: dict[str, object]


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    arguments: dict[str, object]


class ToolSelectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    call: ToolCall
    metadata: ModelCallMetadata


class ModelProvider(Protocol):
    async def generate_structured(
        self,
        *,
        prompt: SyntheticPrompt,
        response_model: type[StructuredOutputT],
    ) -> StructuredModelResult[StructuredOutputT]: ...

    def stream_text(self, *, prompt: SyntheticPrompt) -> AsyncIterator[ModelStreamEvent]: ...

    async def select_tool(
        self,
        *,
        prompt: SyntheticPrompt,
        tools: list[ToolDefinition],
    ) -> ToolSelectionResult: ...

    async def close(self) -> None: ...
