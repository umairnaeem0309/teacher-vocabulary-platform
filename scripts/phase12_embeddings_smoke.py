"""Phase 12 real-data smoke: BGE-M3 embeddings -> pgvector (emb-v1).

Generates embeddings for master senses and stores them in PostgreSQL
`sense_embeddings` (pgvector + HNSW). Features per section 88:

- batched generation (CPU-friendly batch size);
- checkpointing (data/construction/emb-v1_checkpoint.json) + resume
  (pass --resume; without it a fresh run resets the checkpoint);
- resume skips senses whose recipe text is unchanged (text_sha256);
- versioned rows (emb-v1, model + dims recorded); one current version.

Modes:
  --limit N    embed the N lowest-rank senses (smoke subset; default 96)
  --full       embed ALL senses (long CPU run; use with --resume)
  --probes     after generation, run representative similarity checks

Usage (from backend/ with uv):
    uv run python ../scripts/phase12_embeddings_smoke.py --limit 96 --probes
    uv run python ../scripts/phase12_embeddings_smoke.py --full --resume
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.enrich.embeddings import (  # noqa: E402
    EMBEDDINGS_VERSION,
    Checkpoint,
    EmbeddingModel,
    generate_embeddings,
)
from pipeline.storage.pg_store import (  # noqa: E402
    delete_other_versions,
    ensure_sense_rows,
    existing_embedding_shas,
    nearest_senses,
    upsert_embeddings,
)
from pipeline.storage.sqlite_store import ConstructionStore  # noqa: E402

DB_PATH = REPO / "data" / "construction" / "construction.sqlite"
CHECKPOINT_PATH = REPO / "data" / "construction" / f"{EMBEDDINGS_VERSION}_checkpoint.json"
DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/vocab_platform"


def load_rows(limit: int | None) -> list[dict]:
    store = ConstructionStore(DB_PATH)
    sql = (
        "SELECT ms.sense_key, ms.headword_search, ms.pos_canonical, "
        "ms.gloss_search, ms.frequency_rank FROM master_senses ms "
    )
    if limit:
        sql += "WHERE ms.frequency_rank IS NOT NULL "
    sql += "ORDER BY ms.sense_key"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = []
    for key, hw, pos, gloss, rank in store.conn.execute(sql):
        examples = [
            r[0]
            for r in store.conn.execute(
                "SELECT text FROM sense_examples WHERE sense_key = ? "
                "ORDER BY position LIMIT 2",
                (key,),
            )
        ]
        rows.append(
            {
                "sense_key": key,
                "headword": hw,
                "pos": pos,
                "gloss": gloss or "",
                "examples": examples,
                "frequency_rank": rank,
            }
        )
    store.close()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=96)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--probes", action="store_true")
    args = parser.parse_args()

    t0 = time.time()
    rows = load_rows(None if args.full else args.limit)
    print(f"rows: {len(rows)} (mode={'full' if args.full else f'limit {args.limit}'})")

    checkpoint = None
    if args.resume and CHECKPOINT_PATH.exists():
        checkpoint = Checkpoint.from_json(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        print(f"resume: checkpoint {checkpoint.as_json()}")
    else:
        CHECKPOINT_PATH.write_text(Checkpoint().as_json(), encoding="utf-8")

    from sqlalchemy import create_engine

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with engine.begin() as conn:
        key_to_id = ensure_sense_rows(conn, rows)
        existing = existing_embedding_shas(conn, EMBEDDINGS_VERSION)
    print(f"sense identity rows ensured: {len(key_to_id)}; stored shas: {len(existing)}")

    def save_checkpoint(cp: Checkpoint) -> None:
        CHECKPOINT_PATH.write_text(cp.as_json(), encoding="utf-8")

    records, report = generate_embeddings(
        rows,
        existing_shas=existing,
        model=EmbeddingModel.shared(),
        batch_size=args.batch_size,
        checkpoint=checkpoint,
        checkpoint_cb=save_checkpoint,
    )
    print(f"generated ({time.time() - t0:.1f}s): {json.dumps(report.as_dict())}")

    with engine.begin() as conn:
        n = upsert_embeddings(conn, key_to_id, records)
        deleted = delete_other_versions(conn, EMBEDDINGS_VERSION)
    print(f"stored: {n} rows (removed other versions: {deleted})")

    from sqlalchemy import text as _text

    with engine.connect() as conn:
        totals = conn.execute(
            _text("SELECT COUNT(*), COUNT(DISTINCT embedding_version) FROM sense_embeddings")
        ).fetchone()
    print(f"sense_embeddings totals: rows={totals[0]} versions={totals[1]}")

    if args.probes:
        model = EmbeddingModel.shared()
        probes = [
            ("bank", "noun", "an institution where one can place and borrow money"),
            ("bank", "noun", "the sloping side of a river"),
            ("football", "noun", "a game played with a ball between two teams"),
        ]
        for hw, pos, gloss in probes:
            text_in = f"{hw} | {pos} | {gloss}"
            vec = model.encode([text_in])[0]
            with engine.connect() as conn:
                neighbors = nearest_senses(conn, vec, limit=5, version=EMBEDDINGS_VERSION)
            print(f"probe {text_in!r}:")
            for key, dist in neighbors:
                print(f"    {dist:.4f}  {key}")

    engine.dispose()
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
