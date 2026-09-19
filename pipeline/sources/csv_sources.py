"""CSV source inspectors: CEFR-J, Octanove, NGSL (Phase 3).

Exact statistics (files are small). Raw files are never modified
(section 46); every anomaly is reported, not fixed in place.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def inspect_cefrj(path: Path) -> dict[str, Any]:
    """CEFR-J Vocabulary Profile 1.5: headword/pos/CEFR (+3 mostly-empty cols)."""
    rows = _read_csv(path)
    pos_counter = Counter(r["pos"] for r in rows)
    cefr_counter = Counter(r["CEFR"] for r in rows)
    headwords = [r["headword"] for r in rows]
    multiword = sum(1 for h in headwords if " " in h)
    slash_variants = sum(1 for h in headwords if "/" in h)
    duplicated_pairs = {
        k: v for k, v in Counter((r["headword"], r["pos"]) for r in rows).items() if v > 1
    }
    core1_filled = sum(1 for r in rows if r.get("CoreInventory 1", "").strip())
    core2_filled = sum(1 for r in rows if r.get("CoreInventory 2", "").strip())
    threshold_filled = sum(1 for r in rows if r.get("Threshold", "").strip())
    return {
        "record_count": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "pos_distribution": dict(pos_counter.most_common()),
        "cefr_distribution": dict(sorted(cefr_counter.items())),
        "multiword_headwords": multiword,
        "slash_variant_headwords": slash_variants,
        "duplicate_headword_pos_pairs": len(duplicated_pairs),
        "duplicate_examples": [
            f"{h} ({p}) x{v}" for (h, p), v in list(duplicated_pairs.items())[:10]
        ],
        "auxiliary_column_fill": {
            "CoreInventory 1": core1_filled,
            "CoreInventory 2": core2_filled,
            "Threshold": threshold_filled,
        },
        "sample_rows": rows[:5],
    }


def inspect_octanove(path: Path) -> dict[str, Any]:
    """Octanove C1/C2 profile: headword/pos/CEFR/notes."""
    rows = _read_csv(path)
    pos_counter = Counter(r["pos"] for r in rows)
    cefr_counter = Counter(r["CEFR"] for r in rows)
    notes_filled = sum(1 for r in rows if r.get("notes", "").strip())
    multiword = sum(1 for r in rows if " " in r["headword"])
    duplicated_pairs = {
        k: v for k, v in Counter((r["headword"], r["pos"]) for r in rows).items() if v > 1
    }
    return {
        "record_count": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "pos_distribution": dict(pos_counter.most_common()),
        "cefr_distribution": dict(sorted(cefr_counter.items())),
        "notes_filled": notes_filled,
        "multiword_headwords": multiword,
        "duplicate_headword_pos_pairs": len(duplicated_pairs),
        "sample_rows": rows[:5],
    }


def inspect_ngsl(path: Path) -> dict[str, Any]:
    """NGSL 1.2 stats: lemma + SFI rank/SFI/adjusted frequency per million."""
    rows = _read_csv(path)
    lemmas = [r["Lemma"] for r in rows]
    ranks: list[int] = []
    freqs: list[float] = []
    unparsable = 0
    for r in rows:
        try:
            ranks.append(int(r["SFI Rank"]))
            freqs.append(float(r["Adjusted Frequency per Million (U)"]))
        except (ValueError, KeyError):
            unparsable += 1
    multiword = sum(1 for h in lemmas if " " in h)
    capitalized = sum(1 for h in lemmas if h[:1].isupper())
    duplicated = {k: v for k, v in Counter(lemmas).items() if v > 1}
    return {
        "record_count": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "rank_range": [min(ranks), max(ranks)] if ranks else None,
        "freq_per_million_range": [min(freqs), max(freqs)] if freqs else None,
        "unparsable_numeric_rows": unparsable,
        "multiword_lemmas": multiword,
        "capitalized_lemmas": capitalized,
        "duplicate_lemmas": len(duplicated),
        "duplicate_examples": [
            f"{k} x{v}" for k, v in list(sorted(duplicated.items()))[:10]
        ],
        "sample_rows": rows[:5],
    }
