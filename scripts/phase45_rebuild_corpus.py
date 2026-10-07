"""Phases 4-7 rebuild: construct the master vocabulary corpus from the FULL
Wiktextract dump (sections 44, 48, 81-82).

WHY THIS SCRIPT EXISTS
----------------------
The shipped construction database was built from a small, unfiltered slice
of the dump. Measured against the supplied profiles:

    distinct headwords        7,139   (42,038 senses)
    headwords absent from
      every supplied profile  5,143   (72% - '', '0', 'aa', 'aachen', ...)
    NGSL coverage             1,113 / 2,809   (39.6%)
    CEFR-J coverage           1,834 / 6,863   (26.7%)
    Octanove coverage           185 / 1,955   ( 9.5%)

Base words such as `hotel`, `water`, `teacher`, `dog` and `table` were
missing outright while their derived forms survived (`freshwater`, `dogged`,
`abatable`), so no search-tuning could ever surface them. The words are
present in `raw-wiktextract-data.jsonl.gz` (verified) and in the profiles
(verified) - the loss happened here, in corpus construction.

WHAT THIS DOES
--------------
1. Loads the profile adapters (NGSL, CEFR-J, Octanove) and derives the
   target vocabulary key set (slash-variants split; see `_target_keys`).
2. Streams the dump once, keeping only English entries whose headword is in
   that set (`adapt_wiktextract(target_keys=...)`; section 48: never load
   the dump into RAM).
3. Normalizes -> resolves sense identity -> reconciles CEFR/frequency
   (Phases 5, 6, 7) and writes the construction DB.

Downstream (unchanged, run afterwards): Phase 8 WordNet, 9 taxonomy,
10 priority, 11 examples/quality, 12 embeddings, 13 PostgreSQL import.

Usage:
    backend/.venv/Scripts/python.exe scripts/phase45_rebuild_corpus.py --reset
    # quick code-path check on the first N dump lines:
    backend/.venv/Scripts/python.exe scripts/phase45_rebuild_corpus.py --max-records 50000 --db /tmp/smoke.sqlite
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.enrich.applier import enrich_senses  # noqa: E402
from pipeline.identity.identity import resolve_identities  # noqa: E402
from pipeline.normalize.clean import search_key  # noqa: E402
from pipeline.normalize.normalizer import normalize_wiktextract  # noqa: E402
from pipeline.sources.cefrj_adapter import adapt_cefrj  # noqa: E402
from pipeline.sources.ngsl_adapter import adapt_ngsl  # noqa: E402
from pipeline.sources.octanove_adapter import adapt_octanove  # noqa: E402
from pipeline.sources.wiktextract_adapter import adapt_wiktextract  # noqa: E402
from pipeline.storage.sqlite_store import ConstructionStore  # noqa: E402

RAW = REPO / "data" / "raw"
DEFAULT_DB = REPO / "data" / "construction" / "construction.sqlite"
DEFAULT_REPORT = REPO / "data" / "construction" / "phase45_build_report.json"
WIKTEXTRACT = RAW / "raw-wiktextract-data.jsonl.gz"

BUILD_VERSION = "build-v2"


def _variants(headword: str) -> list[str]:
    """Profile headwords carry slash variants (`actor/actress`, `a.m./am`).

    Each side is a real target word; splitting them is normalization, not
    adapter policy (the CEFR-J adapter explicitly defers it to Phase 5).
    """
    parts = [p.strip() for p in (headword or "").split("/")]
    return [p for p in parts if p]


def _target_keys(headwords: list[str]) -> set[str]:
    """Normalized search keys for the taught vocabulary.

    Keys shorter than two characters are dropped: they only ever come from
    stranded punctuation in profile variants ("'m", "'s") and would pull
    single-letter dictionary entries into the corpus.
    """
    keys: set[str] = set()
    for headword in headwords:
        for variant in _variants(headword):
            key = search_key(variant)
            if len(key) >= 2:
                keys.add(key)
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--dump", type=Path, default=WIKTEXTRACT, help="wiktextract .jsonl.gz"
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="stop after N dump lines (code-path smoke test only)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="back up and replace the construction DB instead of merging",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="comma-separated words: restrict the target set (debugging)",
    )
    args = parser.parse_args()

    t0 = time.time()

    # ---- Phase 4: profile adapters -------------------------------------
    cefrj_run = adapt_cefrj(RAW / "cefrj-vocabulary-profile-1.5.csv")
    octanove_run = adapt_octanove(RAW / "octanove-vocabulary-profile-c1c2-1.0.csv")
    ngsl_run = adapt_ngsl(RAW / "NGSL_1.2_stats.csv")

    headwords = [r.headword for r in cefrj_run.records]
    headwords += [r.headword for r in octanove_run.records]
    headwords += [r.lemma for r in ngsl_run.records]

    target_keys = _target_keys(headwords)
    if args.only:
        wanted = {search_key(w) for w in args.only.split(",")}
        target_keys &= wanted
    print(
        f"target vocabulary: {len(target_keys)} keys from "
        f"cefrj={len(cefrj_run.records)} octanove={len(octanove_run.records)} "
        f"ngsl={len(ngsl_run.records)}",
        flush=True,
    )

    # ---- Phase 4: streamed, filtered Wiktextract pass -------------------
    print(f"streaming {args.dump.name} ...", flush=True)
    wikt_run = adapt_wiktextract(
        args.dump, max_records=args.max_records, target_keys=target_keys
    )
    dump_stats = wikt_run.stats.as_dict()
    print(f"dump pass: {dump_stats} in {time.time() - t0:.1f}s", flush=True)
    if not wikt_run.records:
        print("ERROR: no target entries found - refusing to write an empty corpus")
        return 1

    # ---- Phase 5: normalization ----------------------------------------
    candidates, norm_stats = normalize_wiktextract(
        wikt_run,
        cefrj=cefrj_run.records,
        octanove=octanove_run.records,
        ngsl=ngsl_run.records,
    )
    print(f"normalize: {norm_stats.as_dict()} -> {len(candidates)} candidates")

    # Phase 6 requires deterministically ordered input (D008).
    candidates.sort(
        key=lambda c: (
            c.headword_search,
            c.pos_canonical,
            c.gloss_search,
            c.source_record_ids[0] if c.source_record_ids else "",
        )
    )

    # ---- Phase 6: sense identity ---------------------------------------
    masters, id_stats = resolve_identities(candidates)
    distinct = len({m.headword_search for m in masters})
    print(
        f"identity: {len(masters)} master senses over {distinct} headwords "
        f"({id_stats.as_dict()})",
        flush=True,
    )

    # ---- Phase 7: CEFR + frequency reconciliation ----------------------
    enriched, enrich_report = enrich_senses(masters)
    print(
        "enrich: cefr_levels="
        f"{json.dumps(enrich_report.cefr_levels, sort_keys=True)} "
        f"cefr_unknown={enrich_report.cefr_unknown} "
        f"freq_unknown={enrich_report.frequency_unknown}",
        flush=True,
    )

    # ---- Storage --------------------------------------------------------
    db_path: Path = args.db
    if args.reset and db_path.exists():
        backup = db_path.with_suffix(f".pre-{BUILD_VERSION}.bak")
        shutil.move(str(db_path), str(backup))
        print(f"previous construction DB moved to {backup.name}")
    store = ConstructionStore(db_path)
    run_id = store.begin_run(BUILD_VERSION)
    written = store.upsert_senses(enriched)
    counts = {
        "senses": store.count_senses(),
        "translations": store.count_translations(),
    }
    store.finish_run(
        run_id,
        {
            "build": BUILD_VERSION,
            "target_keys": len(target_keys),
            "dump": dump_stats,
            "normalize": norm_stats.as_dict(),
            "identity": id_stats.as_dict(),
            "enrich": {
                "cefr_levels": enrich_report.cefr_levels,
                "cefr_unknown": enrich_report.cefr_unknown,
                "frequency_unknown": enrich_report.frequency_unknown,
            },
            "counts": counts,
        },
    )
    store.close()

    report = {
        "build_version": BUILD_VERSION,
        "target_keys": len(target_keys),
        "dump": dump_stats,
        "normalize": norm_stats.as_dict(),
        "identity": id_stats.as_dict(),
        "headwords": distinct,
        "written": written,
        "counts": counts,
        "cefr_levels": enrich_report.cefr_levels,
        "cefr_unknown": enrich_report.cefr_unknown,
        "frequency_unknown": enrich_report.frequency_unknown,
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {written} senses ({distinct} headwords) to {db_path}")
    print(f"report: {args.report}")
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
