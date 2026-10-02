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

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.v1.auth import _require_teacher
from app.core import imports as imports_core
from app.core.errors import PayloadTooLargeError
from app.db.session import get_engine

router = APIRouter(prefix="/imports", tags=["imports"])
TeacherDep = Annotated[dict[str, Any], Depends(_require_teacher)]


def _tid(teacher: dict[str, Any]) -> Any:
    from app.api.v1.students import _tid

    return _tid(teacher)


async def _capped_read(request: Request, file: UploadFile) -> bytes:
    """Read an upload with a hard byte cap (§39 safe file handling).

    Never trusts the client-declared Content-Length (spoofable); reads
    at most ``upload_max_bytes + 1`` bytes and rejects when one byte
    more than the cap arrives — so an oversized body cannot pin server
    memory regardless of what the request headers claim. Reads the cap
    from ``app.state.settings`` (per-request), matching the middleware.
    """
    cap = request.app.state.settings.upload_max_bytes
    content = await file.read(cap + 1)
    if len(content) > cap:
        raise PayloadTooLargeError(
            f"The uploaded file exceeds the {cap}-byte cap; "
            "nothing was imported."
        )
    return content


@router.post("/vocabulary/preview")
async def preview_vocabulary_import(
    request: Request,
    teacher: TeacherDep,
    file: UploadFile = File(...),
    format: str = Form(...),
) -> dict[str, Any]:
    """Validate an import file and report per-row outcomes (no writes)."""
    content = await _capped_read(request, file)
    with get_engine().connect() as conn:
        return imports_core.preview_import(conn, content, format)


@router.post("/vocabulary")
async def import_vocabulary(
    request: Request,
    teacher: TeacherDep,
    file: UploadFile = File(...),
    format: str = Form(...),
) -> dict[str, Any]:
    """Validated insert-only import; conflicting rows are skipped, never
    overwritten (§99)."""
    content = await _capped_read(request, file)
    with get_engine().begin() as conn:
        return imports_core.commit_import(conn, content, format)
