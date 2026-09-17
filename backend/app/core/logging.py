"""Logging configuration (section 56).

Requirements implemented here:

- structured (one JSON object per line) or human-readable console output,
  selectable via LOG_FORMAT;
- request correlation ID present on every log record;
- never log passwords, session secrets or tokens (section 56): sensitive
  keys are masked before rendering.

Usage: ``from app.core.logging import get_logger; logger = get_logger(__name__)``.
"""

import json
import logging
import sys
from typing import Any

from app.core.context import get_request_id
from app.core.settings import get_settings

# Keys whose values must never reach the logs (section 56).
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "session_secret",
        "session_id",
        "token",
        "secret",
        "authorization",
        "cookie",
        "api_key",
    }
)


def _mask_sensitive(value: Any) -> Any:
    """Recursively mask values whose key looks sensitive."""
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in SENSITIVE_KEYS else _mask_sensitive(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mask_sensitive(v) for v in value]
    return value


class CorrelationFilter(logging.Filter):
    """Attach the current correlation ID to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


# Standard LogRecord attributes; anything else came from `extra=` and is
# worth rendering (route, status, duration_ms, ...).
_STANDARD_RECORD_ATTRS = frozenset(
    vars(logging.LogRecord("x", 0, "x", 0, "x", None, None)).keys()
) | {
    "message",
    "asctime",
    "taskName",
    "request_id",  # handled explicitly
}


class JsonFormatter(logging.Formatter):
    """Render one JSON object per line (one log event = one line).

    Scalar fields passed via ``extra=`` are included (after masking), so
    access-log lines carry route/status/duration as searchable keys.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(_mask_sensitive(payload), ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable single-line format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} "
            f"{record.levelname:<7} [{getattr(record, 'request_id', '-')}] "
            f"{record.name}: {record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    """Configure the root logger once, according to settings."""
    s = get_settings()
    root = logging.getLogger()
    root.setLevel(s.log_level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(CorrelationFilter())
    if s.log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())
    root.handlers[:] = [handler]


def get_logger(name: str) -> logging.Logger:
    """Return a named logger under the app namespace."""
    return logging.getLogger(name)
