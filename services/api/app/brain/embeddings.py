"""Replaceable embedding boundary; Gemini is the synthetic demo implementation."""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Any, Protocol, cast

from google import genai
from google.genai import errors, types

from app.ai.errors import (
    ModelDataPolicyError,
    ModelProviderConfigurationError,
    ModelProviderResponseError,
    ModelProviderUnavailableError,
)
from app.core.config import Settings

logger = logging.getLogger(__name__)

EMBEDDING_PROVIDER = "gemini"
EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMENSION = 768
EMBEDDING_FORMAT_VERSION = "question-answering-v1"
INDEX_CONTRACT = (
    f"{EMBEDDING_PROVIDER}:{EMBEDDING_MODEL}:{EMBEDDING_DIMENSION}:"
    f"{EMBEDDING_FORMAT_VERSION}:structure-v1"
)
_RETRYABLE = {408, 429, 500, 502, 503, 504}


class EmbeddingProvider(Protocol):
    async def embed_documents(self, *, title: str, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, query: str) -> list[float]: ...

    async def close(self) -> None: ...


class GeminiEmbeddingProvider:
    def __init__(self, settings: Settings, *, client: genai.Client | None = None) -> None:
        if settings.environment == "production":
            raise ModelProviderConfigurationError(
                "The Gemini demo embedding provider is disabled in production."
            )
        if settings.model_data_policy != "synthetic_only":
            raise ModelDataPolicyError()
        api_key = settings.gemini_api_key
        if client is None and (api_key is None or not api_key.get_secret_value().strip()):
            raise ModelProviderConfigurationError("A backend Gemini API key is required.")
        self._model = settings.gemini_embedding_model
        self._dimension = settings.gemini_embedding_dimension
        self._batch_size = settings.gemini_embedding_batch_size
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
                    http_status_codes=sorted(_RETRYABLE),
                ),
            ),
        )

    async def embed_documents(self, *, title: str, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            prepared = [
                f"title: {title} | text: {text}" for text in texts[start : start + self._batch_size]
            ]
            vectors.extend(await self._embed_many(prepared))
        if len(vectors) != len(texts):
            raise ModelProviderResponseError()
        return vectors

    async def embed_query(self, query: str) -> list[float]:
        vectors = await self._embed_many([f"task: question answering | query: {query}"])
        if len(vectors) != 1:
            raise ModelProviderResponseError()
        return vectors[0]

    async def _embed_many(self, values: Sequence[str]) -> list[list[float]]:
        if not values:
            return []
        contents = [types.Content(role="user", parts=[types.Part(text=value)]) for value in values]
        try:
            response = await self._client.aio.models.embed_content(
                model=self._model,
                contents=cast(Any, contents),
                config=types.EmbedContentConfig(output_dimensionality=self._dimension),
            )
            embeddings = response.embeddings or []
            vectors = [cast(list[float], embedding.values or []) for embedding in embeddings]
            if len(vectors) != len(values) or any(
                len(vector) != self._dimension for vector in vectors
            ):
                raise ModelProviderResponseError()
            return [_normalize(vector) for vector in vectors]
        except ModelProviderResponseError:
            raise
        except Exception as error:
            logger.warning("Gemini embedding call failed: %s", type(error).__name__)
            if isinstance(error, errors.APIError):
                raise ModelProviderUnavailableError(
                    retryable=error.code in _RETRYABLE,
                    provider_status_code=error.code,
                ) from error
            if isinstance(error, (OSError, TimeoutError)):
                raise ModelProviderUnavailableError(retryable=True) from error
            raise ModelProviderUnavailableError(retryable=False) from error

    async def close(self) -> None:
        await self._client.aio.aclose()
        self._client.close()


def _normalize(vector: list[float]) -> list[float]:
    if any(not math.isfinite(value) for value in vector):
        raise ModelProviderResponseError()
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= 0:
        raise ModelProviderResponseError()
    return [value / magnitude for value in vector]
