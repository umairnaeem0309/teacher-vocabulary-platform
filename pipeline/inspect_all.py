"""Phase 3 entry point: inspect every supplied dataset and write the
machine- and human-readable source inventory (section 79).

Usage (from repository root):
    uv run --project backend python -m pipeline.inspect_all
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import date
from pathlib import Path

from pipeline.sources.csv_sources import inspect_cefrj, inspect_ngsl, inspect_octanove
from pipeline.sources.wiktextract_inspect import profile_wiktextract
from pipeline.sources.wordnet_inspect import inspect_wordnet_dir

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT_JSON = ROOT / "data" / "source-inventory.json"
OUT_MD = ROOT / "docs" / "data-source-inventory.md"

# `vocab_platform` counts as tracked context even though raw data is ignored.
GITIGNORED = True


def _fmt_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes} B"
        num_bytes /= 1024
    return f"{num_bytes:.1f} GB"


def main() -> int:
    inventory: dict[str, object] = {
        "generated": date.today().isoformat(),
        "python": platform.python_version(),
        "sources": {},
    }
    sources = inventory["sources"]  # type: ignore[assignment]

    print("== CEFR-J ==", flush=True)
    p = RAW / "cefrj-vocabulary-profile-1.5.csv"
    sources["cefrj"] = {"file": str(p.name), "size_bytes": p.stat().st_size,
                        **inspect_cefrj(p)}

    print("== Octanove ==", flush=True)
    p = RAW / "octanove-vocabulary-profile-c1c2-1.0.csv"
    sources["octanove"] = {"file": str(p.name), "size_bytes": p.stat().st_size,
                           **inspect_octanove(p)}

    print("== NGSL ==", flush=True)
    p = RAW / "NGSL_1.2_stats.csv"
    sources["ngsl"] = {"file": str(p.name), "size_bytes": p.stat().st_size,
                       **inspect_ngsl(p)}

    print("== WordNet (70 MB; one file at a time) ==", flush=True)
    wn_dir = RAW / "english-wordnet-2025-json"
    sources["wordnet"] = {"file": "english-wordnet-2025-json/",
                          "size_bytes": sum(f.stat().st_size for f in wn_dir.glob("*.json")),
                          **inspect_wordnet_dir(wn_dir)}

    print("== Wiktextract (streaming 2.7 GB; several minutes) ==", flush=True)
    p = RAW / "raw-wiktextract-data.jsonl.gz"
    sources["wiktextract"] = {"file": str(p.name), "size_bytes": p.stat().st_size,
                              **profile_wiktextract(p)}

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(inventory, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render_markdown(inventory), encoding="utf-8")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")
    return 0


def render_markdown(inv: dict) -> str:
    s = inv["sources"]
    w = s["wiktextract"]
    wn = s["wordnet"]
    cj, oc, ng = s["cefrj"], s["octanove"], s["ngsl"]
    lines: list[str] = []
    ap = lines.append

    ap("# Data Source Inventory (Phase 3)")
    ap("")
    ap(f"Generated: {inv['generated']} · Python {inv['python']} · "
       f"all files under `data/raw/` (immutable inputs, Git-ignored, "
       f"see data/raw/README.md)")
    ap("")
    ap("| Dataset | Size | Records | Role |")
    ap("|---|---|---|---|")
    ap(f"| raw-wiktextract-data.jsonl.gz | {_fmt_size(w['size_bytes'])} | "
       f"{w['total_records']:,} lines (all languages) | lexical core: senses, "
       f"glosses, **Polish translations** |")
    ap(f"| cefrj-vocabulary-profile-1.5.csv | {_fmt_size(cj['size_bytes'])} | "
       f"{cj['record_count']:,} | CEFR A1–B2 evidence |")
    ap(f"| octanove-vocabulary-profile-c1c2-1.0.csv | {_fmt_size(oc['size_bytes'])} | "
       f"{oc['record_count']:,} | CEFR C1/C2 evidence |")
    ap(f"| NGSL_1.2_stats.csv | {_fmt_size(ng['size_bytes'])} | "
       f"{ng['record_count']:,} | frequency evidence |")
    ap(f"| english-wordnet-2025-json/ | {_fmt_size(wn['size_bytes'])} | "
       f"{wn['synset_count_total']:,} synsets | semantic relationships |")
    ap("")

    ap("## 1. Wiktextract / Kaikki (primary source)")
    ap("")
    ap("- Format: gzipped JSONL, UTF-8; **streamed** (never fully in RAM, "
       "sections 47–48).")
    ap(f"- Total lines: **{w['total_records']:,}** "
       f"({w['duration_seconds']}s streaming pass).")
    ap(f"- Malformed (unparsable JSON): **{w['malformed_records']:,}** "
       f"({100*w['malformed_records']/max(w['total_records'],1):.4f}%) — will be "
       f"reported, never silently dropped (section 45).")
    ap("- Language distribution (top): " + ", ".join(
        f"{k} {v:,}" for k, v in w["language_distribution_top"].items()))
    ap(f"- English entries: **{w['english_records']:,}**")
    ap("")
    ap("### English-entry profile (50,000-entry sample)")
    ap("")
    st = w["sample_sense_stats"]
    ap("- POS distribution: " + ", ".join(
        f"`{k}` {v:,}" for k, v in w["english_pos_distribution"].items()))
    ap(f"- Senses per word (avg): **{st['avg_senses_per_word']}** → the "
       f"sense-level requirement (section 9) matters at scale.")
    ap(f"- Gloss coverage: **{st['gloss_coverage_pct']}%** of senses carry a "
       f"gloss ({st['senses_with_gloss']:,}/{st['senses_total']:,}).")
    pc = w["sample_polish_coverage"]
    ap(f"- **Polish coverage: {pc['words_with_pl_translation_pct']}%** of sampled "
       f"English words have ≥1 Polish translation "
       f"(avg {pc['avg_pl_translations_per_covered_word']} per covered word). "
       f"Remaining entries keep English-only definitions (section 110: never "
       f"deleted for missing Polish).")
    ap("- Field coverage (share of sampled entries with the field present): "
       + ", ".join(f"`{k}` {v}" for k, v in list(w["sample_field_coverage"].items())[:18]))
    ap("- Top translation target languages: " + ", ".join(
        f"{k} {v:,}" for k, v in list(w["sample_translation_codes_top"].items())[:8]))
    ap("- Most common sense tags: " + ", ".join(
        f"`{k}` {v:,}" for k, v in list(w["sample_sense_tags_top"].items())[:12]))
    ap("")
    ap("### ETL implications")
    ap("")
    ap("1. Filter `lang == \"English\"` early; ~half the dump is other languages.")
    ap("2. Translations live at **word level** (`translations[]`, `code: \"pl\"`), "
       "not per sense — sense/translation alignment needs gloss heuristics "
       "(documented in Phase 5, D-decision to follow).")
    ap("3. Sense tags (`archaic`, `obsolete`, `rare`…) feed `vocabulary_flags` "
       "and priority signals directly.")
    ap("")

    ap("## 2. CEFR-J Vocabulary Profile 1.5")
    ap("")
    ap(f"- Columns: `{', '.join(cj['columns'])}`; {cj['record_count']:,} rows.")
    ap("- CEFR distribution: " + ", ".join(
        f"{k}: {v:,}" for k, v in cj["cefr_distribution"].items()))
    ap("- POS values: " + ", ".join(
        f"`{k}` {v:,}" for k, v in cj["pos_distribution"].items()))
    ap(f"- Multiword headwords: {cj['multiword_headwords']:,}; slash-variant "
       f"headwords (e.g. `a.m./A.M./am/AM`): {cj['slash_variant_headwords']:,} — "
       f"normalization must split variants (Phase 5).")
    ap(f"- Duplicate (headword, POS) pairs: **{cj['duplicate_headword_pos_pairs']}**"
       + (f" e.g. {'; '.join(cj['duplicate_examples'][:5])}" if cj["duplicate_examples"] else "")
       + " — CEFR conflict policy needed (section 14; Phase 7).")
    ap(f"- Auxiliary columns mostly empty: {cj['auxiliary_column_fill']}.")
    ap("")

    ap("## 3. Octanove C1/C2 Vocabulary Profile 1.0")
    ap("")
    ap(f"- Columns: `{', '.join(oc['columns'])}`; {oc['record_count']:,} rows.")
    ap("- CEFR distribution: " + ", ".join(
        f"{k}: {v:,}" for k, v in oc["cefr_distribution"].items()))
    ap("- POS values: " + ", ".join(
        f"`{k}` {v:,}" for k, v in oc["pos_distribution"].items()))
    ap(f"- Notes filled: {oc['notes_filled']:,}; multiword: {oc['multiword_headwords']:,}; "
       f"duplicate (headword, POS): {oc['duplicate_headword_pos_pairs']}.")
    ap("")

    ap("## 4. NGSL 1.2 frequency stats")
    ap("")
    ap(f"- Columns: `{', '.join(ng['columns'])}`; {ng['record_count']:,} rows.")
    ap(f"- Rank range: {ng['rank_range'][0]:,}–{ng['rank_range'][1]:,}; "
       f"frequency/million range: {ng['freq_per_million_range'][0]:,.0f}–"
       f"{ng['freq_per_million_range'][1]:,.0f}.")
    ap(f"- Unparsable numeric rows: {ng['unparsable_numeric_rows']}; "
       f"multiword lemmas: {ng['multiword_lemmas']:,}; capitalized: "
       f"{ng['capitalized_lemmas']:,}; duplicate lemmas: "
       f"{ng['duplicate_lemmas']}"
       + (f" ({'; '.join(ng['duplicate_examples'][:5])})" if ng["duplicate_examples"] else "")
       + " — keep highest-frequency row per lemma (Phase 7 rule).")
    ap("")

    ap("## 5. Open English WordNet 2025")
    ap("")
    ap(f"- {wn['synset_file_count']} synset files + {wn['entry_file_count']} entry "
       f"index files + frames.json ({wn['verb_frames_count']} verb frames).")
    ap(f"- Synsets: **{wn['synset_count_total']:,}**; definitions on "
       f"{wn['synsets_with_definition']:,}; examples on "
       f"{wn['synsets_with_example']:,}; ILI on {wn['synsets_with_ili']:,}.")
    ap("- Synsets by POS group: " + ", ".join(
        f"{k} {v:,}" for k, v in wn["synsets_by_pos_group"].items()))
    ap("- Relations available: " + ", ".join(
        f"`{k}` {v:,}" for k, v in wn["relation_counts"].items()))
    ap(f"- Entry index: {wn['entry_lemma_count']:,} lemmas → "
       f"{wn['entry_sense_links_total']:,} sense links; "
       f"{wn['entry_lemmas_with_multiple_pos']:,} lemmas span multiple POS.")
    ap("")

    ap("## 6. Cross-source integration notes")
    ap("")
    ap("- Join keys differ: CEFR/Octanove use headword+POS strings; NGSL uses "
       "lemmas; Wiktextract uses entry words; WordNet uses synset IDs. Sense "
       "identity (Phase 6) is the only safe join point — never raw spellings "
       "(section 9).")
    ap("- CEFR evidence = CEFR-J (A1–B2) + Octanove (C1/C2) + limited Wiktextract "
       "category hints; conflicts preserved per source (section 14).")
    ap("- Frequency evidence = NGSL ranks/SFI; word-level, so senses of one word "
       "share word frequency until sense-frequency estimation exists (Phase 10 "
       "priority handles this, section 16).")
    ap("- The 2.7 GB dump streams at roughly "
       f"{w['total_records']/max(w['duration_seconds'],1):,.0f} records/s on this "
       "machine — full ETL passes are feasible (checkpointed, section 125).")
    ap("")
    ap("Machine-readable twin: `data/source-inventory.json` "
       "(Git-ignored like all generated data artifacts).")
    ap("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
