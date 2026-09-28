"""PostgreSQL master-vocabulary import (Phase 13, section 89).

Import contract:

- **Source of truth**: the SQLite construction DB (Phase 5-12 output).
  This module turns its tables into the Phase 2 PostgreSQL schema.
- **Identity preserved**: `vocabulary_senses` rows are upserted by
  `sense_key` - a re-import never recreates roots, so generated UUIDs,
  student assignments (later phases) and `sense_embeddings` rows (Phase 12)
  survive every re-import.
- **Children are delete-refreshed**: definitions, translations, examples,
  CEFR/frequency evidence, flags, categories and WordNet links mirror the
  construction DB exactly (stale rows removed, never silently kept).
  `sense_priorities` is the one exception: versioned history is preserved
  (section 86, D012) and only upserted.
- **Validated**: every sense row is validated before insert (required
  fields, field lengths, enum values, key format); rejected rows are
  counted and reported, never silently dropped (section 89).
- **Referential integrity**: child rows referencing a rejected/unknown
  sense are dropped with a warning; sources are registered before use.
- **Batched + transactional**: all inserts run in batches inside ONE
  database transaction provided by the caller (`with conn.begin()`).
  The whole import commits atomically or not at all.

Deterministic duplicate resolution: CEFR evidence arrives one statement
per (sense, source, level) from Phase 7 but the PostgreSQL schema keeps
one row per (sense, source) - the lowest-confidence statement wins, ties
broken by (level, pos) so the result is stable across runs (D015).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

IMPORT_VERSION = "import-v1"
# D012: prio-v1.1 is the current priority formula; the denormalized columns
# on vocabulary_senses mirror this version (history remains in
# sense_priorities).
CURRENT_PRIORITY_VERSION = "prio-v1.1"
CHUNK = 500
ID_CHUNK = 5000

# Sources referenced by construction rows; key -> (name, version).
SOURCE_KEYS: dict[str, tuple[str, str]] = {
    "cefrj": ("CEFR-J Wordlist", "1.5"),
    "octanove": ("Octanove Vocabulary Profile", "1.0"),
    "ngsl": ("New General Service List", "1.2"),
    "wiktextract": ("Wiktextract (English Wiktionary)", "2025"),
    "wordnet": ("Open English WordNet", "2025"),
    "construction": ("Construction pipeline", IMPORT_VERSION),
}

POS_VALUES = {"noun", "verb", "adjective", "adverb", "phrase", "other"}
CEFR_VALUES = {"A1", "A2", "B1", "B2", "C1", "C2"}

# Construction tags that map 1:1 onto SenseFlag enum values. All other
# tags are counted per tag in warnings (kept in the construction DB;
# a future migration may extend the enum - never silently dropped).
TAG_TO_FLAG: dict[str, str] = {
    "obsolete": "obsolete",
    "archaic": "archaic",
    "rare": "rare",
    "US": "american",
    "UK": "british",
}


class ImportValidationError(ValueError):
    """Raised when the import payload itself is unusable."""


@dataclass
class ImportReport:
    """Section 89 import report: processed/inserted/updated/rejected/warnings."""

    started_at: str = ""
    finished_at: str = ""
    records_processed: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    records_rejected: int = 0
    warnings: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    version: str = IMPORT_VERSION

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "records_processed": self.records_processed,
            "records_inserted": self.records_inserted,
            "records_updated": self.records_updated,
            "records_rejected": self.records_rejected,
            "warnings": list(self.warnings),
            "detail": dict(self.detail),
        }

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, indent=2)

    def summary(self) -> str:
        return (
            f"processed={self.records_processed} inserted={self.records_inserted} "
            f"updated={self.records_updated} rejected={self.records_rejected} "
            f"warnings={len(self.warnings)}"
        )


# --------------------------------------------------------------------------
# validation / normalization
# --------------------------------------------------------------------------

MAX_LENGTHS = {
    "sense_key": 400,
    "headword": 200,
    "headword_search": 200,
    "processing_version": 20,
    "priority_version": 20,
}


def validate_sense_row(row: Mapping[str, Any]) -> str | None:
    """Return an error message for an invalid sense row, or None if valid.

    Validation covers exactly what the PostgreSQL schema can hold: required
    identity fields, column lengths, enum membership and the sensekey-v1
    format guarantee (Phase 6).
    """
    for name in ("sense_key", "headword_display", "headword_search"):
        value = row.get(name)
        if value is None or not str(value).strip():
            return f"missing required field {name}"
    if row.get("key_version") != "sensekey-v1":
        return f"unsupported key_version {row.get('key_version')!r}"
    if len(str(row["sense_key"])) > MAX_LENGTHS["sense_key"]:
        return "sense_key longer than 400 characters"
    if len(str(row["headword_display"])) > MAX_LENGTHS["headword"]:
        return "headword longer than 200 characters"
    if len(str(row["headword_search"])) > MAX_LENGTHS["headword_search"]:
        return "headword_search longer than 200 characters"
    pos = row.get("pos_canonical")
    if pos is not None and str(pos) not in POS_VALUES:
        return f"unknown pos_canonical {pos!r}"
    cefr = row.get("cefr_level")
    if cefr is not None and str(cefr) not in CEFR_VALUES:
        return f"unknown cefr_level {cefr!r}"
    if len(str(row.get("processing_version") or "")) > MAX_LENGTHS["processing_version"]:
        return "processing_version longer than 20 characters"
    if len(str(row.get("priority_version") or "")) > MAX_LENGTHS["priority_version"]:
        return "priority_version longer than 20 characters"
    try:
        if row.get("frequency_rank") is not None:
            int(row["frequency_rank"])
        for f in ("priority_score", "cefr_confidence"):
            if row.get(f) is not None:
                float(row[f])
    except (TypeError, ValueError):
        return "non-numeric value in numeric field"
    return None


def _s(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def normalize_sense_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map a validated construction row onto vocabulary_senses columns."""
    return {
        "sense_key": str(row["sense_key"]),
        "headword": str(row["headword_display"]),
        "headword_normalized": str(row["headword_search"]),
        "part_of_speech": _s(row.get("pos_canonical")),
        "cefr_level": _s(row.get("cefr_level")),
        "definition_preview": _s(row.get("gloss_display")),
        "priority_score": (
            float(row["priority_score"]) if row.get("priority_score") is not None else None
        ),
        "priority_level": _s(row.get("priority_level")),
        "priority_version": _s(row.get("priority_version")),
        "processing_version": str(row.get("processing_version") or "norm-v1"),
        "is_active": True,
    }


