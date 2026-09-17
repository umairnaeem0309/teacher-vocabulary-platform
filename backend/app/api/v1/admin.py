"""Admin domain (section 54). Bootstrap teacher creation arrives in Phase 15."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/admin", tags=["admin"])

register_stubs(
    router,
    [("/bootstrap", 15)],
    methods=["POST"],
)
