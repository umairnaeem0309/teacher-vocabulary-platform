# Vocabulary Construction Pipeline

Implemented in Phases 3–13 (see plan.md). Target layout:

```text
pipeline/
  sources/        # one adapter per dataset (wiktextract, cefrj, ngsl, octanove, wordnet)
  normalize/      # lexical normalization
  identity/       # sense identity / deduplication
  enrich/         # CEFR, frequency, WordNet, taxonomy, priority, quality
  embeddings/     # BGE-M3 generation (batched, resumable)
  qc/             # quality control and reports
  construction/   # SQLite construction DB management
  import/         # PostgreSQL production import
```

Raw inputs stay in `data/raw/` (immutable). Intermediate and processed
outputs go to `data/intermediate/`, `data/processed/`, `data/embeddings/`
and the SQLite construction DB in `data/construction/` — all Git-ignored.

Nothing is implemented yet; Phase 0 explicitly excludes application
features and ETL (master_prompt.md section 76).
