"""Phase 8 real-data smoke: WordNet catalog + sense linking on real data.

Loads all synsets/relations from data/raw/english-wordnet-2025-json, plus
entry evidence, then links the senses already stored in the construction
DB (from the Phase 7 run). Idempotent; safe to re-run.

Usage (from backend/ with uv):
    uv run python ../scripts/phase8_wordnet_smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.enrich.wordnet import (  # noqa: E402
    build_synset_catalog,
    build_wordnet_evidence,
    link_senses,
)
from pipeline.sources.wordnet_adapter import (  # noqa: E402
    SourceSynset,
    SourceSynsetRelation,
    adapt_wordnet_dir,
)
from pipeline.storage.sqlite_store import ConstructionStore  # noqa: E402

WN_DIR = REPO / "data" / "raw" / "english-wordnet-2025-json"
DB_PATH = REPO / "data" / "construction" / "construction.sqlite"


def main() -> int:
    t0 = time.time()
    print(f"WordNet dir: {WN_DIR}")
    run = adapt_wordnet_dir(WN_DIR)
    print(
        f"adapter: read={run.stats.read} processed={run.stats.processed} "
        f"failed={run.stats.failed} warnings={run.stats.warning} "
        f"records={len(run.records)} ({time.time() - t0:.1f}s)"
    )

    synsets = [r for r in run.records if isinstance(r, SourceSynset)]
    rels = [r for r in run.records if isinstance(r, SourceSynsetRelation)]
    links = [
        r
        for r in run.records
        if type(r).__name__ == "SourceWordnetLink"
    ]
    print(f"records: synsets={len(synsets)} relations={len(rels)} entry_links={len(links)}")

    t1 = time.time()
    catalog = build_synset_catalog(synsets, rels)
    print(f"catalog: {catalog.stats()} ({time.time() - t1:.1f}s)")

    t2 = time.time()
    evidence = build_wordnet_evidence(links)
    print(f"evidence: {len(evidence)} lemmas ({time.time() - t2:.1f}s)")

    store = ConstructionStore(DB_PATH)
    total_senses = store.count_senses()
    print(f"construction DB: {total_senses} master senses")

    # Read stored senses back (sense_key + gloss_search + headword + pos)
    # and rehydrate MasterSense-shaped objects for linking.
    t3 = time.time()
    cursor = store.conn.execute(
        "SELECT sense_key, headword_search, pos_canonical, gloss_search "
        "FROM master_senses"
    )
    senses = []
    Sense = type("Sense", (), {})
    for sense_key, hw, pos, gloss in cursor:
        s = Sense()
        s.sense_key = sense_key
        s.headword_search = hw
        s.pos_canonical = pos
        s.gloss_search = gloss or ""
        senses.append(s)
    print(f"rehydrated {len(senses)} senses ({time.time() - t3:.1f}s)")

    t4 = time.time()
    links_out, report = link_senses(senses, catalog, evidence)
    d = report.as_dict()
    print(f"linking ({time.time() - t4:.1f}s): {json.dumps(d, indent=None)}")

    t5 = time.time()
    store.upsert_wordnet(catalog, links_out)
    print(f"stored ({time.time() - t5:.1f}s): {store.count_wordnet()}")

    # Coverage of stored senses by POS and CEFR band (QC view, §126).
    pos_rows = store.conn.execute(
        "SELECT ms.pos_canonical, COUNT(DISTINCT ms.sense_key), "
        "COUNT(DISTINCT l.sense_key) "
        "FROM master_senses ms "
        "LEFT JOIN sense_wordnet_links l ON l.sense_key = ms.sense_key "
        "GROUP BY ms.pos_canonical ORDER BY 2 DESC"
    ).fetchall()
    for pos, total, linked in pos_rows:
        pct = (100.0 * linked / total) if total else 0.0
        print(f"  pos {pos:10s} total={total:6d} linked={linked:6d} ({pct:.1f}%)")

    cefr_rows = store.conn.execute(
        "SELECT ms.cefr_level, COUNT(DISTINCT ms.sense_key), "
        "COUNT(DISTINCT l.sense_key) "
        "FROM master_senses ms "
        "LEFT JOIN sense_wordnet_links l ON l.sense_key = ms.sense_key "
        "WHERE ms.cefr_level IS NOT NULL "
        "GROUP BY ms.cefr_level ORDER BY ms.cefr_level"
    ).fetchall()
    for level, total, linked in cefr_rows:
        pct = (100.0 * linked / total) if total else 0.0
        print(f"  cefr {level:3s} total={total:6d} linked={linked:6d} ({pct:.1f}%)")

    store.finish_run(
        store.begin_run("phase8-wordnet-smoke"),
        {"wordnet": store.count_wordnet(), "link_report": d},
    )
    store.close()
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
