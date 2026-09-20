"""NGSL 1.2 frequency stats adapter (Phase 4).

Frequency evidence: lemma, SFI rank, SFI, adjusted frequency per million.
Policy:

- rows with unparsable numbers are **failed** (counted, sampled);
- duplicate lemmas are kept with a warning (Phase 7 reconciliation decides;
  adapter never silently drops, section 45).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.records import AdapterRun, _clean, _normalize_ws

SOURCE_KEY = "ngsl"


@dataclass
class SourceFrequencyRecord:
    """One frequency statement from NGSL."""

    lemma: str
    rank: int
    sfi: float
    frequency_per_million: float
    source: str = SOURCE_KEY
    source_record_id: str = ""
    warnings: list[str] = field(default_factory=list)


def adapt_ngsl(path: Path) -> AdapterRun:
    """Parse the NGSL CSV into normalized frequency records."""
    run = AdapterRun(source=SOURCE_KEY)
    seen: set[str] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_number, row in enumerate(reader, start=2):
            run.stats.read += 1
            record_id = f"ngsl:row:{row_number}"

            lemma = _normalize_ws(_clean(row.get("Lemma")))
            if not lemma:
                run.stats.failed += 1
                run.add_error(record_id, "missing lemma")
                continue

            try:
                rank = int(_clean(row.get("SFI Rank")))
                sfi = float(_clean(row.get("SFI")))
                freq = float(_clean(row.get("Adjusted Frequency per Million (U)")))
            except (TypeError, ValueError) as exc:
                run.stats.failed += 1
                run.add_error(record_id, f"unparsable numeric field: {exc}")
                continue

            warnings: list[str] = []
            if lemma.lower() in seen:
                warnings.append("duplicate_lemma")
            seen.add(lemma.lower())
            if warnings:
                run.stats.warning += 1
                for w in warnings:
                    run.add_warning(record_id, w)

            run.records.append(
                SourceFrequencyRecord(
                    lemma=lemma,
                    rank=rank,
                    sfi=sfi,
                    frequency_per_million=freq,
                    source_record_id=record_id,
                    warnings=warnings,
                )
            )
            run.stats.processed += 1

    return run