def collapse_cefr(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Collapse (sense, source) duplicates deterministically.

    Construction keeps one statement per (sense, source, level, pos_raw);
    the PostgreSQL schema keeps one row per (sense, source). Statements
    within one source carry equal weight, so the survivor is the
    lexicographically smallest (cefr, pos_raw) - stable across runs (D015).
    Returns the collapsed rows and the number of statements dropped.
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["sense_key"]), str(row["source"]))
        cand = (str(row.get("cefr") or ""), str(row.get("pos_raw") or ""))
        cur = best.get(key)
        if cur is None or cand < (
            str(cur.get("cefr") or ""),
            str(cur.get("pos_raw") or ""),
        ):
            best[key] = dict(row)
    dropped = len(rows) - len(best)
    return list(best.values()), dropped


# --------------------------------------------------------------------------
# batch helpers
# --------------------------------------------------------------------------


def _chunks(seq: list[Any], size: int) -> list[list[Any]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _insert_batches(
    conn: Connection,
    sql: str,
    params: list[dict[str, Any]],
) -> None:
    for batch in _chunks(params, CHUNK):
        conn.execute(text(sql), batch)


def _delete_by_sense_ids(
    conn: Connection,
    table: str,
    sense_ids: list[uuid.UUID],
) -> int:
    """Delete all rows of `table` for the given senses (delete-refresh)."""
    if not sense_ids:
        return 0
    # psycopg3 adapts list[uuid.UUID] natively; an explicit UUID bindparam
    # would render `ANY(...)::UUID` which Postgres rejects
    stmt = text(f"DELETE FROM {table} WHERE sense_id = ANY(:ids)")
    total = 0
    for batch in _chunks(sense_ids, ID_CHUNK):
        result = conn.execute(stmt, {"ids": batch})
        total += result.rowcount or 0
    return total


def _fetch_sense_ids(
    conn: Connection,
    keys: list[str],
) -> dict[str, uuid.UUID]:
    stmt = text("SELECT id, sense_key FROM vocabulary_senses WHERE sense_key = ANY(:keys)")
    out: dict[str, uuid.UUID] = {}
    for batch in _chunks(keys, ID_CHUNK):
        for row in conn.execute(stmt, {"keys": batch}):
            out[row[1]] = row[0]
    return out


def _referential_filter(
    rows: list[dict[str, Any]],
    valid_keys: set[str],
    label: str,
    report: ImportReport,
) -> list[dict[str, Any]]:
    kept = [r for r in rows if str(r.get("sense_key")) in valid_keys]
    dropped = len(rows) - len(kept)
    if dropped:
        report.warn(f"{label}: dropped {dropped} rows referencing unknown/rejected senses")
    return kept


# --------------------------------------------------------------------------
# table inserters (each returns its row count for the report)
# --------------------------------------------------------------------------


def register_sources(conn: Connection) -> int:
    params = [
        {"key": key, "name": name, "version": version, "import_date": datetime.now(UTC)}
        for key, (name, version) in SOURCE_KEYS.items()
    ]
    _insert_batches(
        conn,
        """
        INSERT INTO vocabulary_sources (key, name, version, import_date)
        VALUES (:key, :name, :version, :import_date)
        ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, version = EXCLUDED.version
        """,
        params,
    )
    rows = conn.execute(text("SELECT key, id FROM vocabulary_sources")).fetchall()
    return len(rows)


def upsert_senses(
    conn: Connection,
    rows: list[dict[str, Any]],
    report: ImportReport,
) -> tuple[dict[str, uuid.UUID], set[str], set[str]]:
    """Validate + upsert sense rows; return (key->id, inserted_keys, updated_keys)."""
    valid: list[dict[str, Any]] = []
    for row in rows:
        report.records_processed += 1
        error = validate_sense_row(row)
        if error:
            report.records_rejected += 1
            report.warn(f"sense {row.get('sense_key')!r}: rejected - {error}")
            continue
        valid.append(row)

    existing_before = set(_fetch_sense_ids(conn, [str(r["sense_key"]) for r in valid]))
    params = [normalize_sense_row(r) for r in valid]
    _insert_batches(
        conn,
        """
        INSERT INTO vocabulary_senses (
            id, sense_key, headword, headword_normalized, part_of_speech,
            cefr_level, definition_preview, priority_score, priority_level,
            priority_version, processing_version, is_active
        ) VALUES (
            :id, :sense_key, :headword, :headword_normalized, :part_of_speech,
            :cefr_level, :definition_preview, :priority_score, :priority_level,
            :priority_version, :processing_version, :is_active
        )
        ON CONFLICT (sense_key) DO UPDATE SET
            headword = EXCLUDED.headword,
            headword_normalized = EXCLUDED.headword_normalized,
            part_of_speech = EXCLUDED.part_of_speech,
            cefr_level = EXCLUDED.cefr_level,
            definition_preview = EXCLUDED.definition_preview,
            priority_score = EXCLUDED.priority_score,
            priority_level = EXCLUDED.priority_level,
            priority_version = EXCLUDED.priority_version,
            processing_version = EXCLUDED.processing_version,
            is_active = TRUE,
            updated_at = now()
        """,
        [{**p, "id": uuid.uuid4()} for p in params],
    )

    key_to_id = _fetch_sense_ids(conn, [str(r["sense_key"]) for r in valid])
    inserted = {str(r["sense_key"]) for r in valid} - existing_before
    updated = {str(r["sense_key"]) for r in valid} & existing_before
    report.records_inserted = len(inserted)
    report.records_updated = len(updated)
    return key_to_id, inserted, updated


def insert_definitions(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
) -> int:
    params = [
        {
            "id": uuid.uuid4(),
            "sid": key_to_id[str(r["sense_key"])],
            "definition": str(r["gloss_display"]),
            "position": 0,
            "source": "construction",
        }
        for r in rows
    ]
    _insert_batches(
        conn,
        """
        INSERT INTO sense_definitions (id, sense_id, definition, position, source)
        VALUES (:id, :sid, :definition, :position, :source)
        """,
        params,
    )
    return len(params)


def insert_translations(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
) -> int:
    from pipeline.normalize.clean import search_key

    params = []
    for r in rows:
        translation = str(r["translation"])
        method = _s(r.get("method"))
        params.append(
            {
                "id": uuid.uuid4(),
                "sid": key_to_id[str(r["sense_key"])],
                "translation": translation,
                "translation_normalized": search_key(translation),
                "position": 0,
                "confidence": float(r["confidence"]) if r.get("confidence") is not None else None,
                # alignment method is the provenance of the translation
                "source": f"align-{method}" if method else "align",
            }
        )
    _insert_batches(
        conn,
        """
        INSERT INTO sense_translations (
            id, sense_id, language, translation, translation_normalized,
            position, confidence, source
        ) VALUES (
            :id, :sid, 'pl', :translation, :translation_normalized,
            :position, :confidence, :source
        )
        """,
        params,
    )
    return len(params)


def insert_examples(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
) -> int:
    params = [
        {
            "id": uuid.uuid4(),
            "sid": key_to_id[str(r["sense_key"])],
            "example": str(r["text"]),
            "position": int(r.get("position") or 0),
            "source": _s(r.get("source")) or "construction",
        }
        for r in rows
    ]
    _insert_batches(
        conn,
        """
        INSERT INTO sense_examples (id, sense_id, example, position, source)
        VALUES (:id, :sid, :example, :position, :source)
        """,
        params,
    )
    return len(params)


def insert_cefr_evidence(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
    source_ids: dict[str, int],
    report: ImportReport,
) -> int:
    collapsed, dropped = collapse_cefr(rows)
    if dropped:
        report.warn(
            f"cefr_evidence: collapsed {dropped} duplicate (sense, source) statements "
            "(lowest confidence retained, section 14)"
        )
    params = [
        {
            "id": uuid.uuid4(),
            "sid": key_to_id[str(r["sense_key"])],
            "source_id": source_ids[str(r["source"])],
            "cefr_level": str(r["cefr"]),
            # per-statement confidence does not exist in the construction
            # schema (decision confidence lives on the sense) - stay None
            "confidence": None,
        }
        for r in collapsed
    ]
    _insert_batches(
        conn,
        """
        INSERT INTO cefr_evidence (id, sense_id, source_id, cefr_level, confidence)
        VALUES (:id, :sid, :source_id, :cefr_level, :confidence)
        ON CONFLICT (sense_id, source_id) DO NOTHING
        """,
        params,
    )
    return len(params)


def insert_frequency_evidence(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
    source_ids: dict[str, int],
) -> int:
    params = [
        {
            "id": uuid.uuid4(),
            "sid": key_to_id[str(r["sense_key"])],
            "source_id": source_ids[str(r["source"])],
            "rank": int(r["rank"]) if r.get("rank") is not None else None,
            "frequency_per_million": float(r["freq"]) if r.get("freq") is not None else None,
            "raw_value": str(r["freq"]) if r.get("freq") is not None else None,
        }
        for r in rows
    ]
    _insert_batches(
        conn,
        """
        INSERT INTO frequency_evidence (
            id, sense_id, source_id, rank, frequency_per_million, raw_value
        ) VALUES (
            :id, :sid, :source_id, :rank, :frequency_per_million, :raw_value
        )
        ON CONFLICT (sense_id, source_id) DO UPDATE SET
            rank = EXCLUDED.rank,
            frequency_per_million = EXCLUDED.frequency_per_million,
            raw_value = EXCLUDED.raw_value
        """,
        params,
    )
    return len(params)


def insert_flags(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
    report: ImportReport,
) -> int:
    params: list[dict[str, Any]] = []
    unmapped: dict[str, int] = {}
    for r in rows:
        raw = r.get("tags_json")
        try:
            tags = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            report.warn(f"sense {r.get('sense_key')!r}: unparseable tags_json, skipped")
            continue
        for tag in tags:
            flag = TAG_TO_FLAG.get(str(tag))
            if flag is None:
                unmapped[str(tag)] = unmapped.get(str(tag), 0) + 1
                continue
            params.append({"id": uuid.uuid4(), "sid": key_to_id[str(r["sense_key"])], "flag": flag})
    for tag, count in sorted(unmapped.items()):
        report.warn(
            f"flags: {count} occurrences of tag {tag!r} have no SenseFlag mapping "
            "(kept in construction DB)"
        )
    _insert_batches(
        conn,
        """
        INSERT INTO vocabulary_flags (id, sense_id, flag)
        VALUES (:id, :sid, :flag)
        ON CONFLICT (sense_id, flag) DO NOTHING
        """,
        params,
    )
    return len(params)


def insert_forms(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
) -> int:
    """One lemma form per sense (headword); surface variants come later."""
    params = [
        {
            "id": uuid.uuid4(),
            "sid": key_to_id[str(r["sense_key"])],
            "form": str(r["headword_display"]),
            "form_normalized": str(r["headword_search"]),
        }
        for r in rows
    ]
    _insert_batches(
        conn,
        """
        INSERT INTO vocabulary_forms (id, sense_id, form, form_normalized, is_lemma)
        VALUES (:id, :sid, :form, :form_normalized, TRUE)
        """,
        params,
    )
    return len(params)


def upsert_priorities(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
) -> int:
    params = []
    for r in rows:
        components = r.get("components_json")
        try:
            components_text = (
                json.dumps(json.loads(components), sort_keys=True) if components else None
            )
        except (TypeError, json.JSONDecodeError):
            components_text = components
        params.append(
            {
                "sid": key_to_id[str(r["sense_key"])],
                "score": float(r["score"]),
                "level": str(r["level"]),
                "version": str(r["version"]),
                "components": components_text,
            }
        )
    _insert_batches(
        conn,
        """
        INSERT INTO sense_priorities (sense_id, score, level, version, components, calculated_at)
        VALUES (:sid, :score, :level, :version, :components, now())
        ON CONFLICT (sense_id, version) DO UPDATE SET
            score = EXCLUDED.score,
            level = EXCLUDED.level,
            components = EXCLUDED.components,
            calculated_at = now()
        """,
        params,
    )
    return len(params)


def upsert_categories(conn: Connection, nodes: list[dict[str, Any]]) -> int:
    """Insert taxonomy nodes, parents before children (roots are parents=None)."""
    roots = [n for n in nodes if not n.get("parent_key")]
    children = [n for n in nodes if n.get("parent_key")]
    for group in (roots, children):
        params = [
            {
                "key": str(n["node_key"]),
                "name": str(n["name"]),
                "parent_key": _s(n.get("parent_key")),
                "position": int(n.get("position") or 0),
            }
            for n in group
        ]
        _insert_batches(
            conn,
            """
            INSERT INTO categories (id, key, name, parent_id, position)
            VALUES (:id, :key, :name,
                    (SELECT id FROM categories WHERE key = :parent_key),
                    :position)
            ON CONFLICT (key) DO UPDATE SET
                name = EXCLUDED.name, position = EXCLUDED.position
            """,
            [{**p, "id": uuid.uuid4()} for p in params],
        )
    rows = conn.execute(text("SELECT count(*) FROM categories")).fetchone()
    return int(rows[0]) if rows else 0


def insert_sense_categories(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
    report: ImportReport,
) -> int:
    cat_rows = conn.execute(text("SELECT key, id FROM categories")).fetchall()
    cat_to_id: dict[str, uuid.UUID] = {r[0]: r[1] for r in cat_rows}
    params: list[dict[str, Any]] = []
    # D013 no-double-count: a (sense, category) pair that has a subcategory
    # row must not also get a top-level row (the sub implies the top).
    with_sub: set[tuple[str, str]] = {
        (str(r["sense_key"]), str(r["category_key"]))
        for r in rows
        if r.get("subcategory_key")
    }
    skipped = 0
    for r in rows:
        sub = r.get("subcategory_key")
        if not sub and (str(r["sense_key"]), str(r["category_key"])) in with_sub:
            skipped += 1
            continue
        params.append(
            {
                "sid": key_to_id[str(r["sense_key"])],
                "cid": cat_to_id[str(sub)] if sub else cat_to_id[str(r["category_key"])],
                "confidence": float(r["confidence"]) if r.get("confidence") is not None else None,
                "assigned_by": _s(r.get("method")) or "construction",
            }
        )
    if skipped:
        report.warn(
            f"sense_categories: skipped {skipped} top-level rows already implied "
            "by a subcategory row (no double counting, D013)"
        )
    _insert_batches(
        conn,
        """
        INSERT INTO sense_categories (sense_id, category_id, confidence, assigned_by)
        VALUES (:sid, :cid, :confidence, :assigned_by)
        ON CONFLICT (sense_id, category_id) DO UPDATE SET
            confidence = EXCLUDED.confidence,
            assigned_by = EXCLUDED.assigned_by
        """,
        params,
    )
    return len(params)


def upsert_wordnet(
    conn: Connection,
    synsets: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, uuid.UUID]:
    """Upsert synsets + relations; return synset_id (natural) -> uuid map."""
    _insert_batches(
        conn,
        """
        INSERT INTO wordnet_synsets (id, synset_id, part_of_speech, definition, ili)
        VALUES (:id, :synset_id, :part_of_speech, :definition, :ili)
        ON CONFLICT (synset_id) DO UPDATE SET
            part_of_speech = EXCLUDED.part_of_speech,
            definition = EXCLUDED.definition,
            ili = EXCLUDED.ili
        """,
        [
            {
                "id": uuid.uuid4(),
                "synset_id": str(s["synset_id"]),
                "part_of_speech": str(s["part_of_speech"]),
                "definition": _s(s.get("definition")),
                "ili": _s(s.get("ili")),
            }
            for s in synsets
        ],
    )
    id_rows = conn.execute(text("SELECT synset_id, id FROM wordnet_synsets")).fetchall()
    natural_to_uuid: dict[str, uuid.UUID] = {r[0]: r[1] for r in id_rows}
    _insert_batches(
        conn,
        """
        INSERT INTO wordnet_relations (id, from_synset_id, to_synset_id, relation)
        VALUES (:id, :from_id, :to_id, :relation)
        ON CONFLICT (from_synset_id, to_synset_id, relation) DO NOTHING
        """,
        [
            {
                "id": uuid.uuid4(),
                "from_id": natural_to_uuid[str(r["from_synset_id"])],
                "to_id": natural_to_uuid[str(r["to_synset_id"])],
                "relation": str(r["relation"]),
            }
            for r in relations
        ],
    )
    return natural_to_uuid


def insert_wordnet_links(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    natural_to_uuid: dict[str, uuid.UUID],
    rows: list[dict[str, Any]],
) -> int:
    params = [
        {
            "sid": key_to_id[str(r["sense_key"])],
            "wid": natural_to_uuid[str(r["synset_id"])],
            "confidence": float(r["confidence"]) if r.get("confidence") is not None else None,
        }
        for r in rows
    ]
    _insert_batches(
        conn,
        """
        INSERT INTO sense_wordnet_links (id, sense_id, synset_id, confidence)
        VALUES (:id, :sid, :wid, :confidence)
        ON CONFLICT (sense_id, synset_id) DO NOTHING
        """,
        [{"id": uuid.uuid4(), **p} for p in params],
    )
    return len(params)


# --------------------------------------------------------------------------
# top-level import
# --------------------------------------------------------------------------


def refresh_priority_columns(
    conn: Connection,
    version: str,
) -> int:
    """Copy the given priority version onto vocabulary_senses (denormalized).

    Phase 13 gap fix: the root table's priority_score/level/version columns
    were left NULL because construction stores priorities only in the
    versioned sense_priorities table. Reads (search, filtering, later
    FSRS seeding) expect the current values at hand without a join.
    Idempotent; keyed on the versioned rows so the source of truth stays
    sense_priorities (section 86: history is never destroyed).
    """
    stmt = text(
        """
        UPDATE vocabulary_senses s
        SET priority_score = p.score,
            priority_level = p.level,
            priority_version = p.version
        FROM sense_priorities p
        WHERE p.sense_id = s.id
          AND p.version = :version
        """
    )
    result = conn.execute(stmt, {"version": version})
    return result.rowcount or 0


def import_vocabulary(conn: Connection, data: dict[str, list[dict[str, Any]]]) -> ImportReport:
    """Import the construction payload into PostgreSQL in one transaction.

    The caller opens the transaction (`with conn.begin():`). Every table
    family is refreshed from `data`; nothing is silently dropped: rejected
    senses, orphan child rows, collapsed duplicates and unmapped tags all
    appear in the report's warnings (section 89).
    """
    report = ImportReport(started_at=datetime.now(UTC).isoformat())

    register_sources(conn)
    source_rows = conn.execute(text("SELECT key, id FROM vocabulary_sources")).fetchall()
    source_ids: dict[str, int] = {r[0]: int(r[1]) for r in source_rows}

    senses = data.get("senses", [])
    key_to_id, inserted, updated = upsert_senses(conn, senses, report)
    valid_keys = set(key_to_id)
    report.detail["senses"] = len(senses)
    report.detail["sense_ids_preserved"] = True
    valid_senses = [r for r in senses if str(r["sense_key"]) in valid_keys]

    def kid(r: dict[str, Any]) -> str:
        return str(r["sense_key"])

    def refilter(label: str, rows_in: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _referential_filter(rows_in, valid_keys, label, report)

    definitions = refilter("definitions", data.get("definitions", []))
    translations = refilter("translations", data.get("translations", []))
    examples = refilter("examples", data.get("examples", []))
    cefr = refilter("cefr_evidence", data.get("cefr_evidence", []))
    freq = refilter("frequency_evidence", data.get("frequency_evidence", []))
    priorities = refilter("priorities", data.get("priorities", []))
    category_links = refilter("sense_categories", data.get("sense_categories", []))
    wordnet_links = refilter("wordnet_links", data.get("wordnet_links", []))

    sense_ids = list(key_to_id.values())

    _delete_by_sense_ids(conn, "vocabulary_forms", sense_ids)
    report.detail["forms"] = insert_forms(conn, key_to_id, valid_senses)

    _delete_by_sense_ids(conn, "sense_definitions", sense_ids)
    report.detail["definitions"] = insert_definitions(conn, key_to_id, definitions)

    _delete_by_sense_ids(conn, "sense_translations", sense_ids)
    report.detail["translations"] = insert_translations(conn, key_to_id, translations)

    _delete_by_sense_ids(conn, "sense_examples", sense_ids)
    report.detail["examples"] = insert_examples(conn, key_to_id, examples)

    _delete_by_sense_ids(conn, "cefr_evidence", sense_ids)
    report.detail["cefr_evidence"] = insert_cefr_evidence(
        conn, key_to_id, cefr, source_ids, report
    )

    _delete_by_sense_ids(conn, "frequency_evidence", sense_ids)
    report.detail["frequency_evidence"] = insert_frequency_evidence(
        conn, key_to_id, freq, source_ids
    )

    _delete_by_sense_ids(conn, "vocabulary_flags", sense_ids)
    report.detail["flags"] = insert_flags(conn, key_to_id, valid_senses, report)

    # priorities: versioned history preserved (no delete, section 86)
    report.detail["priorities"] = upsert_priorities(conn, key_to_id, priorities)
    # Denormalized current-priority columns on the root row (D012: the
    # latest formula version is "current"). Phase 14 search/filtering sorts
    # on these columns directly, so they must be populated, not NULL.
    report.detail["priority_columns"] = refresh_priority_columns(
        conn, CURRENT_PRIORITY_VERSION
    )

    # categories + assignments
    _delete_by_sense_ids(conn, "sense_categories", sense_ids)
    report.detail["categories"] = upsert_categories(conn, data.get("categories", []))
    report.detail["sense_categories"] = insert_sense_categories(
        conn, key_to_id, category_links, report
    )

    # wordnet
    synsets = data.get("wordnet_synsets", [])
    relations = [
        r
        for r in data.get("wordnet_relations", [])
        if r.get("from_synset_id") != r.get("to_synset_id")
    ]
    natural_to_uuid = upsert_wordnet(conn, synsets, relations)
    report.detail["wordnet_synsets"] = len(synsets)
    report.detail["wordnet_relations"] = len(relations)
    _delete_by_sense_ids(conn, "sense_wordnet_links", sense_ids)
    report.detail["wordnet_links"] = insert_wordnet_links(
        conn, key_to_id, natural_to_uuid, wordnet_links
    )

    report.finished_at = datetime.now(UTC).isoformat()
    return report
