"""PostgreSQL storage for embeddings (Phase 12, section 88).

Writes ``sense_embeddings`` rows (pgvector) created by
pipeline/enrich/embeddings.py. The table lives in the production schema
(migration 7b2c91a4e8f5) with an HNSW cosine index; this module is the
pipeline-side writer and is deliberately independent of the backend app
(callers pass a SQLAlchemy connection and DSN).

Because ``sense_embeddings`` carries a foreign key to
``vocabulary_senses``, storing an embedding requires a sense identity
row. ``ensure_sense_rows`` provides a minimal, idempotent bootstrap
(sense_key/headword/POS, ON CONFLICT DO NOTHING) so embeddings can be
stored before the Phase 13 full validated import enriches the same rows.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.engine import Connection

from pipeline.enrich.embeddings import EmbeddingRecord


def ensure_sense_rows(conn: Connection, rows: list) -> dict[str, uuid.UUID]:
    """Insert minimal identity rows for senses missing in PostgreSQL.

    ``rows``: each needs sense_key, headword, pos (canonical lowercase,
    mapped to the enum), gloss (used as definition_preview fallback).
    Returns sense_key -> id for every input row (existing or inserted).
    ON CONFLICT DO NOTHING: Phase 13's validated import owns enrichment.

    The part_of_speech enum accepts noun/verb/adjective/adverb/phrase/
    other; unknown values fall back to OTHER (D006 strings).
    """
    pos_map = {
        "noun": "NOUN",
        "verb": "VERB",
        "adjective": "ADJECTIVE",
        "adverb": "ADVERB",
        "phrase": "PHRASE",
        "other": "OTHER",
    }
    key_to_id: dict[str, uuid.UUID] = {}
    for row in rows:
        get = row.get if isinstance(row, dict) else lambda k, _r=row: getattr(_r, k)
        sense_key = str(get("sense_key"))
        sense_id: uuid.UUID | None = conn.execute(
            text("SELECT id FROM vocabulary_senses WHERE sense_key = :k"),
            {"k": sense_key},
        ).scalar()
        if sense_id is None:
            pos_raw = str(get("pos") or "other").strip().lower()
            # D006: UUID PKs are application-generated — supply the id here.
            sense_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO vocabulary_senses "
                    "(id, sense_key, headword, headword_normalized, part_of_speech, "
                    " definition_preview, is_active, processing_version) "
                    "VALUES (:id, :k, :hw, :hwn, :pos, :dp, TRUE, 'v0-bootstrap') "
                    "ON CONFLICT (sense_key) DO NOTHING"
                ),
                {
                    "id": sense_id,
                    "k": sense_key,
                    "hw": str(get("headword") or "")[:200],
                    "hwn": str(get("headword") or "").casefold()[:200],
                    "pos": pos_map.get(pos_raw, "OTHER"),
                    "dp": (str(get("gloss") or "") or None),
                },
            )
        if sense_id is None:  # defensive: id is set on both paths
            raise RuntimeError(f"could not resolve identity row for {sense_key}")
        key_to_id[sense_key] = sense_id
    return key_to_id


def existing_embedding_shas(conn: Connection, version: str) -> dict[str, str]:
    """sense_key -> text_sha256 for one embedding version (resume guard)."""
    rows = conn.execute(
        text(
            "SELECT vs.sense_key, se.text_sha256 FROM sense_embeddings se "
            "JOIN vocabulary_senses vs ON vs.id = se.sense_id "
            "WHERE se.embedding_version = :v"
        ),
        {"v": version},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def upsert_embeddings(
    conn: Connection,
    key_to_id: dict[str, uuid.UUID],
    records: list[EmbeddingRecord],
    batch_size: int = 500,
) -> int:
    """Insert/replace embedding rows for one version (batched)."""
    total = 0
    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]
        params = []
        for rec in batch:
            sense_id = key_to_id.get(rec.sense_key)
            if sense_id is None:
                continue
            params.append(
                {
                    "sid": sense_id,
                    "emb": "[" + ",".join(repr(x) for x in rec.embedding) + "]",
                    "mn": rec.model_name,
                    "mv": rec.model_version,
                    "dims": len(rec.embedding),
                    "ver": rec.embedding_version,
                    "sha": rec.text_sha256,
                }
            )
        if params:
            conn.execute(
                text(
                    "INSERT INTO sense_embeddings "
                    "(sense_id, embedding, model_name, model_version, dims, "
                    " embedding_version, text_sha256) VALUES "
                    "(:sid, CAST(:emb AS vector), :mn, :mv, :dims, :ver, :sha) "
                    "ON CONFLICT (sense_id, embedding_version) DO UPDATE SET "
                    "embedding = EXCLUDED.embedding, model_name = EXCLUDED.model_name, "
                    "model_version = EXCLUDED.model_version, dims = EXCLUDED.dims, "
                    "text_sha256 = EXCLUDED.text_sha256"
                ),
                params,
            )
        total += len(params)
    return total


def delete_other_versions(conn: Connection, version: str) -> int:
    """Keep one current embedding version (rows are regenerable, D014)."""
    res = conn.execute(
        text("DELETE FROM sense_embeddings WHERE embedding_version != :v"),
        {"v": version},
    )
    return int(getattr(res, "rowcount", 0) or 0)


def count_embeddings(conn: Connection, version: str | None = None) -> dict:
    if version:
        row = conn.execute(
            text(
                "SELECT COUNT(*), COUNT(DISTINCT embedding_version) "
                "FROM sense_embeddings WHERE embedding_version = :v"
            ),
            {"v": version},
        ).fetchone()
    else:
        row = conn.execute(
            text("SELECT COUNT(*), COUNT(DISTINCT embedding_version) FROM sense_embeddings")
        ).fetchone()
    if row is None:
        return {"rows": 0, "versions": 0}
    return {"rows": int(row[0]), "versions": int(row[1])}


def nearest_senses(
    conn: Connection,
    query_vector: list[float],
    limit: int = 5,
    version: str | None = None,
) -> list[tuple[str, float]]:
    """Cosine nearest neighbors using the HNSW index (section 90 preview)."""
    sql = (
        "SELECT vs.sense_key, se.embedding <=> CAST(:q AS vector) AS d "
        "FROM sense_embeddings se JOIN vocabulary_senses vs ON vs.id = se.sense_id "
    )
    params: dict = {"q": "[" + ",".join(repr(x) for x in query_vector) + "]"}
    if version:
        sql += " WHERE se.embedding_version = :v"
        params["v"] = version
    sql += " ORDER BY se.embedding <=> CAST(:q AS vector) LIMIT :lim"
    params["lim"] = limit
    return [(r[0], float(r[1])) for r in conn.execute(text(sql), params).fetchall()]
