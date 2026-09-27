"""Phase 10 quality audit: priority scoring on real data (D012 follow-up).

Same methodology as the Phase 9 taxonomy audit (D011 addendum):

1. programmatic consistency checks over ALL prio-v1 rows;
2. deterministic stratified random samples for manual review.

Checks:
  A. stored level == level_for_score(score) for every row;
  B. score recomputed from stored components_json matches the stored score
     (internal consistency: store roundtrip + formula determinism);
  C. within strata of identical non-frequency components, score ordering
     follows the frequency component (no rank/score inversions);
  D. flagged senses score lower on average than unflagged ones;
  E. mean score gradient across CEFR runs the right way (A1 highest,
     C2 lowest among well-populated levels) without being deterministic;
  F. all-neutral senses (no frequency, CEFR, Polish, examples, gloss or
     WordNet evidence) sit at the neutral floor and are never VERY LOW
     unless flagged;
  G. slur/offensive/derogatory senses (hard markers) never reach VERY
     HIGH — penalty makes it structurally impossible;
  H. stratified samples (seed 42): per level, plus boundary strata
     (lowest VERY HIGH, highest VERY LOW, A1 VERY LOW, C2 HIGH).

Usage (from backend/ with uv):
    uv run python ../scripts/phase10_priority_audit.py
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.enrich.priority import PRIORITY_VERSION, level_for_score  # noqa: E402
from pipeline.storage.sqlite_store import ConstructionStore  # noqa: E402

DB_PATH = REPO / "data" / "construction" / "construction.sqlite"
SEED = 42
SAMPLES_PER_LEVEL = 12
BOUNDARY_N = 8
_TOL = 2e-4  # rounding tolerance for ordering checks


def _load_rows(store: ConstructionStore) -> list[dict]:
    cur = store.conn.execute(
        "SELECT sp.sense_key, sp.score, sp.level, sp.components_json, "
        "ms.headword_search, ms.cefr_level, ms.frequency_rank, ms.tags_json "
        "FROM sense_priorities sp JOIN master_senses ms "
        "ON ms.sense_key = sp.sense_key WHERE sp.version = ?",
        (PRIORITY_VERSION,),
    )
    rows = []
    for sense_key, score, level, comps, hw, cefr, rank, tags_json in cur:
        rows.append(
            {
                "sense_key": sense_key,
                "score": score,
                "level": level,
                "components": json.loads(comps),
                "headword": hw,
                "cefr": cefr,
                "rank": rank,
                "tags": json.loads(tags_json or "[]"),
            }
        )
    return rows


def _recompute(row: dict) -> float:
    c = row["components"]
    w = c["weights"]
    base = (
        w["frequency"] * c["frequency"]
        + w["learner"] * c["learner"]
        + w["polish"] * c["polish"]
        + w["quality"] * c["quality"]
    )
    return round(min(1.0, max(0.0, base * c["penalty_factor"])), 4)


def _is_all_neutral(row: dict) -> bool:
    i = row["components"]["inputs"]
    return (
        i["frequency_rank"] is None
        and i["cefr_level"] is None
        and i["translations"] == 0
        and i["examples"] == 0
        and i["gloss_tokens"] == 0
        and not i["wordnet_linked"]
        and not i["tags"]
    )


def _is_slur_class(row: dict) -> bool:
    return bool({"derogatory", "offensive", "slur"} & set(row["tags"]))


def _print_sample(rows: list[dict], title: str) -> None:
    print(f"  -- {title} --")
    for r in rows:
        c = r["components"]
        i = c["inputs"]
        print(
            f"    {r['score']:.4f} {r['level']:9s} {r['headword'][:22]:22s} "
            f"cefr={str(r['cefr'] or '-'):3s} rank={str(r['rank'] or '-'):>6s} "
            f"tr={i['translations']} ex={i['examples']} "
            f"wn={int(i['wordnet_linked'])} gl={i['gloss_tokens']:2d} "
            f"tags={','.join(i['tags']) or '-'}"
        )


def main() -> int:
    t0 = time.time()
    store = ConstructionStore(DB_PATH)
    rows = _load_rows(store)
    failures: list[str] = []
    print(f"auditing {len(rows)} {PRIORITY_VERSION} rows (seed {SEED})")

    # Orphan checks: exactly one row per sense, both directions.
    n_senses = store.count_senses()
    if len(rows) != n_senses:
        failures.append(f"row/sense mismatch: {len(rows)} rows vs {n_senses} senses")

    # A. stored level matches score thresholds.
    bad_level = [r for r in rows if r["level"] != level_for_score(r["score"])]
    print(f"A. level-threshold mismatches: {len(bad_level)}")
    if bad_level:
        failures.append(f"{len(bad_level)} level mismatches")

    # B. recompute from stored components.
    bad_recompute = [r for r in rows if abs(_recompute(r) - r["score"]) > 1e-9]
    print(f"B. recompute mismatches: {len(bad_recompute)}")
    if bad_recompute:
        failures.append(f"{len(bad_recompute)} recompute mismatches")

    # C. rank/score ordering within identical non-frequency strata.
    strata: dict[tuple, list[dict]] = {}
    for r in rows:
        c = r["components"]
        key = (c["learner"], c["polish"], c["quality"], c["penalty_factor"])
        strata.setdefault(key, []).append(r)
    inversions = 0
    for members in strata.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda r: r["components"]["frequency"])
        for a, b in zip(members, members[1:], strict=False):
            if b["score"] < a["score"] - _TOL:
                inversions += 1
    multi = sum(1 for m in strata.values() if len(m) > 1)
    print(f"C. ordering inversions: {inversions} across {multi} multi-sense strata")
    if inversions:
        failures.append(f"{inversions} frequency-ordering inversions")

    # D. flags lower the score on average.
    flagged = [r for r in rows if r["components"]["penalty_factor"] < 1.0]
    clean = [r for r in rows if r["components"]["penalty_factor"] == 1.0]
    mean_flagged = sum(r["score"] for r in flagged) / max(1, len(flagged))
    mean_clean = sum(r["score"] for r in clean) / max(1, len(clean))
    print(
        f"D. mean score flagged={mean_flagged:.3f} (n={len(flagged)}) "
        f"vs clean={mean_clean:.3f} (n={len(clean)})"
    )
    if flagged and mean_flagged >= mean_clean:
        failures.append("flagged senses do not score lower on average")

    # E. CEFR gradient of mean scores.
    by_cefr: dict[str, list[float]] = {}
    for r in rows:
        if r["cefr"]:
            by_cefr.setdefault(r["cefr"], []).append(r["score"])
    means = {k: sum(v) / len(v) for k, v in sorted(by_cefr.items()) if len(v) >= 100}
    print("E. mean score by CEFR (n>=100): " + ", ".join(f"{k}={v:.3f}" for k, v in means.items()))
    ordered = [k for k, _ in sorted(means.items(), key=lambda kv: -kv[1])]
    if ordered and (ordered[0] != "A1" or ordered[-1] != "C2"):
        failures.append(f"CEFR gradient wrong ends: {ordered}")

    # F. all-neutral senses: floor 0.35 LOW, never VERY LOW unflagged.
    neutral = [r for r in rows if _is_all_neutral(r)]
    neutral_levels = {}
    for r in neutral:
        neutral_levels[r["level"]] = neutral_levels.get(r["level"], 0) + 1
    print(f"F. all-neutral senses: {len(neutral)} at {neutral_levels}")
    bad_neutral = [r for r in neutral if r["level"] == "VERY LOW"]
    if bad_neutral:
        failures.append(f"{len(bad_neutral)} unflagged all-neutral senses at VERY LOW")

    # G. slur-class senses never reach VERY HIGH (hard marker, prio-v1.1).
    slur = [r for r in rows if _is_slur_class(r)]
    slur_vh = [r for r in slur if r["level"] == "VERY HIGH"]
    print(f"G. slur-class senses: {len(slur)}, at VERY HIGH: {len(slur_vh)}")
    if slur_vh:
        failures.append(f"{len(slur_vh)} slur-class senses at VERY HIGH")

    rng = random.Random(SEED)

    # G1. stratified random sample per level.
    by_level: dict[str, list[dict]] = {}
    for r in rows:
        by_level.setdefault(r["level"], []).append(r)
    print("H1. stratified random sample (seed 42):")
    for level in ("VERY HIGH", "HIGH", "MEDIUM", "LOW", "VERY LOW"):
        pool = sorted(by_level.get(level, []), key=lambda r: r["sense_key"])
        _print_sample(rng.sample(pool, min(SAMPLES_PER_LEVEL, len(pool))), level)

    # H2. boundary strata for manual review.
    vh = sorted(by_level.get("VERY HIGH", []), key=lambda r: r["score"])[:BOUNDARY_N]
    _print_sample(vh, "lowest VERY HIGH (weakest members)")
    vl = sorted(by_level.get("VERY LOW", []), key=lambda r: -r["score"])[:BOUNDARY_N]
    _print_sample(vl, "highest VERY LOW (strongest members)")
    a1_vl = sorted(
        [r for r in by_level.get("VERY LOW", []) if r["cefr"] == "A1"],
        key=lambda r: r["score"],
    )[:BOUNDARY_N]
    _print_sample(a1_vl, "A1 senses at VERY LOW (expect flagged junk)")
    c2_high = sorted(
        [r for r in by_level.get("HIGH", []) if r["cefr"] == "C2"],
        key=lambda r: -r["score"],
    )[:BOUNDARY_N]
    _print_sample(c2_high, "C2 senses at HIGH (must survive, section 14)")

    store.finish_run(
        store.begin_run("phase10-priority-audit"),
        {
            "seed": SEED,
            "rows_audited": len(rows),
            "failures": failures,
            "level_mismatches": len(bad_level),
            "recompute_mismatches": len(bad_recompute),
            "ordering_inversions": inversions,
            "all_neutral": len(neutral),
        },
    )
    store.close()
    print(f"done in {time.time() - t0:.1f}s")
    if failures:
        print("AUDIT FAILURES: " + "; ".join(failures))
        return 1
    print("AUDIT PASS (programmatic checks; samples above for manual review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
