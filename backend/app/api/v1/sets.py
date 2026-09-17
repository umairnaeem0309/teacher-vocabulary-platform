"""Vocabulary sets domain (section 54). Implemented in Phase 19."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/sets", tags=["sets"])

register_stubs(
    router,
    [
        ("", 19),
        ("/{set_id}", 19),
    ],
)
