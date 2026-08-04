from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    redis_url: str
    biometric_kek: SecretStr
    jwt_secret: SecretStr = SecretStr("default_kiosk_jwt_secret_change_me_in_production")
    audit_chain_export_dir: str | None = None
    audit_chain_export_environment: str = "production"
    audit_chain_export_deployment_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
