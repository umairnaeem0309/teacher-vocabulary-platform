"""FSRS domain (section 54). Implemented in Phase 20."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/fsrs", tags=["fsrs"])

register_stubs(
    router,
    [("/parameters", 20)],
)
