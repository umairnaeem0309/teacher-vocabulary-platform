"""Phase 10 real-data smoke: priority scoring over the construction DB.

Reads senses + stored evidence (translations, examples, WordNet links,
tags) and computes prio-v1 scores for every sense. Idempotent per
version.

Usage (from backend/ with uv):
    uv run python ../scripts/phase10_priority_smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.enrich.priority import score_senses  # noqa: E402
from pipeline.storage.sqlite_store import ConstructionStore  # noqa: E402

DB_PATH = REPO / "data" / "construction" / "construction.sqlite"


def main() -> int:
    t0 = time.time()
    store = ConstructionStore(DB_PATH)
    total = store.count_senses()
    print(f"construction DB: {total} master senses")

    # Gather evidence per sense in three grouped queries.
    evidence: dict[str, dict] = {}
    cur = store.conn.execute(
        "SELECT sense_key, gloss_search, cefr_level, frequency_rank, "
        "examples_json, tags_json FROM master_senses"
    )
    for sense_key, gloss, cefr, rank, examples_json, tags_json in cur:
        examples = json.loads(examples_json or "[]")
        tags = json.loads(tags_json or "[]")
        evidence[sense_key] = {
            "sense_key": sense_key,
            "gloss_search": gloss or "",
            "cefr_level": cefr,
            "frequency_rank": rank,
            "examples_count": len(examples),
            "gloss_tokens": len((gloss or "").split()),
            "wordnet_linked": False,
            "translations": [],
            "tags": tags,
        }
    print(f"senses loaded ({time.time() - t0:.1f}s)")

    n_tr = 0
    for sense_key, conf in store.conn.execute(
        "SELECT sense_key, confidence FROM sense_translations"
    ):
        ev = evidence.get(sense_key)
        if ev is not None:
            ev["translations"].append(type("T", (), {"confidence": conf})())
            n_tr += 1
    n_links = 0
    for (sense_key,) in store.conn.execute(
        "SELECT DISTINCT sense_key FROM sense_wordnet_links"
    ):
        ev = evidence.get(sense_key)
        if ev is not None:
            ev["wordnet_linked"] = True
            n_links += 1
    print(f"evidence: {n_tr} translations, {n_links} wordnet-linked senses")

    rows = list(evidence.values())
    t1 = time.time()
    results, report = score_senses(rows)
    print(f"scored ({time.time() - t1:.1f}s): {json.dumps(report.as_dict())}")

    store.upsert_priorities(results)
    print(f"stored: {store.count_priorities()}")

    # Level distribution per CEFR level (sanity, not equality: §14).
    rows_q = store.conn.execute(
        "SELECT ms.cefr_level, sp.level, COUNT(*) FROM sense_priorities sp "
        "JOIN master_senses ms ON ms.sense_key = sp.sense_key "
        "WHERE sp.version='prio-v1' AND ms.cefr_level IS NOT NULL "
        "GROUP BY 1, 2 ORDER BY 1, 2"
    ).fetchall()
    by_cefr: dict[str, dict[str, int]] = {}
    for cefr, level, n in rows_q:
        by_cefr.setdefault(cefr, {})[level] = n
    for cefr in sorted(by_cefr):
        print(f"  cefr {cefr}: {by_cefr[cefr]}")

    # Sample top and bottom.
    print("top 5:")
    for hw, level, score in store.conn.execute(
        "SELECT ms.headword_search, sp.level, sp.score FROM sense_priorities sp "
        "JOIN master_senses ms ON ms.sense_key = sp.sense_key "
        "WHERE sp.version='prio-v1' ORDER BY sp.score DESC LIMIT 5"
    ):
        print(f"  {score:.3f} {level:9s} {hw}")
    print("bottom 5:")
    for hw, level, score in store.conn.execute(
        "SELECT ms.headword_search, sp.level, sp.score FROM sense_priorities sp "
        "JOIN master_senses ms ON ms.sense_key = sp.sense_key "
        "WHERE sp.version='prio-v1' ORDER BY sp.score ASC LIMIT 5"
    ):
        print(f"  {score:.3f} {level:9s} {hw}")

    store.finish_run(
        store.begin_run("phase10-priority-smoke"),
        {"priority": report.as_dict(), "counts": store.count_priorities()},
    )
    store.close()
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
