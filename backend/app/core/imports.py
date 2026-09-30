"""Import service (Phase 22, sections 38/99): validated vocabulary import.

Safeguards (§99 "never accidentally overwrite production vocabulary"):

1. **Two steps.** POST /imports/vocabulary/preview parses and fully
   validates the file and returns per-row statuses — no writes. POST
   /imports/vocabulary re-validates and commits inside one transaction.
2. **Insert-only.** An import may INSERT new senses and may APPEND
   translations/examples/flags to existing senses; it never UPDATEs or
   DELETEs master-vocabulary rows. A row carrying master fields that
   differ from the stored sense (POS/CEFR/definition) is reported as a
   conflict and skipped — imports never overwrite.
3. **Identity is sense_key round-trip (D008).** A row carrying the
   exact ``sense_key`` from a previous export attaches to that sense.
   A row without a key derives one with the Phase 6 algorithm; a
   derived key that hits an existing sense with different master
   fields is a conflict (never a silent merge), and a derived key
   colliding with a *different existing meaning* is impossible by
   construction (the key digests the meaning).
4. **Full validation before any write.** Row-level errors (missing
   headword, bad POS/CEFR, unknown flag, unknown sense_key, too-long
   fields) fail the request with 422 and a per-row report; the commit
   endpoint refuses to run when any row has structural errors.

File formats: CSV (RFC-4180, UTF-8 with BOM tolerated), XLSX (first
worksheet, header row), JSON (array of row objects). Headers are the
stable export schema (app.core.exports.EXPORT_COLUMNS); ``headword``
is required per row. Empty cells mean "nothing to add", never "clear".
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.core.errors import ValidationError
from app.core.exports import EXPORT_COLUMNS, MULTI_SEP

IMPORT_VERSION = "import-v1"

#: Cap on uploaded rows (a teacher lesson list, not a corpus rebuild;
#: corpus-scale vocabulary arrives through the Phase 13 pipeline).
MAX_IMPORT_ROWS = 10_000

MAX_FIELD_LENGTHS = {
    "headword": 200,
    "definition": 10_000,
    "translations_pl": 4_000,
    "examples": 10_000,
    "flags": 500,
}

VALID_POS = {"noun", "verb", "adjective", "adverb", "phrase", "other"}
VALID_CEFR = {"A1", "A2", "B1", "B2", "C1", "C2"}

VALID_FLAGS = {
    "rare",
    "archaic",
    "obsolete",
    "technical",
    "specialized",
    "proper_name",
    "offensive",
    "american",
    "british",
}


@dataclass
class ImportRow:
    """One parsed input row with its structural errors/warnings."""

    line: int
    data: dict[str, str]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Parsing (bytes -> raw row dicts)
# --------------------------------------------------------------------------


def parse_file(content: bytes, format: str) -> list[dict[str, str]]:
    """Parse an uploaded file into raw row dicts (no validation yet).

    Raises ValidationError with a user-actionable message on unreadable
    input (wrong format, bad headers, binary garbage).
    """
    fmt = (format or "").strip().lower()
    if fmt == "json":
        return _parse_json(content)
    if fmt == "xlsx":
        return _parse_xlsx(content)
    if fmt == "csv":
        return _parse_csv(content)
    raise ValidationError("Unsupported import format; use csv, xlsx or json.")


def _check_headers(header: list[str]) -> None:
    missing_required = ["headword"] if "headword" not in header else []
    unknown = [c for c in header if c and c not in EXPORT_COLUMNS]
    if missing_required or unknown:
        problems = []
        if missing_required:
            problems.append("missing required column(s): " + ", ".join(missing_required))
        if unknown:
            problems.append("unknown column(s): " + ", ".join(unknown))
        raise ValidationError(
            "Invalid import headers ("
            + "; ".join(problems)
            + "). Expected columns: "
            + ", ".join(EXPORT_COLUMNS)
            + "."
        )


def _parse_csv(content: bytes) -> list[dict[str, str]]:
    try:
        text_in = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("CSV must be UTF-8 encoded.") from exc
    reader = csv.DictReader(io.StringIO(text_in))
    if reader.fieldnames is None:
        raise ValidationError("CSV file is empty.")
    _check_headers([f.strip() for f in reader.fieldnames])
    rows: list[dict[str, str]] = []
    for raw in reader:
        rows.append(
            {
                (k or "").strip(): (v or "").strip()
                for k, v in raw.items()
                if k is not None
            }
        )
        if len(rows) > MAX_IMPORT_ROWS:
            raise ValidationError(f"Too many rows (limit {MAX_IMPORT_ROWS}).")
    return rows


def _parse_xlsx(content: bytes) -> list[dict[str, str]]:
    from openpyxl import load_workbook  # noqa: PLC0415

    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many types
        raise ValidationError("File is not a readable XLSX workbook.") from exc
    ws = wb.worksheets[0]
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    try:
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c).strip() for c in row]
            if header is None:
                if not any(cells):
                    continue
                header = cells
                _check_headers(header)
                continue
            if not any(cells):
                continue
            rows.append(
                {
                    header[i]: cells[i] if i < len(cells) else ""
                    for i in range(len(header))
                    if header[i]
                }
            )
            if len(rows) > MAX_IMPORT_ROWS:
                raise ValidationError(
                    f"Too many rows (limit {MAX_IMPORT_ROWS})."
                )
    finally:
        wb.close()
    if header is None:
        raise ValidationError("XLSX first worksheet has no header row.")
    return rows


def _parse_json(content: bytes) -> list[dict[str, str]]:
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("File is not valid JSON.") from exc
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        raise ValidationError("JSON import must be an array of row objects.")
    if len(payload) > MAX_IMPORT_ROWS:
        raise ValidationError(f"Too many rows (limit {MAX_IMPORT_ROWS}).")
    if payload:
        keys = sorted({str(k) for r in payload for k in r})
        _check_headers(keys)
    return [
        {str(k): ("" if v is None else str(v).strip()) for k, v in r.items()}
        for r in payload
    ]


# --------------------------------------------------------------------------
# Validation (no DB access)
# --------------------------------------------------------------------------


def validate_rows(rows: list[dict[str, str]]) -> list[ImportRow]:
    """Row-level structural validation."""
    out: list[ImportRow] = []
    for i, raw in enumerate(rows, start=1):
        row = ImportRow(line=i, data=raw)
        if not raw.get("headword"):
            row.errors.append("headword is required")
        for col, limit in MAX_FIELD_LENGTHS.items():
            if len(raw.get(col, "")) > limit:
                row.errors.append(f"{col} exceeds {limit} characters")
        pos = raw.get("part_of_speech", "").lower()
        if pos and pos not in VALID_POS:
            row.errors.append(
                "part_of_speech must be one of " + ", ".join(sorted(VALID_POS))
            )
        cefr = raw.get("cefr_level", "").upper()
        if cefr and cefr not in VALID_CEFR:
            row.errors.append("cefr_level must be one of " + ", ".join(sorted(VALID_CEFR)))
        for flag in _split_multi(raw.get("flags", "")):
            if flag.lower() not in VALID_FLAGS:
                row.errors.append(f"unknown flag: {flag}")
        out.append(row)
    return out


def _split_multi(value: str) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(MULTI_SEP.strip()) if p.strip()]


# --------------------------------------------------------------------------
# Classification against the master database (read-only)
# --------------------------------------------------------------------------


def _sense_key_for(headword: str, pos: str, definition: str) -> str:
    """Derive the D008 identity key with the Phase 6 algorithm.

    Verified against the live database: for 300/300 sampled senses,
    make_sense_key(search_key(headword), canonical_pos(pos),
    search_key(clean_gloss(definition_preview))) reproduces the stored
    sense_key exactly.
    """
    from pipeline.identity.identity import make_sense_key  # noqa: PLC0415
    from pipeline.normalize.clean import clean_gloss, search_key  # noqa: PLC0415
    from pipeline.normalize.pos import canonical_pos  # noqa: PLC0415

    return make_sense_key(
        search_key(headword),
        canonical_pos(pos or "other"),
        search_key(clean_gloss(definition)),
    )


def _load_by_key(conn: Any, key: str) -> dict[str, Any] | None:
    return (
        conn.execute(
            text(
                "SELECT id, sense_key, headword, "
                "part_of_speech::text AS pos, cefr_level::text AS cefr, "
                "definition_preview "
                "FROM vocabulary_senses WHERE sense_key = :k"
            ),
            {"k": key},
        )
        .mappings()
        .first()
    )


def _classify(conn: Any, data: dict[str, str]) -> dict[str, Any]:
    """Classify one structurally-valid row.

    Returns {status, detail, sense_id?} where status is one of:
    new | existing_match | conflict | error.
    """
    provided_key = data.get("sense_key", "").strip()
    hit = _load_by_key(conn, provided_key) if provided_key else None
    if provided_key and hit is None:
        return {
            "status": "error",
            "detail": "sense_key does not exist (paste it from a previous export)",
        }
    if hit is None:
        derived = _sense_key_for(
            data["headword"],
            data.get("part_of_speech", ""),
            data.get("definition", ""),
        )
        hit = _load_by_key(conn, derived)
        if hit is None:
            return {"status": "new", "detail": f"derived key {derived}"}

    same_master = (
        (hit["pos"] or "") == (data.get("part_of_speech", "").lower() or "")
        and (hit["cefr"] or "") == (data.get("cefr_level", "").upper() or "")
        and (hit["definition_preview"] or "") == data.get("definition", "")
    )
    if same_master:
        return {
            "status": "existing_match",
            "detail": f"attaches to existing sense {hit['sense_key']}",
            "sense_id": str(hit["id"]),
        }
    return {
        "status": "conflict",
        "detail": (
            f"existing sense {hit['sense_key']} has different master fields; "
            "imports never overwrite"
        ),
        "sense_id": str(hit["id"]),
    }


# --------------------------------------------------------------------------
# Preview and commit
# --------------------------------------------------------------------------


def preview_import(conn: Any, content: bytes, format: str) -> dict[str, Any]:
    """Parse + validate + classify against the DB; write nothing."""
    rows = validate_rows(parse_file(content, format))
    report_rows: list[dict[str, Any]] = []
    counts = {"new": 0, "existing_match": 0, "conflict": 0, "error": 0}
    for row in rows:
        entry: dict[str, Any] = {
            "line": row.line,
            "headword": row.data.get("headword", ""),
            "status": "ok",
            "errors": row.errors,
            "warnings": row.warnings,
            "detail": "",
        }
        if row.errors:
            entry["status"] = "error"
            counts["error"] += 1
        else:
            classification = _classify(conn, row.data)
            entry["status"] = classification["status"]
            entry["detail"] = classification.get("detail", "")
            counts[classification["status"]] += 1
        report_rows.append(entry)
    return {
        "total_rows": len(rows),
        "counts": counts,
        "rows": report_rows,
        "would_insert_senses": counts["new"],
        "would_skip": counts["error"] + counts["conflict"],
        "version": IMPORT_VERSION,
    }


def commit_import(conn: Any, content: bytes, format: str) -> dict[str, Any]:
    """Re-validate and insert inside the caller's transaction.

    Structurally-invalid rows abort the whole import (422 from the
    endpoint). Conflicting rows (existing sense, different master
    fields) are skipped and reported — never overwritten.
    """
    rows = validate_rows(parse_file(content, format))
    errors = [r for r in rows if r.errors]
    if errors:
        raise ValidationError(
            f"{len(errors)} row(s) failed validation; nothing was imported."
        )

    inserted = 0
    merged_senses = 0
    added_translations = 0
    added_examples = 0
    added_flags = 0
    skipped: list[dict[str, Any]] = []

    for row in rows:
        classification = _classify(conn, row.data)
        if classification["status"] in ("conflict", "error"):
            skipped.append({"line": row.line, "detail": classification["detail"]})
            continue

        if classification["status"] == "new":
            sense_id = _insert_sense(conn, row.data)
            inserted += 1
        else:
            sense_id = uuid.UUID(classification["sense_id"])
            merged_senses += 1

        added_translations += _append_translations(conn, sense_id, row.data)
        added_examples += _append_examples(conn, sense_id, row.data)
        added_flags += _append_flags(conn, sense_id, row.data)

    return {
        "inserted_senses": inserted,
        "existing_senses_touched": merged_senses,
        "translations_added": added_translations,
        "examples_added": added_examples,
        "flags_added": added_flags,
        "skipped": skipped,
        "skipped_count": len(skipped),
        "version": IMPORT_VERSION,
    }


# --------------------------------------------------------------------------
# Insert helpers (append-only; no UPDATE/DELETE anywhere)
# --------------------------------------------------------------------------


def _insert_sense(conn: Any, data: dict[str, str]) -> uuid.UUID:
    from pipeline.normalize.clean import search_key  # noqa: PLC0415

    sense_id = uuid.uuid4()
    key = data.get("sense_key", "").strip() or _sense_key_for(
        data["headword"],
        data.get("part_of_speech", ""),
        data.get("definition", ""),
    )
    pos = data.get("part_of_speech", "").lower() or None
    cefr = data.get("cefr_level", "").upper() or None
    conn.execute(
        text(
            "INSERT INTO vocabulary_senses "
            "(id, sense_key, headword, headword_normalized, part_of_speech, "
            " cefr_level, definition_preview, processing_version, is_active) "
            "VALUES (:id, :key, :hw, :hwn, :pos, :cefr, :def, :ver, true)"
        ),
        {
            "id": sense_id,
            "key": key,
            "hw": data["headword"],
            "hwn": search_key(data["headword"]),
            "pos": pos,
            "cefr": cefr,
            "def": data.get("definition", "") or None,
            "ver": IMPORT_VERSION,
        },
    )
    _ensure_lemma_form(conn, sense_id, data["headword"])
    return sense_id


def _ensure_lemma_form(conn: Any, sense_id: uuid.UUID, headword: str) -> None:
    from pipeline.normalize.clean import search_key  # noqa: PLC0415

    conn.execute(
        text(
            "INSERT INTO vocabulary_forms (id, sense_id, form, form_normalized, is_lemma) "
            "VALUES (:id, CAST(:sid AS uuid), :f, :fn, true) "
            "ON CONFLICT (sense_id, form_normalized) DO NOTHING"
        ),
        {
            "id": uuid.uuid4(),
            "sid": sense_id,
            "f": headword,
            "fn": search_key(headword),
        },
    )


def _append_translations(conn: Any, sense_id: uuid.UUID, data: dict[str, str]) -> int:
    from pipeline.normalize.clean import search_key  # noqa: PLC0415

    added = 0
    existing = {
        str(r[0])
        for r in conn.execute(
            text(
                "SELECT translation_normalized FROM sense_translations "
                "WHERE sense_id = CAST(:sid AS uuid)"
            ),
            {"sid": sense_id},
        ).all()
    }
    for tr in _split_multi(data.get("translations_pl", "")):
        norm = search_key(tr)
        if not norm or norm in existing:
            continue
        conn.execute(
            text(
                "INSERT INTO sense_translations "
                "(id, sense_id, language, translation, translation_normalized, "
                " position, source) "
                "VALUES (:id, CAST(:sid AS uuid), 'pl', :tr, :trn, "
                " (SELECT COALESCE(max(position), -1) + 1 FROM sense_translations "
                "   WHERE sense_id = CAST(:sid AS uuid)), 'import')"
            ),
            {
                "id": uuid.uuid4(),
                "sid": sense_id,
                "tr": tr[:400],
                "trn": norm[:400],
            },
        )
        existing.add(norm)
        added += 1
    return added


def _append_examples(conn: Any, sense_id: uuid.UUID, data: dict[str, str]) -> int:
    added = 0
    existing = {
        str(r[0])
        for r in conn.execute(
            text("SELECT example FROM sense_examples WHERE sense_id = CAST(:sid AS uuid)"),
            {"sid": sense_id},
        ).all()
    }
    for ex in _split_multi(data.get("examples", "")):
        if not ex or ex in existing:
            continue
        conn.execute(
            text(
                "INSERT INTO sense_examples (id, sense_id, example, position, source) "
                "VALUES (:id, CAST(:sid AS uuid), :ex, "
                " (SELECT COALESCE(max(position), -1) + 1 FROM sense_examples "
                "   WHERE sense_id = CAST(:sid AS uuid)), 'import')"
            ),
            {"id": uuid.uuid4(), "sid": sense_id, "ex": ex[:10_000]},
        )
        existing.add(ex)
        added += 1
    return added


def _append_flags(conn: Any, sense_id: uuid.UUID, data: dict[str, str]) -> int:
    added = 0
    for flag in _split_multi(data.get("flags", "")):
        result = conn.execute(
            text(
                "INSERT INTO vocabulary_flags (id, sense_id, flag) "
                "VALUES (:id, CAST(:sid AS uuid), :fl) "
                "ON CONFLICT (sense_id, flag) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "sid": sense_id, "fl": flag.lower()},
        )
        added += result.rowcount or 0
    return added
