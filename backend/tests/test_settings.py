"""Tests for settings validation (fail-fast configuration, section 66)."""

import pytest

from app.core.settings import Settings, SettingsError


class TestDatabaseUrlValidation:
    """DATABASE_URL is normalized and strictly validated."""

    def test_plain_postgresql_url_normalized(self) -> None:
        s = Settings(database_url="postgresql://u:p@localhost:5432/db")
        assert s.database_url.startswith("postgresql+psycopg://")

    def test_legacy_postgres_scheme_normalized(self) -> None:
        s = Settings(database_url="postgres://u:p@localhost:5432/db")
        assert s.database_url.startswith("postgresql+psycopg://")

    def test_psycopg_url_accepted_as_is(self) -> None:
        url = "postgresql+psycopg://u:p@localhost:5432/db"
        assert Settings(database_url=url).database_url == url

    def test_non_postgres_backend_rejected(self) -> None:
        with pytest.raises(SettingsError):
            Settings(database_url="mysql://u:p@localhost/db")

    def test_missing_database_name_rejected(self) -> None:
        with pytest.raises(SettingsError):
            Settings(database_url="postgresql://u:p@localhost")


class TestEnumValidation:
    """Enum-ish settings reject unknown values."""

    def test_bad_app_env_rejected(self) -> None:
        with pytest.raises(SettingsError):
            Settings(app_env="notanenv")

    def test_bad_log_level_rejected(self) -> None:
        with pytest.raises(SettingsError):
            Settings(log_level="VERBOSE")

    def test_bad_log_format_rejected(self) -> None:
        with pytest.raises(SettingsError):
            Settings(log_format="xml")


class TestCorsParsing:
    """CORS origins parse from a comma-separated string."""

    def test_multiple_origins(self) -> None:
        s = Settings(cors_origins="http://a:3000, http://b:3000")
        assert s.cors_origin_list == ["http://a:3000", "http://b:3000"]

    def test_empty_origins(self) -> None:
        assert Settings(cors_origins="").cors_origin_list == []
