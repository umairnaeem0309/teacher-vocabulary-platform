"""Application configuration.

All settings are read from environment variables (12-factor style) so the same
code runs in local development, tests and production. See .env.example at the
repository root for documentation of every variable.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "English-Polish Vocabulary Platform"
    app_env: str = "development"

    # --- Database ---
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/vocab_platform"

    # --- HTTP ---
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()
