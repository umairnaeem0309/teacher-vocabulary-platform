"""Vocabulary domain (section 54). Implemented in Phases 13-16."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])

register_stubs(
    router,
    [
        ("", 13),
        ("/{sense_id}", 13),
    ],
    methods=["GET"],
)
