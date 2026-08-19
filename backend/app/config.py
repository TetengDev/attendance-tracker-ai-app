from __future__ import annotations

import os
import sys
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_file = None if ("pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ) else ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment and optional .env file."""

    model_config = SettingsConfigDict(
        env_file=_env_file,
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
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5178,http://127.0.0.1:5178"
    public_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
