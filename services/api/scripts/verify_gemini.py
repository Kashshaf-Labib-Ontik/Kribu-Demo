from __future__ import annotations

import argparse
import asyncio
import json

from pydantic import BaseModel, Field

from app.ai.contracts import ModelProvider, SyntheticPrompt, ToolDefinition
from app.ai.errors import ModelProviderError
from app.ai.factory import create_model_provider
from app.core.config import get_settings


class DemoProjectFinding(BaseModel):
    status: str = Field(description="The supported project status.")
    delayed_milestone_ids: list[str]
    summary: str


async def run_spike() -> int:
    provider: ModelProvider | None = None
    try:
        provider = create_model_provider(get_settings())
        structured = await provider.generate_structured(
            prompt=SyntheticPrompt(
                content=(
                    "Synthetic demo record: milestone M-17 was due on 2026-09-15 and "
                    "remains incomplete on 2026-10-01. Return the supported status, "
                    "delayed milestone IDs, and a short summary."
                )
            ),
            response_model=DemoProjectFinding,
        )

        streamed_text: list[str] = []
        stream_metadata = None
        async for event in provider.stream_text(
            prompt=SyntheticPrompt(
                content="Summarize this synthetic fact in one sentence: milestone M-17 is late."
            )
        ):
            if event.event == "text_delta":
                streamed_text.append(event.text)
            else:
                stream_metadata = event.metadata

        tool_result = await provider.select_tool(
            prompt=SyntheticPrompt(
                content="Use the available tool to retrieve synthetic milestone M-17."
            ),
            tools=[
                ToolDefinition(
                    name="get_demo_milestone",
                    description="Retrieves one milestone from the synthetic demo fixture.",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "milestone_id": {
                                "type": "string",
                                "description": "Synthetic milestone identifier.",
                            }
                        },
                        "required": ["milestone_id"],
                        "additionalProperties": False,
                    },
                )
            ],
        )

        print(
            json.dumps(
                {
                    "structured": structured.model_dump(mode="json"),
                    "streaming": {
                        "text": "".join(streamed_text),
                        "metadata": stream_metadata.model_dump(mode="json")
                        if stream_metadata
                        else None,
                    },
                    "tool_selection": tool_result.model_dump(mode="json"),
                },
                indent=2,
            )
        )
        return 0
    except ModelProviderError as error:
        print(
            json.dumps(
                {
                    "error": error.code,
                    "message": error.safe_message,
                    "retryable": error.retryable,
                    "provider_status_code": error.provider_status_code,
                },
                indent=2,
            )
        )
        return 1
    finally:
        if provider is not None:
            await provider.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Gemini using synthetic demo prompts only.")
    parser.add_argument(
        "--confirm-synthetic",
        action="store_true",
        help="Confirm that this command may send its built-in synthetic prompts to Gemini.",
    )
    arguments = parser.parse_args()
    if not arguments.confirm_synthetic:
        parser.error("--confirm-synthetic is required")
    raise SystemExit(asyncio.run(run_spike()))


if __name__ == "__main__":
    main()
