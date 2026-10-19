from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_prefix="KRIBU_",
        extra="ignore",
    )

    service_name: str = "kribu-api"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "postgresql+asyncpg://kribu:kribu_dev_only@localhost:5432/kribu"
    cors_origins: list[AnyHttpUrl] = [AnyHttpUrl("http://localhost:3000")]
    model_provider: Literal["gemini"] = "gemini"
    model_data_policy: Literal["synthetic_only"] = "synthetic_only"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_max_output_tokens: int = Field(default=4096, ge=1, le=65_536)
    gemini_temperature: float = Field(default=0.1, ge=0, le=2)
    gemini_timeout_seconds: float = Field(default=30, ge=1, le=120)
    gemini_retry_attempts: int = Field(default=3, ge=1, le=5)


@lru_cache
def get_settings() -> Settings:
    return Settings()
