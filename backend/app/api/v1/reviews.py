"""Reviews domain (section 54). Implemented in Phases 20-21."""

from fastapi import APIRouter

from app.api.v1.stub import register_stubs

router = APIRouter(prefix="/reviews", tags=["reviews"])

register_stubs(
    router,
    [
        ("/due", 20),
        ("", 20),
    ],
)
