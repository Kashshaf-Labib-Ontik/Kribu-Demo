from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.errors import ModelProviderConfigurationError, ModelProviderResponseError
from app.brain.embeddings import GeminiEmbeddingProvider
from app.core.config import Settings


class FakeModels:
    def __init__(self, dimensions: int = 768) -> None:
        self.dimensions = dimensions
        self.calls: list[dict[str, Any]] = []

    async def embed_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        contents = kwargs["contents"]
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1] * self.dimensions) for _ in contents]
        )


class FakeClient:
    def __init__(self, dimensions: int = 768) -> None:
        self.models = FakeModels(dimensions)
        self.aio = SimpleNamespace(models=self.models, aclose=self._aclose)

    async def _aclose(self) -> None:
        return None

    def close(self) -> None:
        return None


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://example.invalid/kribu",
        gemini_api_key="synthetic-test-key",
        **overrides,
    )


@pytest.mark.asyncio
async def test_gemini_embedding_formats_query_and_documents_separately() -> None:
    client = FakeClient()
    provider = GeminiEmbeddingProvider(settings(), client=client)  # type: ignore[arg-type]

    documents = await provider.embed_documents(title="Progress report", texts=["Permit pending"])
    query = await provider.embed_query("Why is the project delayed?")

    assert len(documents[0]) == 768
    assert len(query) == 768
    assert math.sqrt(sum(value * value for value in documents[0])) == pytest.approx(1.0)
    assert math.sqrt(sum(value * value for value in query)) == pytest.approx(1.0)
    document_text = client.models.calls[0]["contents"][0].parts[0].text
    query_text = client.models.calls[1]["contents"][0].parts[0].text
    assert document_text == "title: Progress report | text: Permit pending"
    assert query_text == "task: question answering | query: Why is the project delayed?"


@pytest.mark.asyncio
async def test_gemini_embedding_rejects_wrong_dimensions() -> None:
    provider = GeminiEmbeddingProvider(settings(), client=FakeClient(12))  # type: ignore[arg-type]

    with pytest.raises(ModelProviderResponseError):
        await provider.embed_query("synthetic query")


def test_gemini_embedding_is_disabled_in_production() -> None:
    with pytest.raises(ModelProviderConfigurationError):
        GeminiEmbeddingProvider(settings(environment="production"), client=FakeClient())  # type: ignore[arg-type]
