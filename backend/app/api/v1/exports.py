"""Exports domain (Phase 22, sections 38/99).

POST /exports/vocabulary — filtered master-vocabulary export as a file
download (CSV, XLSX or JSON). Selection reuses the search engine's
Layer-2 filters minus the student-viewpoint filters, which are rejected
(D024: student learning data never leaves through a file download).

Requires an authenticated teacher (§39/§40).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.auth import _require_teacher
from app.core import exports as exports_core
from app.db.session import get_engine

router = APIRouter(prefix="/exports", tags=["exports"])

TeacherDep = Annotated[dict[str, Any], Depends(_require_teacher)]


class ExportRequest(BaseModel):
    """Master-vocabulary filter selection (mirrors the workbench
    sidebar). Student-viewpoint fields are deliberately absent and
    forbidden: an unknown field (student_id, assigned, learning_states,
    due_only, difficult_only, teacher_priority_only) fails validation
    with 422 instead of being silently ignored (D024)."""

    model_config = ConfigDict(extra="forbid")

    cefr: list[str] = Field(default_factory=list)
    pos: list[str] = Field(default_factory=list)
    priority_levels: list[str] = Field(default_factory=list)
    priority_min: str | None = None
    category_key: str | None = None
    frequency_bands: list[str] = Field(default_factory=list)
    max_frequency_rank: int | None = Field(default=None, ge=1, le=100_000)
    flags: list[str] = Field(default_factory=list)
    format: str = Field(pattern="^(csv|xlsx|json)$")


@router.post("/vocabulary")
def export_vocabulary(
    teacher: TeacherDep,
    body: ExportRequest,
) -> Response:
    """Export master vocabulary in the requested format (§38/§99)."""
    filters_dict = body.model_dump(exclude={"format"})
    format_l = body.format.lower()
    if format_l not in exports_core.EXPORT_FORMATS:
        from app.core.errors import ValidationError

        raise ValidationError("format must be one of csv, xlsx, json.")
    exports_core.validate_export_request(filters_dict)

    with get_engine().connect() as conn:
        rows = exports_core.export_rows(conn, filters_dict)

    tid = _tid(teacher)
    filename = exports_core.filename_for(format_l, tid)
    if format_l == "csv":
        return Response(
            content=exports_core.to_csv(rows),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if format_l == "xlsx":
        return Response(
            content=exports_core.to_xlsx(rows),
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return Response(
        content=exports_core.to_json(rows),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _tid(teacher: dict[str, Any]) -> uuid.UUID:
    from app.api.v1.students import _tid

    return _tid(teacher)
