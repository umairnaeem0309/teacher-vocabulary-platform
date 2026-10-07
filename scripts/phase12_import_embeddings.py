"""Import GPU-generated embeddings (e.g. from Google Colab) into PostgreSQL.

Reads the RESULT .npz produced off-machine (keys + shas + float32 vectors,
optionally texts), verifies integrity, and upserts into `sense_embeddings`
for emb-v1 with the exact same rules the local worker uses:

- rows whose stored sha already equals the incoming sha are skipped
  (idempotent — safe to import at any time, even while the local worker
  runs, and safe to re-run after a partial import);
- everything else is upserted with model/dims/version recorded.

Pair with scripts/phase12_export_pending.py (produces the recipe file the
GPU run consumes) and scripts/embedding_status.py (progress).

Usage:
    python scripts/phase12_import_embeddings.py data/downloads/embed_result.s0.npz
    python scripts/phase12_import_embeddings.py *.s*.npz            (all shards)
    python scripts/phase12_import_embeddings.py result.npz --dry-run

After the last import, rebuild the HNSW index (mandatory — D014):
    cd backend && PYTHONPATH=.. uv run python ../scripts/phase12_embeddings_smoke.py --full --reindex --resume
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv

load_dotenv(REPO / ".env")

from pipeline.enrich.embeddings import (
    DIMS,
    EMBEDDINGS_VERSION,
    EmbeddingRecord,
    text_sha256,
)
from pipeline.storage.pg_store import (
    delete_other_versions,
    existing_embedding_shas,
    upsert_embeddings,
)


def load_result(path: Path) -> tuple[list[str], list[str], list[str], np.ndarray]:
    data = np.load(path, allow_pickle=False)
    keys = [str(x) for x in data["keys"]]
    shas = [str(x) for x in data["shas"]]
    vectors = np.asarray(data["embeddings"], dtype=np.float32)
    texts = [str(x) for x in data["texts"]] if "texts" in data.files else None
    if "meta" in data.files:
        meta = json.loads(str(data["meta"]))
        if meta.get("embeddings_version") not in (None, EMBEDDINGS_VERSION):
            raise SystemExit(
                f"{path.name}: wrong embeddings_version {meta.get('embeddings_version')}"
            )
        if meta.get("dims") not in (None, DIMS):
            raise SystemExit(f"{path.name}: wrong dims {meta.get('dims')}")
    if len(keys) != len(shas) or len(keys) != len(vectors):
        raise SystemExit(f"{path.name}: keys/shas/vectors length mismatch")
    if vectors.ndim != 2 or vectors.shape[1] != DIMS:
        raise SystemExit(f"{path.name}: expected vectors Nx{DIMS}, got {vectors.shape}")
    if texts is not None and len(texts) == len(keys):
        bad = [
            k
            for k, t, s in zip(keys, texts, shas, strict=True)
            if text_sha256(t) != s
        ]
        if bad:
            raise SystemExit(f"{path.name}: sha mismatch for {len(bad)} rows (stale file?)")
    return keys, shas, texts or [], vectors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="+", help="result .npz file(s) from the GPU run")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and report, but do not write to PostgreSQL",
    )
    args = parser.parse_args()

    keys: list[str] = []
    shas: list[str] = []
    vecs: list[np.ndarray] = []
    for raw in args.results:
        path = Path(raw)
        k, s, _t, v = load_result(path)
        print(f"{path.name}: {len(k)} rows ok")
        keys.extend(k)
        shas.extend(s)
        vecs.extend(v)

    if len(set(keys)) != len(keys):
        raise SystemExit("duplicate sense_keys across result files — check shard overlap")

    import os

    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    incoming = list(zip(keys, shas, vecs, strict=True))
    with engine.begin() as conn:
        id_rows = conn.execute(
            text("SELECT sense_key, id FROM vocabulary_senses WHERE sense_key = ANY(:ks)"),
            {"ks": keys},
        ).fetchall()
        key_to_id = {str(k): i for k, i in id_rows}
        missing = [k for k in keys if k not in key_to_id]
        if missing:
            raise SystemExit(
                f"{len(missing)} sense_keys not found in PostgreSQL (stale export "
                f"file? re-export) — e.g. {missing[:3]}"
            )
        existing = existing_embedding_shas(conn, EMBEDDINGS_VERSION)
        fresh = [(k, s, v) for k, s, v in incoming if existing.get(k) != s]
        print(
            f"incoming={len(incoming)} already_stored={len(incoming) - len(fresh)} "
            f"to_upsert={len(fresh)}"
        )
        if args.dry_run:
            print("dry-run: nothing written")
            return 0
        records = [
            EmbeddingRecord(
                sense_key=k,
                embedding=[float(x) for x in v],
                text_sha256=s,
            )
            for k, s, v in fresh
        ]
        n = upsert_embeddings(conn, key_to_id, records)
        delete_other_versions(conn, EMBEDDINGS_VERSION)
    print(f"stored: {n} rows (emb-v1)")
    print("next: rebuild the HNSW index — see module docstring")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
