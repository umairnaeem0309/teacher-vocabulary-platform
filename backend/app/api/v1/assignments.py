"""Assignments domain (section 54). Implemented in Phase 18."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/assignments", tags=["assignments"])

register_stubs(
    router,
    [
        ("", 18),
        ("/bulk", 18),
    ],
    methods=["POST"],
)
