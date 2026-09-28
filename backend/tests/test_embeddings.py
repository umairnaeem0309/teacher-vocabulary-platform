"""Phase 12 tests: embeddings (emb-v1, section 88)."""

import hashlib

import pytest
from pipeline.enrich.embeddings import (
    DIMS,
    EMBEDDINGS_VERSION,
    Checkpoint,
    EmbeddingRecord,
    embed_text,
    generate_embeddings,
    text_sha256,
)

from tests.conftest import requires_db
from tests.test_pgvector import requires_vector


class FakeModel:
    """Duck-typed EmbeddingModel: deterministic hash-based vectors."""

    def __init__(self) -> None:
        self.encode_calls = 0

    def encode(self, texts: list[str], batch_size: int = 32, **kwargs) -> list[list[float]]:
        self.encode_calls += 1
        out = []
        for t in texts:
            digest = hashlib.sha256(t.encode("utf-8")).digest()
            vec = [b / 255.0 for b in digest[:8]]
            out.append(vec + [0.0] * (DIMS - 8))
        return out

    def model_version(self) -> str:
        return "fake-model"


def _rows(*keys: str) -> list[dict]:
    return [
        {
            "sense_key": f"{k}|noun|t",
            "headword": k,
            "pos": "noun",
            "gloss": f"gloss of {k}",
            "examples": [f"{k} example one"],
        }
        for k in keys
    ]


class TestTextRecipe:
    def test_recipe_content(self) -> None:
        text = embed_text("bank", "noun", "money place", ["He paid.", "River edge."])
        assert text == "bank | noun | money place | He paid. | River edge."

    def test_examples_capped_at_two(self) -> None:
        text = embed_text("w", "noun", "g", [f"ex {i}" for i in range(5)])
        assert text.count("|") == 4  # hw, pos, gloss, 2 examples

    def test_no_metadata_in_recipe(self) -> None:
        # section 88: CEFR/frequency/tags/priority never enter the text
        text = embed_text("bank", "noun", "money place", [])
        assert "A2" not in text and "rank" not in text and "tag" not in text

    def test_empty_parts_dropped(self) -> None:
        assert embed_text("bank", "", "", []) == "bank"

    def test_sha_deterministic(self) -> None:
        assert text_sha256("abc") == hashlib.sha256(b"abc").hexdigest()
        assert text_sha256("abc") == text_sha256("abc")
        assert text_sha256("abc") != text_sha256("abd")


class TestGeneration:
    def test_skips_unchanged_senses(self) -> None:
        rows = _rows("a", "b")
        sha = text_sha256(embed_text("a", "noun", "gloss of a", ["a example one"]))
        existing = {"a|noun|t": sha}
        records, report = generate_embeddings(rows, existing_shas=existing, model=FakeModel())
        assert report.skipped_unchanged == 1
        assert report.generated == 1
        assert [r.sense_key for r in records] == ["b|noun|t"]

    def test_changed_text_reembedded(self) -> None:
        rows = _rows("a")
        stale = {"a|noun|t": "0" * 64}
        records, report = generate_embeddings(rows, existing_shas=stale, model=FakeModel())
        assert report.reembedded_changed == 1
        assert len(records) == 1
        expected = text_sha256(embed_text("a", "noun", "gloss of a", ["a example one"]))
        assert records[0].text_sha256 == expected

    def test_resume_after_checkpoint(self) -> None:
        rows = _rows("a", "b", "c")
        cp = Checkpoint(last_sense_key="a|noun|t", batches_done=1)
        records, report = generate_embeddings(rows, model=FakeModel(), checkpoint=cp)
        # sorted keys: a|noun|t, b|noun|t, c|noun|t; resume after a
        assert [r.sense_key for r in records] == ["b|noun|t", "c|noun|t"]
        assert report.generated == 2

    def test_checkpoint_callback_per_batch(self) -> None:
        rows = _rows("a", "b", "c", "d", "e")
        seen: list[Checkpoint] = []
        records, report = generate_embeddings(
            rows, model=FakeModel(), batch_size=2,
            checkpoint_cb=seen.append,
        )
        assert report.batches == 3
        assert [cp.batches_done for cp in seen] == [1, 2, 3]
        assert seen[-1].last_sense_key == "e|noun|t"
        assert seen[-1].as_json() == Checkpoint.from_json(seen[-1].as_json()).as_json()

    def test_records_shape_and_version(self) -> None:
        records, report = generate_embeddings(_rows("a"), model=FakeModel())
        rec = records[0]
        assert isinstance(rec, EmbeddingRecord)
        assert len(rec.embedding) == DIMS
        assert rec.embedding_version == EMBEDDINGS_VERSION == "emb-v1"
        assert rec.model_name == "BAAI/bge-m3"
        assert report.version == "emb-v1"

    def test_deterministic_order_and_vectors(self) -> None:
        rows = _rows("b", "a", "c")
        r1, rep1 = generate_embeddings(rows, model=FakeModel())
        r2, rep2 = generate_embeddings(list(reversed(rows)), model=FakeModel())
        assert [r.sense_key for r in r1] == ["a|noun|t", "b|noun|t", "c|noun|t"]
        assert [x.embedding for x in r1] == [x.embedding for x in r2]
        assert rep1.as_dict() == rep2.as_dict()


