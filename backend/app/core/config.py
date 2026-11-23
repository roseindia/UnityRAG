"""Application configuration (12-factor, environment driven).

Secrets are never hard-coded: every credential is read from the environment
(or a secrets-manager-injected env file) and the application refuses to start
in production with development defaults (NFR-039).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-change-me-dev-only-change-me-0000"  # noqa: S105 - development sentinel; refused in production


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "UnityRAG"
    environment: Literal["development", "test", "staging", "production"] = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])

    # --- PostgreSQL (one login role per process type; none has BYPASSRLS) ---------
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "enterprise_rag"
    db_app_user: str = "rag_app"
    db_app_password: SecretStr = SecretStr("devpass")
    db_worker_user: str = "rag_worker"
    db_worker_password: SecretStr = SecretStr("devpass")
    db_readonly_user: str = "rag_readonly"
    db_readonly_password: SecretStr = SecretStr("devpass")
    # Migration credentials are only read by the migration / bootstrap entry points.
    db_migration_user: str = "rag_migration"
    db_migration_password: SecretStr = SecretStr("devpass")
    db_superuser_dsn: SecretStr | None = None  # bootstrap only (create roles / extensions)
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_sslmode: str = "prefer"

    # --- Redis / Celery -------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_task_always_eager: bool = False
    cache_backend: Literal["redis", "memory"] = "redis"
    cache_ttl_seconds: int = 300

    # --- Authentication -------------------------------------------------------------
    auth_mode: Literal["local", "oidc", "both"] = "both"
    jwt_secret: SecretStr = SecretStr(_DEV_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "enterprise-rag"
    jwt_audience: str = "enterprise-rag-api"
    access_token_minutes: int = 10
    refresh_token_hours: int = 12
    password_min_length: int = 12
    lockout_threshold: int = 5
    lockout_minutes: int = 15
    password_reset_minutes: int = 30
    mfa_step_up_minutes: int = 15
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_email_claim: str = "email"

    # --- Secrets encryption (provider API keys, MFA secrets) ---------------------------
    secrets_encryption_key: SecretStr | None = None  # Fernet key; derived from jwt_secret in dev only

    # --- Object storage --------------------------------------------------------------
    storage_root: Path = Path("./var/storage")

    # --- Ingestion ---------------------------------------------------------------------
    malware_scanner: Literal["none", "clamav"] = "none"
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    tesseract_cmd: str | None = None
    ocr_languages: str = "eng"
    ocr_min_confidence: float = 60.0
    ocr_min_chars_per_page: int = 25

    # --- API protection ------------------------------------------------------------------
    rate_limit_per_minute: int = 120
    chat_rate_limit_per_minute: int = 20
    max_request_bytes: int = 600 * 1024 * 1024

    metrics_enabled: bool = True
    otel_enabled: bool = False          # OTLP/HTTP span export (OTEL_EXPORTER_OTLP_* variables)
    otel_service_name: str = "unityrag"

    @field_validator("secrets_encryption_key", mode="before")
    @classmethod
    def _blank_key_is_unset(cls, v):
        # The template ships an empty value; treat it as "not set" so development falls back to the derived key.
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode="after")
    def _production_guard(self) -> Settings:
        if self.environment == "production":
            if self.jwt_secret.get_secret_value() == _DEV_SECRET or len(self.jwt_secret.get_secret_value()) < 32:
                raise ValueError("JWT_SECRET must be set to a strong value in production")
            if self.secrets_encryption_key is None:
                raise ValueError("SECRETS_ENCRYPTION_KEY is required in production")
            if self.db_app_password.get_secret_value() == "devpass":
                raise ValueError("database passwords must be set in production")
            if self.malware_scanner == "none":
                raise ValueError("a malware scanner is mandatory in production (FR-029)")
        return self

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    def dsn(self, role: Literal["app", "worker", "readonly", "migration"]) -> str:
        user, password = {
            "app": (self.db_app_user, self.db_app_password),
            "worker": (self.db_worker_user, self.db_worker_password),
            "readonly": (self.db_readonly_user, self.db_readonly_password),
            "migration": (self.db_migration_user, self.db_migration_password),
        }[role]
        from urllib.parse import quote_plus

        return (
            f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password.get_secret_value())}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?sslmode={self.db_sslmode}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
