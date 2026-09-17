"""Auth domain (section 54). Implemented in Phase 15."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/auth", tags=["auth"])

register_stubs(
    router,
    [
        ("/login", 15),
        ("/logout", 15),
        ("/session", 15),
    ],
)
