"""Phase 11 real-data smoke: integrate examples + compute quality indicators.

Integrates Wiktextract sense examples and WordNet synset examples into
sense_examples (ex-v1), then computes the section-87 quality indicators
for every sense (qual-v1) from stored evidence. Idempotent (full
refresh).

Usage (from backend/ with uv):
    uv run python ../scripts/phase11_quality_smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.enrich.examples import integrate_examples  # noqa: E402
from pipeline.enrich.quality import compute_quality_batch  # noqa: E402
from pipeline.storage.sqlite_store import ConstructionStore  # noqa: E402

DB_PATH = REPO / "data" / "construction" / "construction.sqlite"


def main() -> int:
    t0 = time.time()
    store = ConstructionStore(DB_PATH)
    total = store.count_senses()
    print(f"construction DB: {total} master senses")

    # --- Examples integration (ex-v1) ---
    wikt: dict[str, list] = {}
    for sense_key, examples_json in store.conn.execute(
        "SELECT sense_key, examples_json FROM master_senses"
    ):
        texts = json.loads(examples_json or "[]")
        if texts:
            wikt[sense_key] = texts

    wn: dict[str, list] = {}
    for sense_key, synset_id in store.conn.execute(
        "SELECT sense_key, synset_id FROM sense_wordnet_links "
        "ORDER BY sense_key, confidence DESC, synset_id"
    ):
        row = store.conn.execute(
            "SELECT examples_json FROM wordnet_synsets WHERE synset_id = ?",
            (synset_id,),
        ).fetchone()
        if row and row[0]:
            texts = json.loads(row[0])
            if texts:
                wn.setdefault(sense_key, []).extend(texts)

    records, ex_report = integrate_examples(wikt, wn)
    print(f"examples ({ex_report.version}): {json.dumps(ex_report.as_dict())}")
    store.upsert_examples(records)
    print(f"stored: {store.count_examples()}")

    # --- Quality indicators (qual-v1) ---
    translation_confs: dict[str, list[float]] = {}
    for sense_key, confidence in store.conn.execute(
        "SELECT sense_key, confidence FROM sense_translations"
    ):
        translation_confs.setdefault(sense_key, []).append(confidence)

    category_conf: dict[str, float] = {}
    for sense_key, confidence in store.conn.execute(
        "SELECT sense_key, MAX(confidence) FROM sense_categories GROUP BY 1"
    ):
        category_conf[sense_key] = float(confidence)

    examples_count: dict[str, int] = {}
    for sense_key, n in store.conn.execute(
        "SELECT sense_key, COUNT(*) FROM sense_examples GROUP BY 1"
    ):
        examples_count[sense_key] = int(n)

    rows = []
    for sense_key, gloss, cefr, rank in store.conn.execute(
        "SELECT sense_key, gloss_search, cefr_level, frequency_rank "
        "FROM master_senses ORDER BY sense_key"
    ):
        rows.append(
            {
                "sense_key": sense_key,
                "translation_confidences": translation_confs.get(sense_key, []),
                "gloss": gloss or "",
                "examples_count": examples_count.get(sense_key, 0),
                "cefr_level": cefr,
                "frequency_rank": rank,
                "category_confidence": category_conf.get(sense_key, 0.0),
            }
        )

    indicators, q_report = compute_quality_batch(rows)
    print(f"quality ({q_report.version}): {json.dumps(q_report.as_dict())}")
    store.upsert_quality(indicators)
    print(f"stored: {store.count_quality()}")

    # --- Distribution sanity ---
    print("sense_confidence distribution:")
    for lo, hi in ((0.8, 1.01), (0.6, 0.8), (0.4, 0.6), (0.2, 0.4), (0.0, 0.2)):
        n = store.conn.execute(
            "SELECT COUNT(*) FROM sense_quality WHERE sense_confidence >= ? "
            "AND sense_confidence < ?",
            (lo, hi),
        ).fetchone()[0]
        print(f"  [{lo:.1f},{hi:.1f}): {n}")

    print("top 5 sense_confidence:")
    for hw, gloss, conf in store.conn.execute(
        "SELECT ms.headword_search, ms.gloss_search, sq.sense_confidence "
        "FROM sense_quality sq JOIN master_senses ms "
        "ON ms.sense_key = sq.sense_key ORDER BY sq.sense_confidence DESC LIMIT 5"
    ):
        print(f"  {conf:.3f} {hw:14s} {gloss[:45]!r}")
    print("zero-evidence senses (kept, never deleted):")
    for hw, gloss, conf in store.conn.execute(
        "SELECT ms.headword_search, ms.gloss_search, sq.sense_confidence "
        "FROM sense_quality sq JOIN master_senses ms "
        "ON ms.sense_key = sq.sense_key WHERE sq.sense_confidence = 0 LIMIT 5"
    ):
        print(f"  {conf:.3f} {hw:14s} {gloss[:45]!r}")
    n_zero = store.conn.execute(
        "SELECT COUNT(*) FROM sense_quality WHERE sense_confidence = 0"
    ).fetchone()[0]
    print(f"  total zero-evidence senses retained: {n_zero}")

    store.finish_run(
        store.begin_run("phase11-quality-smoke"),
        {
            "examples": ex_report.as_dict(),
            "quality": q_report.as_dict(),
            "counts": {
                "examples": store.count_examples(),
                "quality": store.count_quality(),
            },
        },
    )
    store.close()
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
