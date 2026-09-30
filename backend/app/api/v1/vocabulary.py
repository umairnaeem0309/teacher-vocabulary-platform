"""Vocabulary domain (section 54). Implemented in Phases 13-16.

GET /vocabulary            — filtered browse without a text query (the Phase 16
                             table's data source); a GET wrapper around the
                             Phase 14 engine so sorting/pagination semantics
                             stay identical to POST /vocabulary/search.
GET /vocabulary/{sense_id} — full detail of one master sense (forms,
                             definitions, Polish translations, examples,
                             categories, frequency and priority evidence).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Query
from pipeline.search.engine import MAX_LIMIT, SearchFilters, SearchRequest, search
from sqlalchemy import text

from app.core.errors import NotFoundError
from app.db.session import get_engine

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])


def _csv(value: str) -> list[str]:
    """Parse a comma-separated query parameter into clean tokens."""
    return [token.strip() for token in value.split(",") if token.strip()]


@router.get("")
def browse_vocabulary(
    query: str = Query("", max_length=300),
    mode: str = Query("lexical", description="hybrid | lexical | semantic"),
    sort: str = Query("headword", description="relevance | headword | priority | frequency"),
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    cefr: str = Query("", description="comma-separated CEFR levels"),
    pos: str = Query("", description="comma-separated parts of speech"),
    priority_levels: str = Query("", description="comma-separated priority levels"),
    priority_min: str | None = Query(None, description='e.g. "HIGH+"'),
    category_key: str | None = Query(None),
    frequency_bands: str = Query("", description="comma-separated bands"),
    max_frequency_rank: int | None = Query(None),
    flags: str = Query("", description="comma-separated flags"),
    student_id: str | None = Query(None, description="§30 assignment viewpoint"),
    assigned: bool | None = Query(None, description="§30: true/false"),
) -> dict[str, Any]:
    """Browse/filter vocabulary (section 23: dense table data source)."""
    try:
        sid: uuid.UUID | None = (
            uuid.UUID(student_id) if student_id else None
        )
    except ValueError as exc:
        raise NotFoundError("No such student.") from exc
    filters = SearchFilters(
        cefr=_csv(cefr),
        pos=_csv(pos),
        priority_levels=_csv(priority_levels),
        priority_min=priority_min,
        category_key=category_key,
        frequency_bands=_csv(frequency_bands),
        max_frequency_rank=max_frequency_rank,
        flags=_csv(flags),
        student_id=sid,
        assigned=assigned,
    )
    req = SearchRequest(
        query=query,
        mode=mode,
        filters=filters,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    with get_engine().connect() as conn:
        result = search(conn, req)
    return result.as_dict()


@router.get("/{sense_id}")
def sense_detail(sense_id: str) -> dict[str, Any]:
    """Full detail of one vocabulary sense (all relationships)."""
    try:
        sid = str(uuid.UUID(sense_id))
    except ValueError as exc:
        raise NotFoundError(
            f"No vocabulary sense with id {sense_id!r}."
        ) from exc

    with get_engine().connect() as conn:
        sense = conn.execute(
            text(
                "SELECT id, sense_key, headword, headword_normalized, "
                "part_of_speech, cefr_level, definition_preview, "
                "priority_score, priority_level, priority_version, "
                "processing_version, is_active, created_at, updated_at "
                "FROM vocabulary_senses WHERE id = CAST(:sid AS uuid)"
            ),
            {"sid": sid},
        ).mappings().first()
        if sense is None or not sense["is_active"]:
            raise NotFoundError(
                f"No vocabulary sense with id {sense_id!r}."
            )

        def rows(sql: str) -> list[dict[str, Any]]:
            return [
                dict(r)
                for r in conn.execute(text(sql), {"sid": sid}).mappings().all()
            ]

        forms = rows(
            "SELECT form, is_lemma FROM vocabulary_forms "
            "WHERE sense_id = CAST(:sid AS uuid) ORDER BY form"
        )
        definitions = rows(
            "SELECT definition, source FROM sense_definitions "
            "WHERE sense_id = CAST(:sid AS uuid) ORDER BY position"
        )
        translations = rows(
            "SELECT translation, language, confidence FROM sense_translations "
            "WHERE sense_id = CAST(:sid AS uuid) ORDER BY position"
        )
        examples = rows(
            "SELECT example, source FROM sense_examples "
            "WHERE sense_id = CAST(:sid AS uuid) ORDER BY position"
        )
        categories = rows(
            "SELECT c.key, c.name FROM sense_categories sc "
            "JOIN categories c ON c.id = sc.category_id "
            "WHERE sc.sense_id = CAST(:sid AS uuid) ORDER BY c.position, c.name"
        )
        frequency = rows(
            "SELECT s.key AS source_key, s.name AS source_name, "
            "fe.rank, fe.frequency_per_million, fe.raw_value "
            "FROM frequency_evidence fe "
            "JOIN vocabulary_sources s ON s.id = fe.source_id "
            "WHERE fe.sense_id = CAST(:sid AS uuid) "
            "ORDER BY fe.rank NULLS LAST"
        )
        priorities = rows(
            "SELECT version, score, level FROM sense_priorities "
            "WHERE sense_id = CAST(:sid AS uuid) ORDER BY version"
        )

    return {
        "sense": dict(sense),
        "forms": forms,
        "definitions": definitions,
        "translations": translations,
        "examples": examples,
        "categories": categories,
        "frequency": frequency,
        "priorities": priorities,
    }
