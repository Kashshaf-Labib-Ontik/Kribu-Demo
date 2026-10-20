from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends

from app.brain.embeddings import EmbeddingProvider, GeminiEmbeddingProvider
from app.core.config import Settings, get_settings


async def get_embedding_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[EmbeddingProvider]:
    provider = GeminiEmbeddingProvider(settings)
    try:
        yield provider
    finally:
        await provider.close()
