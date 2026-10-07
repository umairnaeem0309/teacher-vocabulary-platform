"""Print emb-v1 embedding progress: completed / remaining / percent / ETA.

Reads the same skip rule the worker uses (sha comparison against the
current recipe), so the numbers match what `phase12_embeddings_smoke.py`
would do on its next run — not just raw row counts.

    cd backend
    PYTHONPATH=.. uv run python ../scripts/embedding_status.py
    PYTHONPATH=.. uv run python ../scripts/embedding_status.py --measure
        (adds a 30 s live rate sample and an ETA)

Works from the repo root too:
    backend/.venv/Scripts/python.exe scripts/embedding_status.py --measure
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv

load_dotenv(REPO / ".env")

from pipeline.enrich.embeddings import (
    EMBEDDINGS_VERSION,
    embed_text,
    text_sha256,
)
from pipeline.storage.sqlite_store import ConstructionStore


def expected_shas() -> dict[str, str]:
    store = ConstructionStore(REPO / "data" / "construction" / "construction.sqlite")
    rows = store.conn.execute(
        "SELECT sense_key, headword_search, pos_canonical, gloss_search "
        "FROM master_senses ORDER BY sense_key"
    ).fetchall()
    out: dict[str, str] = {}
    for key, hw, pos, gloss in rows:
        examples = [
            r[0]
            for r in store.conn.execute(
                "SELECT text FROM sense_examples WHERE sense_key = ? "
                "ORDER BY position LIMIT 2",
                (key,),
            )
        ]
        out[str(key)] = text_sha256(
            embed_text(str(hw or ""), str(pos or ""), str(gloss or ""), examples)
        )
    store.close()
    return out


def stored_shas() -> dict[str, str]:
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
        "--measure",
        action="store_true",
        help="sample the live rate for 30 s and add an ETA",
    )
    args = parser.parse_args()

    expected = expected_shas()
    stored = stored_shas()
    done = sum(1 for k, sha in expected.items() if stored.get(k) == sha)
    left = len(expected) - done
    pct = 100.0 * done / len(expected) if expected else 100.0
    print(f"total={len(expected)} done={done} left={left} percent={pct:.1f}")

    if args.measure and left:
        print("measuring rate for 30 s ...", flush=True)
        t0 = time.time()
        done0 = done
        time.sleep(30)
        stored2 = stored_shas()
        done1 = sum(1 for k, sha in expected.items() if stored2.get(k) == sha)
        rate = (done1 - done0) / (time.time() - t0)
        print(f"rate={rate:.2f} senses/s")
        if rate > 0:
            hours = left / rate / 3600
            print(f"eta_hours={hours:.1f} (at the sampled rate)")

    ckpt = REPO / "data" / "construction" / f"{EMBEDDINGS_VERSION}_checkpoint.json"
    if ckpt.exists():
        print(f"checkpoint: {ckpt.read_text(encoding='utf-8').strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
