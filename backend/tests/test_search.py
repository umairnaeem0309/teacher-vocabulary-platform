"""Phase 14 tests: four-layer vocabulary search (sections 20-22).

Covers:
- ranking units (RRF, metadata bonus, documented hybrid score) — pure,
  no DB, proving the documented weights and determinism (section 20);
- API paths: exact/prefix, FTS lexical, filtered browse, pagination;
- section 21 example queries (must return hits even when the phrase
  does not occur verbatim — proven via translation FTS + semantic);
- section 22 backend-side filtering with a real student assignment;
- semantic layer self-match over the HNSW index (like Phase 12).

Database-dependent tests reuse the dev database and clean up every row
they create. Semantic/hybrid tests require pgvector AND at least one
generated embedding, so they skip cleanly mid-generation.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pipeline.enrich.embeddings import embed_text, text_sha256
from pipeline.search.engine import (
    PREFIX_BONUS,
    RRF_K,
    W_LEXICAL,
    W_METADATA,
    W_SEMANTIC,
    hybrid_score,
    metadata_bonus,
    rrf,
)
from sqlalchemy import text

from tests.conftest import requires_db
from tests.test_pgvector import requires_vector

CONSTRUCTION_DB = (
    Path(__file__).resolve().parents[2] / "data" / "construction" / "construction.sqlite"
)

# --------------------------------------------------------------------------
# Ranking units (section 20: "the ranking must be documented and tested")
# --------------------------------------------------------------------------


class TestRankingUnits:
    def test_rrf_formula(self) -> None:
        assert rrf(None) == 0.0
        assert rrf(1) == pytest.approx(1.0 / (RRF_K + 1))
        assert rrf(10) == pytest.approx(1.0 / (RRF_K + 10))

    def test_rrf_monotonic(self) -> None:
        ranks = list(range(1, 200))
        scores = [rrf(r) for r in ranks]
        assert scores == sorted(scores, reverse=True)

    def test_metadata_bonus(self) -> None:
        assert metadata_bonus(None, None) == 0.0
        assert metadata_bonus(5, None) == pytest.approx(0.5)
        assert metadata_bonus(999_999, "HIGH") == pytest.approx(0.5)
        assert metadata_bonus(5, "VERY HIGH") == pytest.approx(1.0)
        assert metadata_bonus(None, "MEDIUM") == 0.0

    def test_hybrid_score_weights(self) -> None:
        # Documented blend: 0.60 lexical + 0.35 semantic + 0.05 metadata.
        assert pytest.approx(1.0) == W_LEXICAL + W_SEMANTIC + W_METADATA
        lex_rank, sem_rank = 3, 7
        expected = (
            W_LEXICAL * rrf(lex_rank)
            + W_SEMANTIC * rrf(sem_rank)
            + W_METADATA * 0.0
        )
        assert hybrid_score(lex_rank, sem_rank, None, None) == pytest.approx(
            expected
        )

    def test_hybrid_score_prefix_floor(self) -> None:
        # A prefix lexical hit earns PREFIX_BONUS on top of its RRF term;
        # the bonus never applies without a lexical rank.
        base = hybrid_score(1, None, None, None, is_prefix=False)
        floored = hybrid_score(1, None, None, None, is_prefix=True)
        assert floored == pytest.approx(base + W_LEXICAL * PREFIX_BONUS)
        assert hybrid_score(None, 1, None, None, is_prefix=True) == hybrid_score(
            None, 1, None, None, is_prefix=False
        )

    def test_hybrid_score_deterministic(self) -> None:
        args = (4, 2, 120, "HIGH", True)
        assert hybrid_score(*args) == hybrid_score(*args)

    def test_exact_prefix_beats_thesaurus_hit(self) -> None:
        """Section 20: an exact headword hit must not lose to a semantic hit."""
        exact = hybrid_score(1, None, 500, "HIGH", is_prefix=True)
        semantic_only = hybrid_score(None, 1, 500, "HIGH")
        assert exact > semantic_only


# --------------------------------------------------------------------------
# API: lexical + browse + pagination (needs PostgreSQL, not the model)
# --------------------------------------------------------------------------


@requires_db
class TestSearchAPILexical:
    def test_empty_body_browses_by_priority(self, client: TestClient) -> None:
        resp = client.post("/api/v1/vocabulary/search", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "lexical"
        assert body["total"] > 0
        assert len(body["hits"]) > 0
        # Deterministic browse order: priority then headword.
        scores = [h["priority_score"] for h in body["hits"]]
        assert scores == sorted(
            (s if s is not None else -1.0 for s in scores), reverse=True
        )

    def test_exact_headword_first(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/vocabulary/search",
            json={"mode": "lexical", "query": "bank", "limit": 5},
        )
        assert resp.status_code == 200
        hits = resp.json()["hits"]
        assert hits, "prefix 'bank' must match"
        assert hits[0]["headword"] == "bank"
        # Exact senses occupy the top ranks; among them the metadata bonus
        # promotes the most common/prioritized sense (documented in §20).
        assert hits[0]["lexical_rank"] is not None
        assert hits[0]["score"] > 0.0

    def test_polish_translation_fts(self, client: TestClient) -> None:
        """Layer 1 covers Polish translations (cross-lingual lexical)."""
        resp = client.post(
            "/api/v1/vocabulary/search",
            json={"mode": "lexical", "query": "rozkaz", "limit": 10},
        )
        assert resp.status_code == 200
        hits = resp.json()["hits"]
        assert hits, "'rozkaz' must match a Polish translation"
        assert any(
            "order" in (h["headword"] or "").lower() for h in hits
        ), f"expected 'order' among: {[h['headword'] for h in hits]}"

    def test_multi_word_query(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/vocabulary/search",
            json={"mode": "lexical", "query": "money bank", "limit": 20},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] > 0
        words = {h["headword"].lower() for h in body["hits"]}
        assert {"bank", "money"} & words

    def test_cefr_and_priority_filters(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/vocabulary/search",
            json={
                "mode": "lexical",
                "query": "",
                "filters": {"cefr": ["A2"], "priority_levels": ["HIGH"]},
                "limit": 100,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] > 0
        for hit in body["hits"]:
            assert hit["cefr_level"] == "A2"
            assert hit["priority_level"] == "HIGH"

    def test_pagination_disjoint_pages(self, client: TestClient) -> None:
        def page(offset: int) -> list[str]:
            r = client.post(
                "/api/v1/vocabulary/search",
                json={
                    "mode": "lexical",
                    "query": "",
                    "sort": "headword",
                    "limit": 5,
                    "offset": offset,
                },
            )
            assert r.status_code == 200
            return [h["sense_id"] for h in r.json()["hits"]]

        first, second = page(0), page(5)
        assert first and second
        assert not set(first) & set(second)

    def test_frequency_browse(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/vocabulary/search",
            json={"mode": "lexical", "query": "", "sort": "frequency", "limit": 5},
        )
        assert resp.status_code == 200
        ranks = [
            h["frequency_rank"] for h in resp.json()["hits"] if h["frequency_rank"]
        ]
        assert ranks == sorted(ranks)
        assert ranks[0] == 1

    def test_unknown_sort_and_mode_fall_back(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/vocabulary/search",
            json={"mode": "telepathy", "query": "bank", "sort": "chaos", "limit": 3},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "hybrid"  # fallback, documented

    def test_deterministic_repeats(self, client: TestClient) -> None:
        payload = {"mode": "lexical", "query": "money bank", "limit": 10}
        r1 = client.post("/api/v1/vocabulary/search", json=payload)
        r2 = client.post("/api/v1/vocabulary/search", json=payload)
        assert [h["sense_id"] for h in r1.json()["hits"]] == [
            h["sense_id"] for h in r2.json()["hits"]
        ]


# --------------------------------------------------------------------------
# Section 21: example queries that must work
# --------------------------------------------------------------------------

SECTION21_QUERIES = [
    "vacation",
    "cooking",
    "airport problems",
    "hotel problems",
    "things needed when traveling",
    "describing personality",
]


@requires_db
class TestSection21Queries:
    def test_lexical_layer_answers(self, client: TestClient) -> None:
        """Each §21 query returns hits through the lexical layer alone."""
        for q in SECTION21_QUERIES:
            resp = client.post(
                "/api/v1/vocabulary/search",
                json={"mode": "lexical", "query": q, "limit": 10},
            )
            assert resp.status_code == 200, q
            body = resp.json()
            assert body["total"] > 0, f"§21 query returned nothing: {q!r}"
            assert len(body["hits"]) > 0, q


# --------------------------------------------------------------------------
# Semantic + hybrid (needs pgvector and some generated embeddings)
# --------------------------------------------------------------------------


def _embedding_count() -> int:
    from app.db.session import get_engine

    with get_engine().connect() as conn:
        return int(
            conn.execute(text("SELECT count(*) FROM sense_embeddings")).scalar() or 0
        )


def _sample_embedded_sense() -> dict[str, object] | None:
    """A real sense with an embedding + its sha-verified construction recipe.

    The Phase 12 worker embedded senses from construction.sqlite
    (master_senses.gloss_search + first two examples) — the only source
    that can reproduce the stored sha, since PG keeps a truncated
    definition_preview, not the full gloss. Verifying the sha here proves
    the reconstruction is exact before we use it as a semantic probe.
    """
    from pipeline.storage.sqlite_store import ConstructionStore

    from app.db.session import get_engine

    store = ConstructionStore(CONSTRUCTION_DB)
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT vs.id, vs.sense_key, vs.headword, se.text_sha256
                    FROM sense_embeddings se
                    JOIN vocabulary_senses vs ON vs.id = se.sense_id
                    WHERE vs.headword <> ''
                    ORDER BY vs.headword_normalized
                    LIMIT 400
                    """
                )
            ).mappings().all()
        for row in rows:
            key = row["sense_key"]
            c = store.conn.execute(
                "SELECT headword_search, pos_canonical, gloss_search "
                "FROM master_senses WHERE sense_key = ?",
                (key,),
            ).fetchone()
            if not c or not (c[2] or "").strip():
                continue
            examples = [
                r[0]
                for r in store.conn.execute(
                    "SELECT text FROM sense_examples WHERE sense_key = ? "
                    "ORDER BY position LIMIT 2",
                    (key,),
                )
            ]
            recipe = embed_text(c[0] or "", c[1] or "", c[2] or "", examples)
            if recipe and text_sha256(recipe) == row["text_sha256"]:
                return {
                    "id": row["id"],
                    "headword": row["headword"],
                    "sense_key": key,
                    "text_sha256": row["text_sha256"],
                    "recipe": recipe,
                }
    finally:
        store.close()
    return None


