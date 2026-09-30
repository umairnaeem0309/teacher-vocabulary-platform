"""Dashboard domain (Phase 21, sections 36/98).

GET /dashboard — all-students rollup for the main /dashboard page:
one row per student with the §36 working counts plus totals. Per-student
detail lives at GET /students/{student_id}/dashboard.

Both endpoints are teacher-authenticated (§40): only the teacher's own
students are ever visible.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.v1.auth import _require_teacher
from app.core import dashboard as dashboard_core
from app.db.session import get_engine

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

TeacherDep = Annotated[dict[str, Any], Depends(_require_teacher)]


@router.get("")
def dashboard_overview(
    teacher: TeacherDep,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Per-student counts + totals (§98), attention-need ordering."""
    with get_engine().connect() as conn:
        return dashboard_core.overview(
            conn,
            _teacher_id(teacher),
            include_inactive=include_inactive,
        )


def _teacher_id(teacher: dict[str, Any]) -> Any:
    from app.api.v1.students import _tid

    return _tid(teacher)
