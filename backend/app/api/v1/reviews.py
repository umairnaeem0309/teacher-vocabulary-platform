"""Reviews domain (Phase 20, sections 31-35).

GET  /reviews/due?student_id=…  — what to review next (overdue, due, new)
POST /reviews                   — record one review; updates FSRS, writes
                                  the immutable §33 event, moves the §31
                                  learning state

All teacher-authenticated and scoped through the owning student (§40).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.v1.auth import _require_teacher
from app.core import reviews as reviews_core
from app.db.session import get_engine

router = APIRouter(prefix="/reviews", tags=["reviews"])

TeacherDep = Annotated[dict[str, Any], Depends(_require_teacher)]


class ReviewRequest(BaseModel):
    student_id: str
    assignment_id: str
    rating: str = Field(pattern="^(HARD|MEDIUM|EASY)$")


@router.get("/due")
def due_queue(
    teacher: TeacherDep,
    student_id: str,
    limit: int = Query(50, ge=1, le=200),
    include_new: bool = True,
    assignment_ids: str = Query(
        "", description="§36: comma-separated assignment ids"
    ),
    set_id: str | None = Query(None, description="§36: restrict to a set"),
    learning_states: str = Query(
        "", description="§36: comma-separated learning states"
    ),
    difficult_only: bool = Query(False, description="§36: lapsed cards only"),
    search: str | None = Query(None, description="§36: headword substring"),
) -> dict[str, Any]:
    """Review queue (§32/§35/§36): overdue first, then due today, then new.

    §36: optionally narrowed to a chosen selection instead of the whole
    due queue — explicit assignments, a vocabulary set, learning states,
    difficult cards, or a headword search.
    """
    with get_engine().connect() as conn:
        return reviews_core.due_queue(
            conn,
            _teacher_id(teacher),
            student_id,
            limit=limit,
            include_new=include_new,
            assignment_ids=_csv(assignment_ids),
            set_id=set_id,
            learning_states=_csv(learning_states),
            difficult_only=difficult_only,
            search=search,
        )


def _csv(value: str) -> list[str]:
    return [token.strip() for token in value.split(",") if token.strip()]


@router.post("", status_code=201)
def record_review(teacher: TeacherDep, body: ReviewRequest) -> dict[str, Any]:
    """Record one review (§32): FSRS update + §33 immutable event."""
    with get_engine().begin() as conn:
        return reviews_core.review_assignment(
            conn,
            _teacher_id(teacher),
            body.student_id,
            body.assignment_id,
            body.rating,
        )


def _teacher_id(teacher: dict[str, Any]) -> Any:
    from app.api.v1.students import _tid

    return _tid(teacher)
