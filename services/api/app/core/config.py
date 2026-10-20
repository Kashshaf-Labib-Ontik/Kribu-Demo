from functools import lru_cache
from pathlib import Path
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
    # Required, no default: a silent fallback to the bootstrap superuser would bypass RLS.
    database_url: SecretStr
    cors_origins: list[AnyHttpUrl] = [AnyHttpUrl("http://localhost:3000")]
    oidc_issuer_url: str = "http://localhost:8180/realms/kribu-demo"
    oidc_jwks_url: str = "http://localhost:8180/realms/kribu-demo/protocol/openid-connect/certs"
    oidc_audience: str = "kribu-api"
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=120)
    opa_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8181")
    opa_timeout_seconds: float = Field(default=2, gt=0, le=10)
    opa_policy_version: str = Field(default="guard-v2", min_length=1)
    document_store_path: Path = Path("storage/documents")
    upload_max_bytes: int = Field(default=26_214_400, ge=1, le=268_435_456)
    celery_broker_url: SecretStr = SecretStr("redis://localhost:6379/0")
    ingestion_owner_database_url: SecretStr | None = None
    ingestion_poll_seconds: int = Field(default=15, ge=5, le=300)
    ingestion_task_timeout_seconds: int = Field(default=120, ge=10, le=600)
    ingestion_max_pdf_pages: int = Field(default=250, ge=1, le=2_000)
    ingestion_max_content_units: int = Field(default=100_000, ge=1, le=1_000_000)
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
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
