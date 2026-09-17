"""Search domain (section 54). Implemented in Phase 14."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/vocabulary", tags=["search"])

register_stubs(
    router,
    [("/search", 14)],
    methods=["POST"],
)
