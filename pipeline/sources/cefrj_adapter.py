"""CEFR-J Vocabulary Profile 1.5 adapter (Phase 4).

Reads `data/raw/cefrj-vocabulary-profile-1.5.csv` and yields
``SourceCefrRecord`` entries with provenance. Validation policy:

- rows with unparseable CEFR are **failed** (counted, sampled);
- slash-variant headwords (`a.m./A.M./am/AM`) are kept as-is and marked with
  a warning — splitting is normalization logic (Phase 5), not adapter logic;
- duplicate (headword, POS) rows are kept as evidence with a warning.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.records import AdapterRun, _clean, _normalize_ws

SOURCE_KEY = "cefrj"
VALID_CEFR = {"A1", "A2", "B1", "B2", "C1", "C2"}


@dataclass
class SourceCefrRecord:
    """One CEFR statement from CEFR-J."""

    headword: str
    pos_raw: str
    cefr: str
    source: str = SOURCE_KEY
    source_record_id: str = ""
    warnings: list[str] = field(default_factory=list)


def adapt_cefrj(path: Path) -> AdapterRun:
    """Parse the CEFR-J CSV into normalized records with exact statistics."""
    run = AdapterRun(source=SOURCE_KEY)
    seen: set[tuple[str, str]] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_number, row in enumerate(reader, start=2):  # header is line 1
            run.stats.read += 1
            record_id = f"cefrj:row:{row_number}"

            headword = _normalize_ws(_clean(row.get("headword")))
            pos_raw = _normalize_ws(_clean(row.get("pos")))
            cefr = _clean(row.get("CEFR")).upper()

            if not headword or not cefr:
                run.stats.failed += 1
                run.add_error(record_id, "missing headword or CEFR")
                continue
            if cefr not in VALID_CEFR:
                run.stats.failed += 1
                run.add_error(record_id, f"invalid CEFR value: {cefr!r}")
                continue

            warnings: list[str] = []
            if "/" in headword:
                warnings.append("slash_variant_headword")
            key = (headword.lower(), pos_raw.lower())
            if key in seen:
                warnings.append("duplicate_headword_pos")
            seen.add(key)

            if warnings:
                run.stats.warning += 1
                for w in warnings:
                    run.add_warning(record_id, w)

            run.records.append(
                SourceCefrRecord(
                    headword=headword,
                    pos_raw=pos_raw,
                    cefr=cefr,
                    source_record_id=record_id,
                    warnings=warnings,
                )
            )
            run.stats.processed += 1

    return run
