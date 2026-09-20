"""Normalized intermediate records shared by all source adapters (Phase 4).

Adapters convert raw source rows into these dataclasses. This is the contract
between Phase 4 (adapters) and Phase 5 (normalization): everything an adapter
extracts survives here, including anomalies — nothing is silently dropped
(section 45). Statistics (processed/skipped/failed/warning) are mandatory
adapter output (section 45) and feed pipeline observability (section 126).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecordStats:
    """Per-run adapter statistics (section 45)."""

    processed: int = 0
    skipped: int = 0
    failed: int = 0
    warning: int = 0
    read: int = 0

    def merge(self, other: RecordStats) -> None:
        self.processed += other.processed
        self.skipped += other.skipped
        self.failed += other.failed
        self.warning += other.warning
        self.read += other.read

    def as_dict(self) -> dict[str, int]:
        return {
            "read": self.read,
            "processed": self.processed,
            "skipped": self.skipped,
            "failed": self.failed,
            "warning": self.warning,
        }


@dataclass
class AdapterRun:
    """Result of one adapter execution: records + stats + provenance."""

    source: str
    records: list[Any] = field(default_factory=list)
    stats: RecordStats = field(default_factory=RecordStats)
    errors: list[dict[str, Any]] = field(default_factory=list)  # failed rows, capped
    warnings: list[dict[str, Any]] = field(default_factory=list)  # warning samples

    def add_error(self, record_id: str, detail: str) -> None:
        """Record a failure (capped list keeps memory bounded)."""
        if len(self.errors) < 100:
            self.errors.append({"record_id": record_id, "detail": detail})

    def add_warning(self, record_id: str, detail: str) -> None:
        """Record a warning sample (capped list keeps memory bounded)."""
        if len(self.warnings) < 100:
            self.warnings.append({"record_id": record_id, "detail": detail})


def _clean(value: str | None) -> str:
    """Trim whitespace; empty string becomes ''."""
    return (value or "").strip()


def _normalize_ws(value: str) -> str:
    """Collapse internal whitespace runs to single spaces."""
    return " ".join(value.split())