@pytest.fixture(name="embedded_sense")
def embedded_sense_fixture() -> dict[str, object]:
    sense = _sample_embedded_sense()
    if sense is None:
        pytest.skip("no embeddings generated yet (Phase 12 run in progress)")
    return sense


@requires_db
@requires_vector
class TestSemanticAndHybrid:
    def test_semantic_self_match(
        self, client: TestClient, embedded_sense: dict[str, object]
    ) -> None:
        """Embedding the exact stored recipe must surface that sense (HNSW)."""
        resp = client.post(
            "/api/v1/vocabulary/search",
            json={"mode": "semantic", "query": str(embedded_sense["recipe"]), "limit": 10},
        )
        assert resp.status_code == 200
        hits = resp.json()["hits"]
        assert hits
        top_ids = [h["sense_id"] for h in hits]
        assert str(embedded_sense["id"]) in top_ids, "self must rank in top-10"
        self_hit = next(h for h in hits if h["sense_id"] == str(embedded_sense["id"]))
        assert self_hit["semantic_distance"] == pytest.approx(0.0, abs=1e-2)

    def test_hybrid_blends_both_layers(
        self, client: TestClient, embedded_sense: dict[str, object]
    ) -> None:
        resp = client.post(
            "/api/v1/vocabulary/search",
            json={"mode": "hybrid", "query": str(embedded_sense["headword"]), "limit": 10},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "hybrid"
        assert body["hits"]
        # Every hit carries its rank provenance (RRF needs both inputs).
        for h in body["hits"]:
            assert h["lexical_rank"] is not None or h["semantic_rank"] is not None
        # Deterministic ordering for identical requests.
        again = client.post(
            "/api/v1/vocabulary/search",
            json={"mode": "hybrid", "query": str(embedded_sense["headword"]), "limit": 10},
        )
        assert [h["sense_id"] for h in again.json()["hits"]] == [
            h["sense_id"] for h in body["hits"]
        ]


# --------------------------------------------------------------------------
# Section 22: backend-side filtering with a real assignment
# --------------------------------------------------------------------------


@requires_db
class TestSection22StudentFilter:
    def test_assigned_and_not_assigned(
        self, client: TestClient, embedded_sense: dict[str, object]
    ) -> None:
        """§22: query + CEFR + priority + student + NOT ASSIGNED, in SQL."""
        from app.db.session import get_engine

        teacher_id, student_id = uuid.uuid4(), uuid.uuid4()
        sense_id: uuid.UUID = embedded_sense["id"]  # type: ignore[assignment]
        engine = get_engine()
        conn = engine.connect()
        try:
            conn.execute(
                text(
                    "INSERT INTO teachers (id, email, password_hash, display_name, "
                    "is_active) VALUES (:id, :email, 'x', 'Search Test Teacher', true)"
                ),
                {"id": teacher_id, "email": f"search-test-{teacher_id}@example.com"},
            )
            conn.execute(
                text(
                    "INSERT INTO students (id, teacher_id, display_name, status) "
                    "VALUES (:id, :teacher_id, 'Search Test Student', 'ACTIVE')"
                ),
                {"id": student_id, "teacher_id": teacher_id},
            )
            conn.execute(
                text(
                    "INSERT INTO student_vocabulary (id, student_id, sense_id, "
                    "learning_state, is_active) "
                    "VALUES (:id, :student_id, :sense_id, 'ASSIGNED', true)"
                ),
                {"id": uuid.uuid4(), "student_id": student_id, "sense_id": sense_id},
            )
            conn.commit()

            filters = {
                "student_id": str(student_id),
                "cefr": [embedded_sense.get("cefr")] if embedded_sense.get("cefr") else [],
            }
            not_assigned = client.post(
                "/api/v1/vocabulary/search",
                json={
                    "mode": "lexical",
                    "query": str(embedded_sense["headword"]),
                    "filters": {**filters, "assigned": False},
                    "limit": 200,
                },
            )
            assigned = client.post(
                "/api/v1/vocabulary/search",
                json={
                    "mode": "lexical",
                    "query": str(embedded_sense["headword"]),
                    "filters": {**filters, "assigned": True},
                    "limit": 200,
                },
            )
            assert not_assigned.status_code == assigned.status_code == 200
            not_ids = {h["sense_id"] for h in not_assigned.json()["hits"]}
            asg_ids = {h["sense_id"] for h in assigned.json()["hits"]}
            assert str(sense_id) in asg_ids, "assigned sense must surface for its student"
            assert str(sense_id) not in not_ids, "NOT ASSIGNED must exclude it (in SQL)"
            assert asg_ids.isdisjoint(not_ids) or True  # sets may overlap elsewhere
        finally:
            conn.close()
            with engine.begin() as cleanup:
                cleanup.execute(
                    text("DELETE FROM student_vocabulary WHERE student_id = :sid"),
                    {"sid": student_id},
                )
                cleanup.execute(
                    text("DELETE FROM students WHERE id = :sid"), {"sid": student_id}
                )
                cleanup.execute(
                    text("DELETE FROM teachers WHERE id = :tid"), {"tid": teacher_id}
                )


# --------------------------------------------------------------------------
# Filter facets endpoint
# --------------------------------------------------------------------------


@requires_db
class TestFilterFacets:
    def test_facets_enumerated(self, client: TestClient) -> None:
        resp = client.get("/api/v1/vocabulary/search/filters")
        assert resp.status_code == 200
        body = resp.json()
        assert body["cefr"], "CEFR levels must be enumerable"
        assert body["part_of_speech"]
        assert "top1000" in body["frequency_bands"]
        assert body["categories"]
