# English-Polish Vocabulary Platform - Data Sources

Raw source datasets live in this directory. **They are immutable inputs**:
never edit, rename or re-export them (master_prompt.md section 46).

These files are intentionally NOT committed to Git (see `.gitignore`) because
the Wiktextract dump alone is ~2.7 GB. Provenance is documented here instead.

## Files

| File | Size | Role | Source |
|---|---|---|---|
| `raw-wiktextract-data.jsonl.gz` | ~2.7 GB | Primary lexical source: English entries, senses, glosses, **Polish translations** | Wiktextract / Kaikki export |
| `cefrj-vocabulary-profile-1.5.csv` | 228 KB | CEFR levels A1-B2 (headword, pos, CEFR) | CEFR-J Vocabulary Profile 1.5 |
| `octanove-vocabulary-profile-c1c2-1.0.csv` | 46 KB | CEFR C1/C2 vocabulary (headword, pos, CEFR, notes) | Octanove Vocabulary Profile C1/C2 1.0 |
| `NGSL_1.2_stats.csv` | 62 KB | Word frequency (lemma, rank, SFI, adjusted freq per million) | New General Service List 1.2 |
| `english-wordnet-2025-json/` | 70 MB | Open English WordNet 2025: synset JSON by POS + entry index | Open English WordNet 2025 |

## Verified initial inspection (2026-09-26)

- Wiktextract: gzipped JSONL, UTF-8, one JSON object per line; records carry
  `word`, `lang`, `pos`, `senses[]` (with `glosses`), `translations[]`
  (Polish via `code: "pl"`), categories, synonyms, etc.
- CEFR-J: CSV, header `headword,pos,CEFR,CoreInventory 1,CoreInventory 2,Threshold`,
  7,799 data rows.
- NGSL: CSV, header `Lemma,SFI Rank,SFI,Adjusted Frequency per Million (U)`,
  2,810 data rows.
- Octanove: CSV, header `headword,pos,CEFR,notes`, 2,137 data rows.
- WordNet 2025: per-POS synset files (`noun.*.json`, `verb.*.json`, `adj.*.json`,
  `adv.all.json`) keyed by synset id with `definition`, `example`, `hypernym`,
  `members`, `ili`; plus `entries-*.json` mapping lemmas to sense ids/synsets.

Detailed per-dataset schema analysis is produced in Phase 3
(`docs/data-source-inventory.md`).

## Derived/intermediate directories

Created by the pipeline (all Git-ignored):

- `data/intermediate/` - normalized source records
- `data/processed/` - merged, deduplicated master vocabulary
- `data/embeddings/` - embedding arrays and checkpoints
- `data/construction/` - SQLite construction database
