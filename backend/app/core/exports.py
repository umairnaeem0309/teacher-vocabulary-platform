"""Export service (Phase 22, sections 38/99): controlled vocabulary export.

Formats: CSV, XLSX, JSON. One row per master sense with the fields a
teacher (or another deployment of this platform) needs for controlled
data inspection and migration: identity (sense_key), display
(headword, POS, CEFR, definition preview), ranking (priority level,
frequency rank) and teaching content (Polish translations, examples,
flags).

Selection reuses the Phase 14 engine's Layer-2 filter composition
(``_apply_filters``) so an export always exports exactly what the
workbench shows — the same SQL predicates, minus the §30
student-viewpoint filters, which exports reject (D024: exports are
master-vocabulary only; student learning data never leaves through a
file download).
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from sqlalchemy import text

from app.core.errors import ValidationError

EXPORT_COLUMNS = [
    "sense_key",
    "headword",
    "part_of_speech",
    "cefr_level",
    "definition",
    "priority_level",
    "frequency_rank",
    "translations_pl",
    "examples",
    "flags",
]
"""Stable export schema (documented in D024; the import reader accepts
exactly these headers)."""

#: Multi-value separator inside one cell (translations / examples / flags).
MULTI_SEP = " | "

#: Hard cap on exported rows (§38 "controlled": a runaway export is a
#: bug, not a feature). The full corpus (41,690 senses) fits comfortably.
MAX_EXPORT_ROWS = 50_000

# Student-viewpoint engine filters that must not reach an export.
_STUDENT_FILTER_KEYS = (
    "student_id",
    "assigned",
    "learning_states",
    "due_only",
    "difficult_only",
    "teacher_priority_only",
)


def validate_export_request(filters_dict: dict[str, Any]) -> None:
    """Reject student-viewpoint filters (D024) with a 422 envelope."""
    present = [k for k in _STUDENT_FILTER_KEYS if filters_dict.get(k) not in (None, "", [], False)]
    if present:
        raise ValidationError(
            "Exports cover master vocabulary only; student-viewpoint "
            "filters are not allowed: " + ", ".join(sorted(present)) + "."
        )


def _rows(
    conn: Any,
    filters_dict: dict[str, Any],
) -> list[dict[str, Any]]:
    """Filtered master-vocabulary rows, deterministic order, uncapped by
    the search MAX_LIMIT (the export cap is MAX_EXPORT_ROWS instead)."""
    from pipeline.search.engine import _apply_filters  # noqa: PLC0415

    where: list[str] = ["vs.is_active"]
    params: dict[str, Any] = {}
    _apply_filters(conn, _engine_filters(filters_dict), where, params)

    sql = f"""
    SELECT vs.sense_key, vs.headword, vs.part_of_speech::text AS part_of_speech,
           vs.cefr_level::text AS cefr_level, vs.definition_preview,
           vs.priority_level,
           (SELECT min(fe.rank) FROM frequency_evidence fe
             WHERE fe.sense_id = vs.id) AS frequency_rank,
           COALESCE(
             (SELECT array_agg(st.translation ORDER BY st.position)
                FROM sense_translations st WHERE st.sense_id = vs.id),
             '{{}}') AS translations,
           (SELECT array_agg(se.example ORDER BY se.position)
              FROM sense_examples se WHERE se.sense_id = vs.id) AS examples,
           (SELECT array_agg(vf.flag::text ORDER BY vf.flag::text)
              FROM vocabulary_flags vf WHERE vf.sense_id = vs.id) AS flags
    FROM vocabulary_senses vs
    WHERE {" AND ".join(where)}
    ORDER BY vs.headword_normalized, vs.sense_key
    LIMIT :export_cap
    """
    params["export_cap"] = MAX_EXPORT_ROWS
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def _engine_filters(filters_dict: dict[str, Any]) -> Any:
    """Build engine SearchFilters from the request body (master fields)."""
    from pipeline.search.engine import SearchFilters  # noqa: PLC0415

    def _csv(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [v.strip() for v in str(value).split(",") if v.strip()]

    return SearchFilters(
        cefr=_csv(filters_dict.get("cefr")),
        pos=_csv(filters_dict.get("pos")),
        priority_levels=_csv(filters_dict.get("priority_levels")),
        priority_min=filters_dict.get("priority_min"),
        category_key=filters_dict.get("category_key"),
        frequency_bands=_csv(filters_dict.get("frequency_bands")),
        max_frequency_rank=filters_dict.get("max_frequency_rank"),
        flags=_csv(filters_dict.get("flags")),
    )


def _flatten(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "sense_key": r["sense_key"],
        "headword": r["headword"],
        "part_of_speech": r["part_of_speech"] or "",
        "cefr_level": r["cefr_level"] or "",
        "definition": r["definition_preview"] or "",
        "priority_level": r["priority_level"] or "",
        "frequency_rank": r["frequency_rank"] if r["frequency_rank"] is not None else "",
        "translations_pl": MULTI_SEP.join(r["translations"] or []),
        "examples": MULTI_SEP.join(r["examples"] or []),
        "flags": MULTI_SEP.join(r["flags"] or []),
    }


def export_rows(
    conn: Any,
    filters_dict: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flattened export rows in the stable column order (validation done
    by the endpoint; also the JSON payload shape)."""
    return [_flatten(r) for r in _rows(conn, filters_dict)]


def to_csv(rows: list[dict[str, Any]]) -> str:
    """RFC-4180 CSV with a header row (Excel-friendly: UTF-8 with BOM is
    the client's choice; the API returns plain UTF-8)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def to_xlsx(rows: list[dict[str, Any]]) -> bytes:
    """Streaming workbook (write-only mode keeps memory flat)."""
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("vocabulary")
    ws.append(list(EXPORT_COLUMNS))
    for row in rows:
        cells: list[Any] = []
        for col in EXPORT_COLUMNS:
            cell = WriteOnlyCell(ws, value=row[col])
            cells.append(cell)
        ws.append(cells)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2)


EXPORT_FORMATS = ("csv", "xlsx", "json")


def filename_for(format: str, teacher_id: uuid.UUID) -> str:
    """Content-Disposition filename (deterministic, no timestamps that
    would break content tests; the teacher renames on save anyway)."""
    return f"vocabulary-export-{teacher_id}.{format}"
