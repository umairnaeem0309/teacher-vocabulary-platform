"""Octanove C1/C2 Vocabulary Profile 1.0 adapter (Phase 4).

Same evidence shape as CEFR-J but for C1/C2. Known data quirks (from the
Phase 3 inventory) handled explicitly:

- empty `pos` values are kept with a warning (normalization may still match
  them by headword);
- unknown POS strings (`vern`, empty) are preserved verbatim in `pos_raw`;
- duplicate (headword, POS) rows are kept as evidence with a warning.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.records import AdapterRun, _clean, _normalize_ws

SOURCE_KEY = "octanove"
VALID_CEFR = {"C1", "C2"}  # profile covers only advanced levels


@dataclass
class SourceOctanoveRecord:
    """One CEFR statement from the Octanove C1/C2 profile."""

    headword: str
    pos_raw: str
    cefr: str
    notes: str
    source: str = SOURCE_KEY
    source_record_id: str = ""
    warnings: list[str] = field(default_factory=list)


def adapt_octanove(path: Path) -> AdapterRun:
    """Parse the Octanove CSV into normalized records with exact statistics."""
    run = AdapterRun(source=SOURCE_KEY)
    seen: set[tuple[str, str]] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_number, row in enumerate(reader, start=2):
            run.stats.read += 1
            record_id = f"octanove:row:{row_number}"

            headword = _normalize_ws(_clean(row.get("headword")))
            pos_raw = _normalize_ws(_clean(row.get("pos")))
            cefr = _clean(row.get("CEFR")).upper()
            notes = _clean(row.get("notes"))

            if not headword or not cefr:
                run.stats.failed += 1
                run.add_error(record_id, "missing headword or CEFR")
                continue
            if cefr not in VALID_CEFR:
                run.stats.failed += 1
                run.add_error(record_id, f"unexpected CEFR value for this source: {cefr!r}")
                continue

            warnings: list[str] = []
            if not pos_raw:
                warnings.append("missing_pos")
            key = (headword.lower(), pos_raw.lower())
            if key in seen:
                warnings.append("duplicate_headword_pos")
            seen.add(key)

            if warnings:
                run.stats.warning += 1
                for w in warnings:
                    run.add_warning(record_id, w)

            run.records.append(
                SourceOctanoveRecord(
                    headword=headword,
                    pos_raw=pos_raw,
                    cefr=cefr,
                    notes=notes,
                    source_record_id=record_id,
                    warnings=warnings,
                )
            )
            run.stats.processed += 1

    return run
