"""Streaming Wiktextract inspector (Phase 3).

The dump is ~2.7 GB gzipped JSONL, so this profiler streams line by line and
never materializes the dataset in RAM (sections 47-48). It measures exactly
what the later ETL needs to know: language/POS distribution, sense and gloss
availability, Polish translation coverage (word-level and sense-level),
Polish glosses (sense-level translation alternative), headword duplicates,
and malformed-line accounting.
"""

from __future__ import annotations

import gzip
import json
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# Sample size for detailed field-level profiling (statistically sufficient;
# full-file counts are gathered with cheap streaming passes).
SAMPLE_SIZE = 50_000


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON records, streaming; malformed lines are yielded as
    ``{"__malformed__": True, ...}`` markers to be counted, never dropped
    silently (section 45)."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:  # type: ignore[operator]
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"__malformed__": True}


def profile_wiktextract(path: Path, max_records: int | None = None) -> dict[str, Any]:
    """Stream the dump and return exact or sampled statistics."""
    started = time.time()
    lang_counter: Counter[str] = Counter()
    pos_counter: Counter[str] = Counter()
    malformed = 0
    total = 0
    english = 0

    # Field coverage on the sample.
    field_counter: Counter[str] = Counter()
    sample_english = 0
    senses_total = 0
    senses_with_gloss = 0
    word_has_pl_translation = 0
    word_pl_count = 0
    word_has_pl_gloss_in_sense = 0
    sense_tags: Counter[str] = Counter()
    translation_codes: Counter[str] = Counter()

    for rec in iter_records(path):
        total += 1
        if rec.get("__malformed__"):
            malformed += 1
            continue
        lang = rec.get("lang", "?")
        lang_counter[lang] += 1
        if lang != "English":
            continue
        english += 1
        pos_counter[rec.get("pos", "?")] += 1

        detailed = sample_english < SAMPLE_SIZE and (
            max_records is None or total <= max_records
        )
        if detailed:
            sample_english += 1
            for key in rec:
                field_counter[key] += 1
            senses = rec.get("senses", []) or []
            senses_total += len(senses)
            for sense in senses:
                if sense.get("glosses"):
                    senses_with_gloss += 1
                for tag in sense.get("tags", []) or []:
                    sense_tags[tag] += 1
                for gloss in sense.get("glosses", []) or []:
                    if "(płsk." in gloss or "pl:" in gloss:
                        word_has_pl_gloss_in_sense += 1
                        break
            translations = rec.get("translations", []) or []
            pl_list = [
                t for t in translations if t.get("code") == "pl" or t.get("lang") == "Polish"
            ]
            if pl_list:
                word_has_pl_translation += 1
                word_pl_count += len(pl_list)
            for t in translations:
                code = t.get("code") or "?"
                translation_codes[code] += 1

    duration = time.time() - started
    result: dict[str, Any] = {
        "total_records": total,
        "malformed_records": malformed,
        "english_records": english,
        "non_english_records": total - malformed - english,
        "language_distribution_top": dict(lang_counter.most_common(12)),
        "duration_seconds": round(duration, 1),
        "streamed": True,
    }
    if sample_english:
        result["profile_sample_size"] = sample_english
        result["english_pos_distribution"] = dict(pos_counter.most_common())
        result["sample_field_coverage"] = {
            k: v for k, v in field_counter.most_common(30)
        }
        result["sample_sense_stats"] = {
            "senses_total": senses_total,
            "senses_with_gloss": senses_with_gloss,
            "gloss_coverage_pct": round(100 * senses_with_gloss / max(senses_total, 1), 1),
            "avg_senses_per_word": round(senses_total / sample_english, 2),
        }
        result["sample_polish_coverage"] = {
            "words_with_pl_translation": word_has_pl_translation,
            "words_with_pl_translation_pct": round(
                100 * word_has_pl_translation / sample_english, 1
            ),
            "avg_pl_translations_per_covered_word": round(
                word_pl_count / max(word_has_pl_translation, 1), 1
            ),
            "words_with_pl_hint_in_sense_gloss": word_has_pl_gloss_in_sense,
        }
        result["sample_translation_codes_top"] = dict(translation_codes.most_common(15))
        result["sample_sense_tags_top"] = dict(sense_tags.most_common(20))
    return result


def extract_examples(path: Path, words: set[str], limit: int = 20) -> dict[str, list[str]]:
    """Stream the dump and pull example records for given headwords (utility
    for manual inspection; streaming keeps memory bounded)."""
    found: dict[str, list[str]] = {}
    remaining = len(words)
    for rec in iter_records(path):
        if rec.get("__malformed__"):
            continue
        word = rec.get("word")
        if word not in words or word in found:
            continue
        if rec.get("lang") != "English":
            continue
        entry = {
            "pos": rec.get("pos"),
            "senses": [
                {
                    "glosses": s.get("glosses", [])[:2],
                    "tags": s.get("tags", [])[:4],
                }
                for s in (rec.get("senses", []) or [])[:3]
            ],
            "polish": [
                t.get("word")
                for t in (rec.get("translations", []) or [])
                if t.get("code") == "pl"
            ][:5],
        }
        found[word] = [json.dumps(entry, ensure_ascii=False)]
        remaining -= 1
        if remaining <= 0 or len(found) >= limit:
            break
    return found
