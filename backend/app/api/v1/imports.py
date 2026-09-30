"""Imports domain (Phase 22, sections 38/99).

POST /imports/vocabulary/preview — parse + validate an uploaded
vocabulary file (CSV/XLSX/JSON) and report what would happen; writes
nothing. POST /imports/vocabulary — validated, insert-only commit
(never overwrites master vocabulary; D024).

Both require an authenticated teacher (§39/§40); imports are a
teacher-level operation.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.v1.auth import _require_teacher
from app.core import imports as imports_core
from app.db.session import get_engine

router = APIRouter(prefix="/imports", tags=["imports"])

TeacherDep = Annotated[dict[str, Any], Depends(_require_teacher)]


def _tid(teacher: dict[str, Any]) -> Any:
    from app.api.v1.students import _tid

    return _tid(teacher)


@router.post("/vocabulary/preview")
async def preview_vocabulary_import(
    teacher: TeacherDep,
    file: UploadFile = File(...),
    format: str = Form(...),
) -> dict[str, Any]:
    """Validate an import file and report per-row outcomes (no writes)."""
    content = await file.read()
    with get_engine().connect() as conn:
        return imports_core.preview_import(conn, content, format)


@router.post("/vocabulary")
async def import_vocabulary(
    teacher: TeacherDep,
    file: UploadFile = File(...),
    format: str = Form(...),
) -> dict[str, Any]:
    """Validated insert-only import; conflicting rows are skipped, never
    overwritten (§99)."""
    content = await file.read()
    with get_engine().begin() as conn:
        return imports_core.commit_import(conn, content, format)
