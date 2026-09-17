"""Application settings (section 66: .env.example documents every variable).

All configuration is environment-driven so the same code runs in development,
tests and production. Validation happens once at startup: a misconfigured
deployment must fail loudly here instead of mysteriously at request time.
"""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(Exception):
    """Raised when configuration is invalid or incomplete."""


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "English-Polish Vocabulary Platform"
    app_env: str = "development"
    log_level: str = "INFO"
    log_format: str = "console"  # "console" | "json"

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/vocab_platform",
    )

    # --- HTTP ---
    cors_origins: str = "http://localhost:3000"

    # --- Auth placeholder (used from Phase 15) ---
    session_secret: str = "change-me-in-later-phases"

    # --- Embeddings placeholder (used from Phase 12) ---
    embedding_model: str = "BAAI/bge-m3"
    vector_dimension: int = 1024

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        """Accept common PostgreSQL URL spellings; normalize to the psycopg3 dialect."""
        normalized = value
        if normalized.startswith("postgres://"):
            normalized = normalized.replace("postgres://", "postgresql://", 1)
        if normalized.startswith("postgresql://"):
            normalized = normalized.replace("postgresql://", "postgresql+psycopg://", 1)
        if not normalized.startswith(("postgresql+psycopg://", "sqlite://")):
            raise SettingsError(
                "DATABASE_URL must be a PostgreSQL URL "
                "(postgresql:// or postgresql+psycopg://). "
                "SQLite is permitted only for pipeline/construction use."
            )
        parsed = urlparse(normalized)
        if parsed.scheme.startswith("postgresql") and not parsed.path.lstrip("/"):
            raise SettingsError("DATABASE_URL must include a database name")
        return normalized

    @field_validator("app_env")
    @classmethod
    def _validate_app_env(cls, value: str) -> str:
        allowed = {"development", "test", "staging", "production"}
        if value not in allowed:
            raise SettingsError(f"APP_ENV must be one of {sorted(allowed)}")
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if value.upper() not in allowed:
            raise SettingsError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return value.upper()

    @field_validator("log_format")
    @classmethod
    def _validate_log_format(cls, value: str) -> str:
        allowed = {"console", "json"}
        if value.lower() not in allowed:
            raise SettingsError(f"LOG_FORMAT must be one of {sorted(allowed)}")
        return value.lower()

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list (comma-separated env value)."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings; invalid config raises at first use."""
    return Settings()
