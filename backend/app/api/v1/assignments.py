"""Assignments domain (Phase 18, sections 28-30).

POST /assignments            — single or bulk assign (one student, N senses)
GET /assignments/{id}        — one assignment (scoped through the student)
PATCH /assignments/{id}      — state move / priority override / hide

All endpoints teacher-authenticated; every query scoped to the owning
teacher via the students service (§40). Duplicate prevention is layered
(§29): application pre-check + UNIQUE(student_id, sense_id) backstop.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.v1.auth import _require_teacher
from app.api.v1.students import _tid
from app.core import assignments as assignments_core
from app.db.session import get_engine

router = APIRouter(prefix="/assignments", tags=["assignments"])

TeacherDep = Annotated[dict[str, Any], Depends(_require_teacher)]


_STATE_RE = "^(NEW|ASSIGNED|ENCOUNTERED|LEARNING|REVIEWING|MASTERED)$"


class AssignRequest(BaseModel):
    student_id: str
    sense_ids: list[str] = Field(min_length=1, max_length=1000)
    learning_state: str = Field(default="ASSIGNED", pattern=_STATE_RE)
    reactivate: bool = True


class AssignmentUpdate(BaseModel):
    """PATCH body — only sent fields apply (same semantics as students)."""

    learning_state: str | None = Field(default=None, pattern=_STATE_RE)
    teacher_priority_override: str | None = Field(
        default=None,
        pattern="^(VERY HIGH|HIGH|MEDIUM|LOW|VERY LOW)$",
    )
    is_active: bool | None = None
    # §38: clear the FSRS card (back to new) and/or adjust the next due date.
    reset_review: bool | None = None
    due_at: datetime | None = None


def _tid_dep(teacher: TeacherDep) -> uuid.UUID:
    return _tid(teacher)


@router.post("", status_code=200)
def assign(teacher: TeacherDep, body: AssignRequest) -> dict[str, Any]:
    """Assign senses to a student (§28); bulk-safe per §29.

    Response reports ``selected / new / already_assigned / failed``.
    """
    with get_engine().begin() as conn:
        return assignments_core.assign_senses(
            conn,
            _tid(teacher),
            body.student_id,
            body.sense_ids,
            learning_state=body.learning_state,
            reactivate=body.reactivate,
        )


@router.get("/{assignment_id}")
def get_assignment(
    teacher: TeacherDep, student_id: str, assignment_id: str
) -> dict[str, Any]:
    """One assignment, scoped through the owning student (§40)."""
    with get_engine().connect() as conn:
        return assignments_core.get_assignment(
            conn, _tid(teacher), student_id, assignment_id
        )


@router.patch("/{assignment_id}")
def update_assignment(
    teacher: TeacherDep, student_id: str, assignment_id: str, body: AssignmentUpdate
) -> dict[str, Any]:
    """Edit one assignment (§31 teacher overrides are explicit)."""
    sent = body.model_fields_set
    with get_engine().begin() as conn:
        return assignments_core.update_assignment(
            conn,
            _tid(teacher),
            student_id,
            assignment_id,
            learning_state=body.learning_state,
            teacher_priority_override=body.teacher_priority_override,
            is_active=body.is_active,
            reset_review=bool(body.reset_review),
            due_at=body.due_at,
            sent=sent,
        )
