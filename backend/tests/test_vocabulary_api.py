"""Phase 16 tests: vocabulary browse + detail endpoints (section 23/54).

GET /vocabulary is the Phase 16 table's data source: GET wrapper around
the Phase 14 engine, so its semantics (deterministic sorts, filter
composition, pagination) must match POST /vocabulary/search exactly.
GET /vocabulary/{sense_id} must return the complete relationship set
for the detail page, and 404 with the standard envelope otherwise.

Database-dependent tests reuse the dev database; no rows are created.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from pipeline.search.engine import PRIORITY_LEVELS

from tests.conftest import requires_db


def _client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def _priority_min_set(min_level: str) -> set[str]:
    """Levels >= min_level; the engine's ordering is strongest first."""
    order = list(PRIORITY_LEVELS)
    return set(order[: order.index(min_level) + 1])


@requires_db
class TestBrowse:
    def test_browse_all_sorted_by_headword(self) -> None:
        c = _client()
        params = {"sort": "headword", "limit": 5}
        r = c.get("/api/v1/vocabulary", params=params)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] > 40_000
        assert len(body["hits"]) == 5
        # Parity: the GET wrapper must return exactly what the Phase 14
        # POST /vocabulary/search returns for identical parameters.
        post = c.post(
            "/api/v1/vocabulary/search",
            json={"query": "", "mode": "lexical", "sort": "headword", "limit": 5},
        )
        assert post.status_code == 200
        assert [h["sense_id"] for h in body["hits"]] == [
            h["sense_id"] for h in post.json()["hits"]
        ]

    def test_browse_paginates(self) -> None:
        c = _client()
        page1 = c.get(
            "/api/v1/vocabulary", params={"sort": "headword", "limit": 5, "offset": 0}
        ).json()
        page2 = c.get(
            "/api/v1/vocabulary", params={"sort": "headword", "limit": 5, "offset": 5}
        ).json()
        ids1 = {h["sense_id"] for h in page1["hits"]}
        ids2 = {h["sense_id"] for h in page2["hits"]}
        assert page2["total"] == page1["total"]
        assert ids1.isdisjoint(ids2)

    def test_browse_filters_compose(self) -> None:
        c = _client()
        r = c.get(
            "/api/v1/vocabulary",
            params={"sort": "priority", "cefr": "A2", "priority_min": "HIGH", "limit": 10},
        )
        assert r.status_code == 200
        for hit in r.json()["hits"]:
            assert hit["cefr_level"] == "A2"
            assert hit["priority_level"] in _priority_min_set("HIGH")

    def test_browse_coerces_bad_sort_like_post(self) -> None:
        """The engine's documented contract coerces unknown sorts to
        relevance (then, query-less, to a deterministic priority browse);
        GET must behave exactly like POST (no hidden drift)."""
        c = _client()
        r = c.get("/api/v1/vocabulary", params={"sort": "bogus", "limit": 10})
        assert r.status_code == 200
        post = c.post(
            "/api/v1/vocabulary/search",
            json={"query": "", "mode": "lexical", "sort": "bogus", "limit": 10},
        )
        assert post.status_code == 200
        assert r.json()["hits"] == post.json()["hits"]

    def test_browse_rejects_out_of_range_limit(self) -> None:
        """Query-schema constraints (unlike sort/mode coercion) are 422."""
        c = _client()
        assert c.get("/api/v1/vocabulary", params={"limit": 0}).status_code == 422
        assert c.get("/api/v1/vocabulary", params={"limit": 999}).status_code == 422
        assert c.get("/api/v1/vocabulary", params={"offset": -1}).status_code == 422


@requires_db
class TestDetail:
    def test_detail_round_trip(self) -> None:
        c = _client()
        # Pick a sense that has translations so the relation lists are non-empty.
        from sqlalchemy import text

        from app.db.session import get_engine

        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT vs.id FROM vocabulary_senses vs "
                    "JOIN sense_translations st ON st.sense_id = vs.id "
                    "WHERE vs.headword_normalized = 'bank' "
                    "LIMIT 1"
                )
            ).scalar_one()
        sid = str(row)

        r = c.get(f"/api/v1/vocabulary/{sid}")
        assert r.status_code == 200
        body = r.json()
        assert body["sense"]["id"] == sid
        assert body["sense"]["headword"] == "bank"
        assert len(body["translations"]) >= 1
        for key in (
            "forms",
            "definitions",
            "translations",
            "examples",
            "categories",
            "frequency",
            "priorities",
        ):
            assert key in body

    def test_detail_404_unknown_id(self) -> None:
        c = _client()
        r = c.get(f"/api/v1/vocabulary/{uuid.uuid4()}")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"
        assert "request_id" in r.json()["error"]

    def test_detail_404_invalid_uuid(self) -> None:
        c = _client()
        r = c.get("/api/v1/vocabulary/not-a-uuid")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"