class TestPgEmbeddingStore:
    @requires_db
    @requires_vector
    def test_roundtrip_and_nearest(self) -> None:
        from pipeline.storage.pg_store import (
            count_embeddings,
            ensure_sense_rows,
            nearest_senses,
            upsert_embeddings,
        )
        from sqlalchemy import create_engine, text

        engine = create_engine(
            "postgresql+psycopg://postgres:postgres@localhost:5432/vocab_platform",
            pool_pre_ping=True,
        )
        test_keys = [f"emb-test:{k}|noun|t" for k in ("alpha", "beta")]
        rows = [
            {"sense_key": k, "headword": k.split(":")[1].split("|")[0],
             "pos": "noun", "gloss": "test sense"}
            for k in test_keys
        ]
        records = [
            EmbeddingRecord(
                sense_key=test_keys[0],
                embedding=[1.0] + [0.0] * (DIMS - 1),
                model_version="fake",
                text_sha256="a" * 64,
            ),
            EmbeddingRecord(
                sense_key=test_keys[1],
                embedding=[0.0, 1.0] + [0.0] * (DIMS - 2),
                model_version="fake",
                text_sha256="b" * 64,
            ),
        ]
        try:
            with engine.begin() as conn:
                key_to_id = ensure_sense_rows(conn, rows)
                stored = upsert_embeddings(conn, key_to_id, records)
            assert stored == 2
            with engine.begin() as conn:
                stored_again = upsert_embeddings(conn, key_to_id, records)
                assert stored_again == 2  # upsert, no duplicates
                counts = count_embeddings(conn, EMBEDDINGS_VERSION)
                assert counts["versions"] >= 1
                near = nearest_senses(
                    conn, [1.0] + [0.0] * (DIMS - 1), limit=2,
                    version=EMBEDDINGS_VERSION,
                )
            # the all-X vector must be nearest to itself (cos distance ~0)
            assert near[0][0] == test_keys[0]
            assert near[0][1] == pytest.approx(0.0, abs=1e-6)
        finally:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM sense_embeddings WHERE sense_id IN "
                         "(SELECT id FROM vocabulary_senses WHERE sense_key LIKE 'emb-test:%')")
                )
                conn.execute(
                    text("DELETE FROM vocabulary_senses WHERE sense_key LIKE 'emb-test:%'")
                )
        engine.dispose()

    @requires_db
    @requires_vector
    def test_delete_other_versions(self) -> None:
        from pipeline.storage.pg_store import (
            delete_other_versions,
            ensure_sense_rows,
        )
        from sqlalchemy import create_engine, text

        engine = create_engine(
            "postgresql+psycopg://postgres:postgres@localhost:5432/vocab_platform",
            pool_pre_ping=True,
        )
        key = "emb-test:oldver|noun|t"
        try:
            with engine.begin() as conn:
                key_to_id = ensure_sense_rows(
                    conn, [{"sense_key": key, "headword": "oldver", "pos": "noun",
                            "gloss": "test"}]
                )
                conn.execute(
                    text(
                        "INSERT INTO sense_embeddings (sense_id, embedding, model_name, "
                        "model_version, dims, embedding_version, text_sha256) "
                        "VALUES (:sid, CAST(:emb AS vector), 'm', 'mv', :dims, 'emb-v0-old', :sha) "
                        "ON CONFLICT (sense_id, embedding_version) DO NOTHING"
                    ),
                    {
                        "sid": key_to_id[key],
                        "emb": "[" + ",".join(["0.0"] * DIMS) + "]",
                        "dims": DIMS,
                        "sha": "c" * 64,
                    },
                )
                removed = delete_other_versions(conn, EMBEDDINGS_VERSION)
            assert removed >= 1
        finally:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM vocabulary_senses WHERE sense_key = :k"),
                    {"k": key},
                )
        engine.dispose()
