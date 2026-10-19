from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl
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


@lru_cache
def get_settings() -> Settings:
    return Settings()

