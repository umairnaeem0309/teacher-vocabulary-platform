"""Wiktextract adapter (Phase 4): streaming extraction of English entries.

Converts raw dump lines into ``SourceLexicalRecord`` entries. Policy:

- streams line by line (sections 47-48); never materializes the dump;
- non-English records are **skipped** (expected, counted);
- malformed JSON lines are **failed** (counted, sampled) — never silent.
  Every line is parsed before any filtering, precisely so a corrupt line
  cannot hide inside a skipped one (a substring pre-filter on the language
  field made corrupt, non-English lines silently disappear — caught by
  `test_source_adapters`);
- English records lacking any glossed sense are **skipped** as unusable for
  sense extraction (counted, sampled) but reported, not hidden;
- an optional **target vocabulary** (`target_keys`) restricts the run to
  the words the platform actually teaches. The dump holds ~1M English
  entries; the supplied CEFR-J/NGSL/Octanove profiles cover ~8.7k. Without
  this filter a faithful full-dump run is neither affordable (embeddings)
  nor useful (proper nouns, single letters, non-words). Words outside the
  target set are skipped non-destructively (counted, never deleted from
  the source);
- Polish translations are captured at word level exactly as the dump stores
  them; sense alignment is Phase 5's documented heuristic;
- sense tags pass through for flag extraction (Phase 8+) and priority.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.normalize.clean import search_key
from pipeline.records import AdapterRun, _clean

SOURCE_KEY = "wiktextract"
MAX_ERRORS_KEPT = 100


def _usable_headword(word: str) -> bool:
    """Is this entry title usable as a vocabulary headword?

    Wiktionary also carries apostrophe/hyphen forms (`'at`, `-ability`) and
    ampersand forms (`A. & M.`). Their search keys collide with the plain
    word (`at`, `ability`, `a m`), so a key-only match pulls them in as
    headwords that read as junk in the table and cannot be typed exactly
    (`websearch_to_tsquery('simple', "'at")` never matches the row). Both
    classes are rejected at the source rather than cleaned up downstream.
    """
    if not word:
        return False
    first = word[0]
    return first.isalnum() and "&" not in word


@dataclass
class SourceSense:
    """One raw sense from a Wiktextract entry."""

    gloss: str
    tags: list[str]
    examples: list[str]
    # Raw sense id if the dump provides one (stable per dump version).
    sense_id: str | None = None


@dataclass
class SourceLexicalRecord:
    """One English entry from Wiktextract, normalized shape."""

    word: str
    pos_raw: str
    senses: list[SourceSense]
    polish_translations: list[str]
    source: str = SOURCE_KEY
    source_record_id: str = ""
    categories: list[str] = field(default_factory=list)


def _iter_lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (line_number, line) streaming; transparent for .gz."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:  # type: ignore[operator]
        yield from enumerate(f, start=1)


def _extract_senses(payload: dict[str, Any]) -> list[SourceSense]:
    senses: list[SourceSense] = []
    for sense in payload.get("senses") or []:
        glosses = [g for g in (sense.get("glosses") or []) if _clean(g)]
        if not glosses:
            continue
        examples = []
        for ex in sense.get("examples") or []:
            text = _clean(ex.get("text", "")) if isinstance(ex, dict) else _clean(str(ex))
            if text:
                examples.append(text)
        senses.append(
            SourceSense(
                gloss=_clean(glosses[0]),
                tags=[_clean(t) for t in sense.get("tags") or [] if _clean(t)],
                examples=examples[:3],
                sense_id=sense.get("id") or None,
            )
        )
    return senses


def _extract_polish(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for t in payload.get("translations") or []:
        if _clean(t.get("code")) == "pl":
            word = _clean(t.get("word"))
            if word:
                out.append(word)
    return out


def adapt_wiktextract(
    path: Path,
    max_records: int | None = None,
    target_keys: set[str] | None = None,
) -> AdapterRun:
    """Stream the dump and produce normalized English lexical records.

    ``target_keys``: normalized ``search_key`` values of the words the
    platform teaches (the supplied CEFR/NGSL profiles). When given, English
    entries outside the set are skipped before their senses are extracted,
    so memory stays proportional to the target vocabulary rather than the
    ~1M English entries in the dump.
    """
    run = AdapterRun(source=SOURCE_KEY)

    for line_number, line in _iter_lines(path):
        if max_records is not None and run.stats.read >= max_records:
            break
        run.stats.read += 1
        record_id = f"wiktextract:line:{line_number}"

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            run.stats.failed += 1
            run.add_error(record_id, f"unparsable JSON: {exc.msg}")
            continue

        if _clean(payload.get("lang")) != "English":
            run.stats.skipped += 1
            continue

        word = _clean(payload.get("word"))
        if not _usable_headword(word):
            run.stats.skipped += 1
            continue
        if target_keys is not None and search_key(word) not in target_keys:
            run.stats.skipped += 1
            continue

        senses = _extract_senses(payload)
        if not word or not senses:
            run.stats.skipped += 1
            run.add_warning(record_id, "english_entry_without_usable_senses")
            continue

        run.records.append(
            SourceLexicalRecord(
                word=word,
                pos_raw=_clean(payload.get("pos")),
                senses=senses,
                polish_translations=_extract_polish(payload),
                categories=[_clean(c) for c in payload.get("categories") or [] if _clean(c)],
                source_record_id=record_id,
            )
        )
        run.stats.processed += 1

    return run
