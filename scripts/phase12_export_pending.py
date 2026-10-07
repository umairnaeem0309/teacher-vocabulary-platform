"""Export the pending emb-v1 recipes for off-machine embedding (Google Colab).

Writes one .npz holding the exact texts the local worker would embed, plus
their text_sha256 values, so a GPU run elsewhere can reproduce emb-v1
vectors and import them without touching the recipe rule.

Pair with scripts/phase12_import_embeddings.py (which reads the RESULT
file Colab produces) and scripts/embedding_status.py.

Sharding (run N Colab sessions in parallel):

    python scripts/phase12_export_pending.py --shard 0 --shards 4 --out data/construction/embed_pending.s0.npz
    python scripts/phase12_export_pending.py --shard 1 --shards 4 --out data/construction/embed_pending.s1.npz
    ...

The partition is deterministic (sorted keys, stride), so re-exporting the
same shard later picks up exactly what is still missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv

load_dotenv(REPO / ".env")

from pipeline.enrich.embeddings import (
    DIMS,
    EMBEDDINGS_VERSION,
    MODEL_NAME,
    embed_text,
    text_sha256,
)
from pipeline.storage.sqlite_store import ConstructionStore


def all_recipes() -> tuple[list[str], list[str], list[str]]:
    """(keys, texts, shas) for every master sense, phase12's recipe."""
    store = ConstructionStore(REPO / "data" / "construction" / "construction.sqlite")
    rows = store.conn.execute(
        "SELECT sense_key, headword_search, pos_canonical, gloss_search "
        "FROM master_senses ORDER BY sense_key"
    ).fetchall()
    keys: list[str] = []
    texts: list[str] = []
    shas: list[str] = []
    for key, hw, pos, gloss in rows:
        examples = [
            r[0]
            for r in store.conn.execute(
                "SELECT text FROM sense_examples WHERE sense_key = ? "
                "ORDER BY position LIMIT 2",
                (key,),
            )
        ]
        text = embed_text(str(hw or ""), str(pos or ""), str(gloss or ""), examples)
        keys.append(str(key))
        texts.append(text)
        shas.append(text_sha256(text))
    store.close()
    return keys, texts, shas


def stored() -> dict[str, str]:
    import os

    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT vs.sense_key, se.text_sha256 FROM sense_embeddings se "
                "JOIN vocabulary_senses vs ON vs.id = se.sense_id "
                "WHERE se.embedding_version = :v"
            ),
            {"v": EMBEDDINGS_VERSION},
        ).fetchall()
    engine.dispose()
    return {str(k): str(s) for k, s in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(REPO / "data" / "construction" / "embed_pending.npz"),
    )
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    if args.shards < 1 or not (0 <= args.shard < args.shards):
        raise SystemExit("need 0 <= --shard < --shards")

    keys, texts, shas = all_recipes()
    existing = stored()
    pending = [
        (k, t, s)
        for k, t, s in zip(keys, texts, shas, strict=True)
        if existing.get(k) != s
    ]
    # deterministic stride partition over sorted keys
    pending.sort(key=lambda r: r[0])
    mine = pending[args.shard:: args.shards]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "model_name": MODEL_NAME,
        "embeddings_version": EMBEDDINGS_VERSION,
        "dims": DIMS,
        "created": datetime.now(timezone.utc).isoformat(),
        "total_pending": len(pending),
        "shard": args.shard,
        "shards": args.shards,
        "in_this_file": len(mine),
        "note": "vectors must be L2-normalized float32, one per key, same order",
    }
    np.savez_compressed(
        out,
        keys=np.array([r[0] for r in mine]),
        shas=np.array([r[2] for r in mine]),
        texts=np.array([r[1] for r in mine]),
        meta=np.array(json.dumps(meta)),
    )
    size_mb = out.stat().st_size / 1e6
    print(
        f"wrote {out} ({size_mb:.1f} MB): {len(mine)} recipes "
        f"(shard {args.shard}/{args.shards} of {len(pending)} pending)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
