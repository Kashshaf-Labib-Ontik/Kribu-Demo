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
    # Required, no default: a silent fallback to the bootstrap superuser would bypass RLS.
    database_url: SecretStr
    cors_origins: list[AnyHttpUrl] = [AnyHttpUrl("http://localhost:3000")]
    oidc_issuer_url: str = "http://localhost:8180/realms/kribu-demo"
    oidc_jwks_url: str = "http://localhost:8180/realms/kribu-demo/protocol/openid-connect/certs"
    oidc_audience: str = "kribu-api"
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=120)
    opa_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8181")
    opa_timeout_seconds: float = Field(default=2, gt=0, le=10)
    opa_policy_version: str = Field(default="guard-v1", min_length=1)
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
