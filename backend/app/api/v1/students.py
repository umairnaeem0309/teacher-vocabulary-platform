"""Students domain (Phase 17, sections 27/39/40).

Every endpoint requires an authenticated teacher (§40) and is scoped to
that teacher's own students — foreign ids are indistinguishable from
nonexistent ones (404). Business logic lives in app.core.students.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.v1.auth import _require_teacher
from app.core import students as students_core
from app.db.session import get_engine

router = APIRouter(prefix="/students", tags=["students"])


def require_teacher(request: Request) -> dict[str, Any]:
    """Resolve the session cookie or raise 401 (Phase 15 dependency)."""
    return _require_teacher(request)


def _tid(teacher: dict[str, Any]) -> uuid.UUID:
    """Teacher id from the session dict (already a UUID from the DB row)."""
    value = teacher["teacher_id"]
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class StudentCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=10_000)


class StudentUpdate(BaseModel):
    """PATCH body: only the fields the client actually sent are applied
    (via model_fields_set); an explicitly sent null clears the field."""

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=10_000)


class StudentStatusUpdate(BaseModel):
    status: str = Field(pattern="^(ACTIVE|INACTIVE|DELETED)$")


TeacherDep = Annotated[dict[str, Any], Depends(require_teacher)]


@router.get("")
def list_students(
    teacher: TeacherDep,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """List the teacher's students (§27)."""
    with get_engine().begin() as conn:
        items = students_core.list_students(
            conn, _tid(teacher), include_inactive
        )
    return {"students": items, "total": len(items)}


@router.post("", status_code=201)
def create_student(teacher: TeacherDep, body: StudentCreate) -> dict[str, Any]:
    """Create a student (§27)."""
    with get_engine().begin() as conn:
        created = students_core.create_student(
            conn,
            _tid(teacher),
            body.display_name,
            body.email,
            body.notes,
        )
    return created


@router.get("/{student_id}")
def get_student(teacher: TeacherDep, student_id: str) -> dict[str, Any]:
    """Open profile (§27); 404 for foreign or unknown ids (§40)."""
    with get_engine().connect() as conn:
        student = students_core.get_student(conn, _tid(teacher), student_id)
    return student


@router.patch("/{student_id}")
def update_student(
    teacher: TeacherDep, student_id: str, body: StudentUpdate
) -> dict[str, Any]:
    """Edit student (§27) — absent fields keep their values."""
    sent = body.model_fields_set
    with get_engine().begin() as conn:
        return students_core.update_student(
            conn,
            _tid(teacher),
            student_id,
            body.display_name if "display_name" in sent else None,
            body.email if "email" in sent else None,
            body.notes if "notes" in sent else None,
            sent=sent,
        )


@router.patch("/{student_id}/status")
def change_status(
    teacher: TeacherDep, student_id: str, body: StudentStatusUpdate
) -> dict[str, Any]:
    """Deactivate/reactivate/delete (§27; delete is soft)."""
    with get_engine().begin() as conn:
        return students_core.set_status(
            conn, _tid(teacher), student_id, body.status
        )


@router.get("/{student_id}/vocabulary")
def student_vocabulary(teacher: TeacherDep, student_id: str) -> dict[str, Any]:
    """View assigned vocabulary + learning state (§27/§28)."""
    with get_engine().connect() as conn:
        items = students_core.student_vocabulary(
            conn, _tid(teacher), student_id
        )
    return {"items": items, "total": len(items)}
