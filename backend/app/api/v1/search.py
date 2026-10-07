"""Search API (Phase 14, sections 20-22).

POST /api/v1/vocabulary/search — the four-layer search behind one
endpoint. Request/response are Pydantic models; the heavy lifting lives
in ``pipeline/search/engine.py`` (lexical + filters + semantic + hybrid
ranking). Filters compose in SQL (section 22 forbids client-side
filtering of a truncated result list).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pipeline.search.engine import MAX_LIMIT, SearchFilters, SearchRequest, SearchResult, search
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.db.session import get_engine

router = APIRouter(prefix="/vocabulary", tags=["search"])


class SearchFiltersIn(BaseModel):
    """Layer-2 filters (all optional; absent = no constraint)."""

    cefr: list[str] = Field(default_factory=list, examples=[["A2", "B1"]])
    pos: list[str] = Field(default_factory=list)
    priority_levels: list[str] = Field(default_factory=list)
    priority_min: str | None = Field(
        default=None, description='Minimum priority level, e.g. "HIGH+"'
    )
    category_key: str | None = Field(
        default=None, description="Category key; includes all descendant subcategories"
    )
    frequency_bands: list[str] = Field(
        default_factory=list, examples=[["top1000", "top2000"]]
    )
    max_frequency_rank: int | None = None
    flags: list[str] = Field(default_factory=list)
    student_id: uuid.UUID | None = None
    assigned: bool | None = Field(
        default=None,
        description="true=assigned only, false=not assigned (section 22)",
    )
    learning_states: list[str] = Field(default_factory=list)
    due_only: bool | None = None
    difficult_only: bool | None = None
    teacher_priority_only: bool | None = None
    translation_availability: str | None = Field(
        default=None,
        description="§42: reliable | multiple | uncertain | missing",
    )


class SearchRequestIn(BaseModel):
    """Request body for POST /vocabulary/search (sections 20-22)."""

    # Generous enough to search the corpus's own text: the longest sense
    # embedding recipe is 861 chars and 18% of senses exceed 300, so the
    # old 300-char cap rejected a teacher pasting a definition straight
    # back into search (HTTP 422). Still bounded, so a pasted paragraph is
    # the practical ceiling rather than an unbounded body.
    query: str = Field(
        default="", max_length=2000, examples=["vacation"],
        description="free text; quoted phrases, OR and -exclusions supported"
    )
    mode: str = Field(
        default="hybrid", description="hybrid | lexical | semantic"
    )
    filters: SearchFiltersIn = Field(default_factory=SearchFiltersIn)
    sort: str = Field(
        default="relevance",
        description=(
            "relevance | headword | polish | cefr | topic | pos | "
            "priority | frequency | student_status"
        ),
    )
    limit: int = Field(default=50, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)


def _to_engine_filters(f: SearchFiltersIn) -> SearchFilters:
    return SearchFilters(
        cefr=f.cefr,
        pos=f.pos,
        priority_levels=f.priority_levels,
        priority_min=f.priority_min,
        category_key=f.category_key,
        frequency_bands=f.frequency_bands,
        max_frequency_rank=f.max_frequency_rank,
        flags=f.flags,
        student_id=f.student_id,
        assigned=f.assigned,
        learning_states=f.learning_states,
        due_only=f.due_only,
        difficult_only=f.difficult_only,
        teacher_priority_only=f.teacher_priority_only,
        translation_availability=f.translation_availability,
    )


@router.post("/search")
def search_vocabulary(body: SearchRequestIn) -> dict[str, Any]:
    """Four-layer vocabulary search (section 20)."""
    req = SearchRequest(
        query=body.query,
        mode=body.mode,
        filters=_to_engine_filters(body.filters),
        sort=body.sort,
        limit=body.limit,
        offset=body.offset,
    )
    with get_engine().connect() as conn:
        result: SearchResult = search(conn, req)
    return result.as_dict()


# --------------------------------------------------------------------------
# Small companion endpoints the UI table needs (dense table, section 23):
# filters are useless if the client cannot enumerate filter values.
# --------------------------------------------------------------------------


@router.get("/search/filters")
def filter_facets() -> dict[str, Any]:
    """Enumerate filter values: categories, POS, CEFR, priority, bands."""
    with get_engine().connect() as conn:
        categories = conn.execute(
            text(
                "SELECT key, name, key = ANY(:roots) AS is_root FROM categories "
                "ORDER BY position, name"
            ),
            {"roots": ["travel", "food", "people", "activities", "world", "work"]},
        ).fetchall()
        pos_levels: list[Any] = list(
            conn.execute(
                text(
                    "SELECT DISTINCT part_of_speech FROM vocabulary_senses "
                    "WHERE part_of_speech IS NOT NULL ORDER BY 1"
                )
            ).scalars()
        )
        cefr_levels: list[Any] = list(
            conn.execute(
                text(
                    "SELECT DISTINCT cefr_level FROM vocabulary_senses "
                    "WHERE cefr_level IS NOT NULL ORDER BY 1"
                )
            ).scalars()
        )
        priority_levels: list[Any] = list(
            conn.execute(
                text(
                    "SELECT DISTINCT priority_level FROM vocabulary_senses "
                    "WHERE priority_level IS NOT NULL"
                )
            ).scalars()
        )
    return {
        "categories": [{"key": r[0], "name": r[1]} for r in categories],
        "part_of_speech": pos_levels,
        "cefr": cefr_levels,
        "priority_levels": priority_levels,
        "frequency_bands": ["top1000", "top2000", "top3000"],
        "flags": [
            "rare", "archaic", "obsolete", "technical", "specialized",
            "proper_name", "offensive", "american", "british",
        ],
    }
