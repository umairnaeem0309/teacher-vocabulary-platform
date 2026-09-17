"""Settings re-export.

The implementation lives in :mod:`app.core.settings`; this module keeps the
short import path (``from app.config import settings``) used across the app.
"""

from app.core.settings import Settings, SettingsError, get_settings

settings = get_settings()

__all__ = ["Settings", "SettingsError", "get_settings", "settings"]
