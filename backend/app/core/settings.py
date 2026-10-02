"""Application settings (section 66: .env.example documents every variable).

All configuration is environment-driven so the same code runs in development,
tests and production. Validation happens once at startup: a misconfigured
deployment must fail loudly here instead of mysteriously at request time.
"""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
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

    # --- Security hardening (phase 23, section 39) ---
    #: Comma-separated list of origins allowed to make state-changing
    #: (browser) requests. Empty disables the Origin check entirely (pure
    #: non-browser API clients; not recommended when cookies are used).
    allowed_request_origins: str = "http://localhost:3000"
    #: Sliding-window rate limiting (per client IP + route class). Zero or
    #: negative disables limiting entirely.
    rate_limit_enabled: bool = True
    rate_limit_login_max: int = 10
    rate_limit_auth_window_seconds: int = 300
    rate_limit_read_max: int = 240
    rate_limit_read_window_seconds: int = 60
    rate_limit_write_max: int = 120
    rate_limit_write_window_seconds: int = 60
    rate_limit_upload_max: int = 20
    rate_limit_upload_window_seconds: int = 300
    #: Hard cap on uploaded import-file size (§39 safe file handling).
    upload_max_bytes: int = 5_242_880  # 5 MiB

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

    @model_validator(mode="after")
    def _production_requires_secret(self) -> "Settings":
        """A placeholder session secret must never reach production (§39
        secret management): fail loudly at startup, not at incident time."""
        if self.app_env in ("production", "staging") and self.session_secret == (
            "change-me-in-later-phases"
        ):
            raise SettingsError(
                "SESSION_SECRET must be set to a strong random value "
                "when APP_ENV is production or staging."
            )
        return self

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

    @property
    def allowed_request_origin_list(self) -> list[str]:
        """Origins allowed to make state-changing requests (CSRF defense,
        phase 23). Empty disables the Origin check entirely."""
        return [o.strip() for o in self.allowed_request_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings; invalid config raises at first use."""
    return Settings()
