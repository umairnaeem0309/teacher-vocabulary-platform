"""Students domain (section 54). Implemented in Phase 17."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/students", tags=["students"])

register_stubs(
    router,
    [
        ("", 17),
        ("/{student_id}", 17),
        ("/{student_id}/vocabulary", 17),
        ("/{student_id}/review", 17),
    ],
)
