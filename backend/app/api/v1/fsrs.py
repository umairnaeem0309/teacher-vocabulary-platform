"""FSRS domain (Phase 20, section 31): scheduler introspection.

GET /fsrs/parameters — the exact scheduler configuration in use
(deterministic: fuzzing disabled, no micro learning steps). The FSRS
version is recorded per review in review history (§33) and on every
student_fsrs_states row, so future algorithm upgrades stay auditable.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.v1.auth import _require_teacher
from app.core.reviews import FSRS_VERSION, SCHEDULER

router = APIRouter(prefix="/fsrs", tags=["fsrs"])

TeacherDep = Annotated[dict[str, Any], Depends(_require_teacher)]


@router.get("/parameters")
def fsrs_parameters(teacher: TeacherDep) -> dict[str, Any]:
    """The active FSRS scheduler configuration (deterministic)."""
    return {
        "fsrs_version": FSRS_VERSION,
        "desired_retention": SCHEDULER.desired_retention,
        "enable_fuzzing": False,
        "learning_steps": [],
        "relearning_steps": [],
        "rating_mapping": {"HARD": "Again(1)", "MEDIUM": "Hard(2)", "EASY": "Good(3)"},
    }
