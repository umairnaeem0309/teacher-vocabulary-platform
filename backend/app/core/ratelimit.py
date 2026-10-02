"""Rate limiting (phase 23, section 39: "rate limiting where appropriate").

The platform is single-teacher-per-deployment software (§39 student
isolation model), so limiting is per **client IP** — not per account.
Windows are fixed-window-per-key and the counters live in process memory
(a restart resets them; multi-worker deployments should put a real
limiter in front — noted in architecture.md). Behind a reverse proxy,
run uvicorn with ``--proxy-headers`` so ``client.host`` is the real
client.

An over-budget request is answered with 429 and the standard error
envelope (code ``rate_limited``) plus ``Retry-After`` and
``X-RateLimit-Limit`` headers so polite clients can back off.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.core.settings import Settings

#: Route classes (§39 "where appropriate": scarce or expensive endpoints
#: get their own tighter budget). Everything else is read or write.
LIMIT_LOGIN = "login"
LIMIT_READ = "read"
LIMIT_WRITE = "write"
LIMIT_UPLOAD = "upload"


@dataclass(frozen=True)
class Limit:
    """One fixed-window budget: ``max_requests`` per ``window_seconds``."""

    name: str
    max_requests: int
    window_seconds: int


@dataclass
class _Window:
    """A mutable fixed window for one (key, class) pair."""

    start: float
    count: int
    period: int


@dataclass(frozen=True)
class Decision:
    """Outcome of one rate-limit check."""

    allowed: bool
    limit: Limit
    #: Whole seconds until the current window rolls over (Retry-After).
    retry_after: int


class RateLimiter:
    """Thread-safe in-process fixed-window counter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], _Window] = {}

    def check(self, key: str, limit: Limit) -> Decision:
        """Count one request for ``key`` under ``limit``."""
        now = time.monotonic()
        with self._lock:
            win = self._windows.get((key, limit.name))
            if win is None or now - win.start >= limit.window_seconds:
                # New window. Opportunistically drop fully-elapsed windows
                # (they are dead anyway; the map must not grow unbounded).
                if len(self._windows) > 10_000:
                    self._sweep(now)
                self._windows[(key, limit.name)] = _Window(
                    start=now, count=1, period=limit.window_seconds
                )
                return Decision(True, limit, limit.window_seconds)
            win.count += 1
            allowed = win.count <= limit.max_requests
            return Decision(allowed, limit, limit.window_seconds)

    def _sweep(self, now: float) -> None:
        """Drop fully-elapsed windows (caller holds the lock)."""
        elapsed = [k for k, w in self._windows.items() if now - w.start >= w.period]
        for k in elapsed:
            del self._windows[k]


def limits_from_settings(settings: Settings) -> dict[str, Limit]:
    """Build the route-class → limit map from application settings."""
    return {
        LIMIT_LOGIN: Limit(
            name=LIMIT_LOGIN,
            max_requests=settings.rate_limit_login_max,
            window_seconds=settings.rate_limit_auth_window_seconds,
        ),
        LIMIT_READ: Limit(
            name=LIMIT_READ,
            max_requests=settings.rate_limit_read_max,
            window_seconds=settings.rate_limit_read_window_seconds,
        ),
        LIMIT_WRITE: Limit(
            name=LIMIT_WRITE,
            max_requests=settings.rate_limit_write_max,
            window_seconds=settings.rate_limit_write_window_seconds,
        ),
        LIMIT_UPLOAD: Limit(
            name=LIMIT_UPLOAD,
            max_requests=settings.rate_limit_upload_max,
            window_seconds=settings.rate_limit_auth_window_seconds,
        ),
    }
