"""Domain router registry (section 54).

The app factory includes every router listed here under ``/api/v1``. Add a
domain by creating its module and exporting its ``router`` — never by
growing a giant shared router.
"""

from fastapi.routing import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.assignments import router as assignments_router
from app.api.v1.auth import router as auth_router
from app.api.v1.exports import router as exports_router
from app.api.v1.fsrs import router as fsrs_router
from app.api.v1.health import router as health_router
from app.api.v1.imports import router as imports_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.search import router as search_router
from app.api.v1.sets import router as sets_router
from app.api.v1.students import router as students_router
from app.api.v1.vocabulary import router as vocabulary_router

routers: list[APIRouter] = [
    health_router,
    auth_router,
    students_router,
    vocabulary_router,
    search_router,
    sets_router,
    assignments_router,
    reviews_router,
    fsrs_router,
    imports_router,
    exports_router,
    admin_router,
]
