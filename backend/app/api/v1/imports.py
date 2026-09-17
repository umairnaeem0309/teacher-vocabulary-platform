"""Imports domain (section 54). Implemented in Phase 23."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/imports", tags=["imports"])

register_stubs(
    router,
    [("/vocabulary", 23)],
    methods=["POST"],
)
