from app.ai.contracts import ModelProvider
from app.ai.gemini import GeminiModelProvider
from app.core.config import Settings


def create_model_provider(settings: Settings) -> ModelProvider:
    if settings.model_provider == "gemini":
        return GeminiModelProvider(settings)
    raise AssertionError(f"Unsupported model provider: {settings.model_provider}")
