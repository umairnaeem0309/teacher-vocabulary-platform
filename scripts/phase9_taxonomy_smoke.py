"""Phase 9 real-data smoke: classify the construction DB senses.

Requires the Phase 8 WordNet catalog + links already stored. Loads senses,
rebuilds the catalog (or reuses raw data), runs the deterministic
classifier and stores taxonomy nodes + assignments. Idempotent.

Usage (from backend/ with uv):
    uv run python ../scripts/phase9_taxonomy_smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.enrich.taxonomy import (  # noqa: E402
    classify_senses,
    taxonomy_nodes,
)
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
    store = ConstructionStore(DB_PATH)
    total = store.count_senses()
    print(f"construction DB: {total} master senses")

    # Ensure WordNet artifacts exist (re-run Phase 8 step if missing).
    wn_counts = store.count_wordnet()
    if wn_counts["sense_links"] == 0:
        print("Phase 8 artifacts missing; building WordNet layer first...")
        run = adapt_wordnet_dir(WN_DIR)
        synsets = [r for r in run.records if isinstance(r, SourceSynset)]
        rels = [r for r in run.records if isinstance(r, SourceSynsetRelation)]
        links = [r for r in run.records if type(r).__name__ == "SourceWordnetLink"]
        catalog = build_synset_catalog(synsets, rels)
        evidence = build_wordnet_evidence(links)
        cur = store.conn.execute(
            "SELECT sense_key, headword_search, pos_canonical, gloss_search FROM master_senses"
        )
        S = type("S", (), {})
        senses = [S() for _ in ()]
        senses = []
        for sense_key, hw, pos, gloss in cur:
            s = S()
            s.sense_key, s.headword_search = sense_key, hw
            s.pos_canonical, s.gloss_search = pos, gloss or ""
            senses.append(s)
        links_out, _ = link_senses(senses, catalog, evidence)
        store.upsert_wordnet(catalog, links_out)
        wn_counts = store.count_wordnet()
    print(f"wordnet: {wn_counts}")

    # Load senses + their stored links.
    cur = store.conn.execute(
        "SELECT sense_key, headword_search, pos_canonical, gloss_search FROM master_senses"
    )
    S = type("S", (), {})
    senses = []
    for sense_key, hw, pos, gloss in cur:
        s = S()
        s.sense_key, s.headword_search = sense_key, hw
        s.pos_canonical, s.gloss_search = pos, gloss or ""
        senses.append(s)

    links: dict[str, list] = {}
    for sense_key, synset_id in store.conn.execute(
        "SELECT sense_key, synset_id FROM sense_wordnet_links"
    ):
        links.setdefault(sense_key, []).append(
            type("L", (), {"synset_id": synset_id})()
        )

    # Catalog needed only for hypernym chains.
    run = adapt_wordnet_dir(WN_DIR)
    synsets = [r for r in run.records if isinstance(r, SourceSynset)]
    rels = [r for r in run.records if isinstance(r, SourceSynsetRelation)]
    catalog = build_synset_catalog(synsets, rels)
    print(f"catalog ready ({time.time() - t0:.1f}s)")

    t1 = time.time()
    assignments, report = classify_senses(senses, links, catalog)
    d = report.as_dict()
    print(f"classified ({time.time() - t1:.1f}s):")
    print(json.dumps({k: v for k, v in d.items() if k != "by_category"}))
    print("by_category:")
    for cat, n in d["by_category"].items():
        print(f"  {cat:24s} {n:6d}")

    store.upsert_taxonomy_nodes(taxonomy_nodes())
    store.upsert_categories(assignments)
    print(f"stored: {store.count_taxonomy()}")
    store.finish_run(
        store.begin_run("phase9-taxonomy-smoke"),
        {"taxonomy": d, "counts": store.count_taxonomy()},
    )
    store.close()
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
