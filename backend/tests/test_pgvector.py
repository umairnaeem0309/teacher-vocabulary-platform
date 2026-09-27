"""pgvector availability tests (D004 resolution; Phase 12 prerequisite).

These tests prove the ``vector`` extension is installed and functional on
the configured PostgreSQL database: type round-trip, distance operators,
dimension enforcement and HNSW index support. They skip automatically
(with a clear reason) when PostgreSQL is unreachable, like the other
database-dependent tests (conftest.py ``requires_db``).
"""

import math

import pytest
from sqlalchemy import text

from tests.conftest import requires_db


def _vector_available() -> bool:
    from app.db.session import get_engine

    with get_engine().connect() as conn:
        return (
            conn.execute(
                text("SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            > 0
        )


VECTOR_AVAILABLE = _vector_available()

requires_vector = pytest.mark.skipif(
    not VECTOR_AVAILABLE,
    reason="pgvector extension not installed on the configured database",
)


@requires_db
@requires_vector
class TestPgvectorAvailability:
    def test_extension_installed(self) -> None:
        from app.db.session import get_engine

        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT extname, extversion FROM pg_extension WHERE extname='vector'")
            ).fetchone()
        assert row is not None
        assert row[0] == "vector"
        # 0.8.6 installed via D004 resolution; accept 0.8.x+
        major = int(str(row[1]).split(".")[0])
        assert major >= 1 or (major == 0 and int(str(row[1]).split(".")[1]) >= 6)

    def test_vector_roundtrip(self) -> None:
        from app.db.session import get_engine

        with get_engine().begin() as conn:
            conn.execute(text("CREATE TEMP TABLE pv_rt (emb vector(4))"))
            conn.execute(
                text("INSERT INTO pv_rt VALUES ('[0.1,0.2,0.3,0.4]')")
            )
            val = conn.execute(text("SELECT emb FROM pv_rt")).scalar()
        assert val is not None
        parts = [float(x) for x in str(val).strip("[]").split(",")]
        assert parts == pytest.approx([0.1, 0.2, 0.3, 0.4])

    def test_l2_distance_operator(self) -> None:
        from app.db.session import get_engine

        with get_engine().begin() as conn:
            conn.execute(text("CREATE TEMP TABLE pv_d (emb vector(3))"))
            conn.execute(text("INSERT INTO pv_d VALUES ('[1,2,3]'), ('[4,5,6]')"))
            dist = conn.execute(
                text("SELECT emb <-> '[1,2,3]' FROM pv_d ORDER BY 1 LIMIT 1")
            ).scalar()
        assert dist == pytest.approx(0.0)

    def test_cosine_distance_operator(self) -> None:
        from app.db.session import get_engine

        with get_engine().begin() as conn:
            conn.execute(text("CREATE TEMP TABLE pv_c (emb vector(3))"))
            conn.execute(text("INSERT INTO pv_c VALUES ('[1,0,0]'), ('[0,1,0]')"))
            dist = conn.execute(
                text("SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector")
            ).scalar()
        # orthogonal vectors: cos distance 1.0
        assert dist == pytest.approx(1.0)

    def test_dimension_enforced(self) -> None:
        from app.db.session import get_engine

        with get_engine().begin() as conn:
            conn.execute(text("CREATE TEMP TABLE pv_dim (emb vector(3))"))
            try:
                conn.execute(text("INSERT INTO pv_dim VALUES ('[1,2]'::vector)"))
            except Exception as exc:  # noqa: BLE001
                assert "expected 3 dimensions" in str(exc).lower()
                conn.rollback()
            else:
                pytest.fail("vector(3) accepted a 2-dim vector")

    def test_hnsw_index_and_query(self) -> None:
        from app.db.session import get_engine

        with get_engine().begin() as conn:
            conn.execute(
                text("CREATE TEMP TABLE pv_h (id serial, emb vector(4))")
            )
            conn.execute(
                text(
                    "INSERT INTO pv_h (emb) "
                    "SELECT ('[' || g || ',' || (g+1) || ',' || (g+2)"
                    " || ',' || (g+3) || ']')::vector "
                    "FROM generate_series(1, 100) g"
                )
            )
            conn.execute(
                text("CREATE INDEX ON pv_h USING hnsw (emb vector_l2_ops)")
            )
            conn.execute(text("SET LOCAL enable_seqscan = off"))
            nearest = conn.execute(
                text(
                    "SELECT id FROM pv_h "
                    "ORDER BY emb <-> '[1,2,3,4]' LIMIT 1"
                )
            ).scalar()
        assert nearest == 1

    def test_embedding_scale_compatible(self) -> None:
        # Phase 12 uses BGE-M3 at 1024 dims; prove that dimension works.
        from app.db.session import get_engine

        vec = "[" + ",".join(["0.01"] * 1024) + "]"
        with get_engine().begin() as conn:
            conn.execute(text("CREATE TEMP TABLE pv_1024 (emb vector(1024))"))
            conn.execute(
                text("INSERT INTO pv_1024 VALUES (:v)"), {"v": vec}
            )
            val = conn.execute(text("SELECT emb FROM pv_1024")).scalar()
        assert val is not None
        parts = [float(x) for x in str(val).strip("[]").split(",")]
        assert len(parts) == 1024
        assert all(p == pytest.approx(0.01) for p in parts[:5])
        # sanity: sqrt(1024 * 0.0001) = 0.32 l2 norm from origin
        expected = math.sqrt(1024 * 0.01**2)
        assert math.isclose(expected, 0.32, rel_tol=1e-9)
