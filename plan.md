# Implementation Plan

Phases follow master_prompt.md sections 76–105. Each phase is finished only
when its tests pass, documentation is updated and the phase commit exists.

Legend: `[ ]` todo · `[x]` done · phase status: TODO / IN PROGRESS / COMPLETE

---

## Phase 0 — Project Initialization
Status: **COMPLETE**

- [x] Inspect repository, all datasets, existing files
- [x] Verify tooling (Node, pnpm, Python, uv, PostgreSQL)
- [x] Establish directory structure (backend/, frontend/, docs/, pipeline placeholder)
- [x] Create documentation files (master.md, decision.md, current-state.md, architecture.md, plan.md, README.md)
- [x] Initialize backend (FastAPI, uv-managed)
- [x] Initialize frontend (Next.js, pnpm-managed)
- [x] Create docker-compose.yml (canonical dev-env config)
- [x] Create .env.example
- [x] Create initial testing structure (pytest suite)
- [x] Verify acceptance: repo starts, frontend builds, backend starts, database starts, health endpoint works, tests execute
- [x] Commit `feat: Initialize project structure and documentation` @ 2026-09-16T10:30:00 +0500

Acceptance criteria: all of the above verified.

---

## Phase 1 — Architecture Foundation
Status: **COMPLETE**

- [x] Backend module layout per domain (auth, students, vocabulary, search, sets, assignments, reviews, fsrs, imports, exports, admin) — routers registered, honest 501 stubs
- [x] Frontend route structure for /login /dashboard /vocabulary /students /sets /settings (+ dynamic segments) — enforced by tests
- [x] Structured logging with request correlation ID (console/JSON, sensitive-key masking)
- [x] Structured, consistent error handling (uniform envelope, no internals leaked; D005)
- [x] Health checks (liveness + database connectivity, real DB round-trip)
- [x] Configuration validation at startup (DATABASE_URL/APP_ENV/LOG_LEVEL/LOG_FORMAT)
- [x] Typed frontend API client mirroring the error envelope (ApiError)
- [x] Unit tests: backend 27 passed; frontend 19 passed (vitest)
- [x] Quality gates: ruff, mypy, pytest, tsc, eslint, next build
- [x] Update architecture.md, current-state.md, decision.md (D005), .env.example
- [x] Commit(s) dated 2026-09-17 (+0500)

Tests: tests/test_error_envelope.py, tests/test_middleware.py,
tests/test_settings.py (backend); tests/routes.test.ts,
tests/api-client.test.ts (frontend).

---

## Phase 2 — Database Foundation
Status: **COMPLETE**

- [x] Alembic setup (env.py wired to app settings; deterministic naming convention)
- [x] Core tables (25): teachers, teacher_sessions, students, vocabulary_senses, vocabulary_forms, sense_definitions, sense_translations, sense_examples, vocabulary_sources, sense_source_records, cefr_evidence, frequency_evidence, vocabulary_flags, wordnet_synsets, wordnet_relations, sense_wordnet_links, categories, sense_categories, sense_priorities, student_vocabulary, student_fsrs_states, review_events, vocabulary_sets, vocabulary_set_items, teacher_priority_overrides
- [x] UNIQUE(student_id, sense_id) constraint — proven by DB-level test
- [x] Indexes per section 42 (headword, CEFR, priority, POS, student+state, due_at, review time, translations, set items)
- [x] Migration up/down round-trip test; FK and uniqueness violation tests
- [x] Schema decisions recorded (D006)
- [x] Gates: ruff, mypy, pytest (40 passed)
- [x] Commit dated 2026-09-18 (+0500)

Tests: tests/test_migrations.py, tests/test_constraints.py.

---

## Phase 3 — Source Data Inspection
Status: **COMPLETE**

- [x] Streaming inspector for every dataset in data/raw/ (pipeline/sources/)
- [x] Machine-readable (data/source-inventory.json, Git-ignored) + human-readable (docs/data-source-inventory.md) reports
- [x] Format, size, record counts, schemas, fields, languages, anomalies recorded for all 5 sources
- [x] Full Wiktextract streaming pass: 10,913,996 lines, 0 malformed; English profile on 50k sample
- [x] Inspector unit tests (synthetic fixtures): 6 tests
- [x] Commit dated 2026-09-19 (+0500)

Key findings (full detail in docs/data-source-inventory.md):
- Wiktextract: 1,492,836 English entries; avg 2.8 senses/word; 100% gloss
  coverage in sample; Polish translation on 39.5% of words (avg 2.4 each);
  word-level (not sense-level) translations → gloss-alignment heuristic
  needed in Phase 5; rich tags (obsolete 7.3k, slang 5.9k in sample) feed flags.
- CEFR-J: 7,799 rows A1–B2, 0 duplicate headword+POS pairs; 167 slash-variant
  headwords need splitting.
- Octanove: 2,136 rows C1/C2; 58 duplicate pairs; 2 malformed POS values.
- NGSL: 2,809 lemmas, clean numeric data.
- WordNet 2025: 107,519 synsets (100% with definitions), 128,009 lemmas,
  88,075 hypernym relations.

---

## Phase 4 — Source Adapters
Status: **COMPLETE**

- [x] Shared normalized record contract + AdapterRun statistics (pipeline/records.py, section 45)
- [x] cefrj adapter (validation, slash-variant + duplicate warnings, exact provenance IDs)
- [x] octanove adapter (missing-POS/duplicate warnings, C1/C2 scope enforcement)
- [x] ngsl adapter (numeric validation, duplicate-lemma warnings)
- [x] wiktextract adapter (streaming, English filter, sense/tag/translation extraction, malformed accounting)
- [x] wordnet adapter (synsets, 16 typed relations, lemma→sense→synset links)
- [x] 13 unit tests on synthetic fixtures; real-data smoke runs match Phase 3 inventory exactly
- [x] Gates: pytest 59 passed; ruff/mypy clean
- [x] Commit dated 2026-09-20 (+0500)

Real-data verification: CEFR-J 7,799 processed/168 warnings; Octanove 2,136/61;
NGSL 2,809/0; WordNet 107,519 synsets + 125,249 relations + 185,129 links/0
failures; Wiktextract 100k-line sample: 10,869 processed, 89,131 non-English
or unusable skipped, 0 failed.

## Phase 5 — Normalization
Status: **COMPLETE**

- [x] Unicode/whitespace normalization with display-vs-search separation; NFD-invariant letters (ł, ø, ß…) handled (pipeline/normalize/clean.py)
- [x] Cross-source POS mapping (CEFR-J/Octanove verb-phrases, Wiktextract tags, WordNet letters) — total mapping, unknown → other
- [x] Gloss cleaning (qualifier parentheses, trailing markers); American-spelling preference helper
- [x] D007 translation sense-alignment heuristic (inline/cognate/token/position; confidences 0.95/0.5/0.7/0.35; versioned align-v1) + docs/translation-alignment.md
- [x] NormalizedSenseCandidate merge: Wiktextract senses + CEFR/frequency/WordNet word-level evidence attached, nothing discarded
- [x] 31 unit tests incl. BANK case; real-data smoke: 150k dump lines → 47,327 candidates, 31.5% with PL, BANK → 42 senses correctly separated
- [x] Gates: pytest 90 passed; ruff/mypy clean
- [x] Commit dated 2026-09-21 (+0500)

## Phase 6 — Sense Identity
Status: **COMPLETE**

- [x] Deterministic identity: (word, POS) groups + gloss-token clustering (equal/subset/Jaccard tiers; bias against over-merging) — D008
- [x] Stable unique sense_key `{word}|{pos}|digest12}` with guaranteed-collision-free resolution
- [x] Merged senses union provenance, translations, CEFR/frequency/WordNet evidence (deduped)
- [x] Tests (15): BANK two-senses acceptance, cross-source BANK merge, subset merge, genuine-difference, cross-POS separation, evidence union, determinism
- [x] Real-data smoke: 47,327 candidates → 41,686 master senses (11.9% dedup), 0 key collisions, BANK-noun → 28 senses (financial & river separate)
- [x] docs/sense-identity.md; D008 in decision.md
- [x] Gates: pytest 105 passed; ruff/mypy clean
- [x] Commit dated 2026-09-22 (+0500)

## Phase 7 — CEFR and Frequency Integration
Status: **COMPLETE**

- [x] CEFR reconciliation: POS-aware evidence, single/unanimous/conflict tiers (0.85/0.95/0.50), higher-level-on-conflict + conflict flag, unknown stays NULL — D009
- [x] Frequency integration: best-rank dedup, frequency bands as display metadata only (separate from priority)
- [x] Enrichment applier + report (levels distribution, conflict/unknown counts)
- [x] SQLite construction DB: idempotent batched upserts, run log, QC summary computed from stored data
- [x] Tests (17): A1–C2 parametrized, unknown, POS-mismatch, conflict flagging, band boundaries, duplicate counting, SQLite roundtrip/idempotence
- [x] Real-data smoke: 41,690 senses; CEFR 57.9% (A1 8,230 / A2 5,019 / B1 5,481 / B2 4,037 / C1 858 / C2 512), 970 conflicts preserved; freq 41.2%; PL 31.6%
- [x] Gates: pytest 122 passed; ruff/mypy clean
- [x] Commit dated 2026-09-23 (+0500)

## Phase 8 — WordNet and Semantic Relationships
Status: **COMPLETE**

- [x] Synset catalog: 107,519 synsets + 125,249 relations grouped synonym /
  hypernym / hyponym / related (unknown types preserved verbatim, no reverse
  edges invented); stored in construction DB keyed by WordNet's own ids (D010)
- [x] Sense linking (wnlink-v1): POS-gated, deterministic — monosemous
  assertion 0.80, definition-match (D008 tokens + light stemmer) ≥ 0.60,
  shared-tokens tier 0.70; never fabricate, all misses counted
- [x] Construction DB: wordnet_synsets / wordnet_relations /
  sense_wordnet_links tables, idempotent upserts, QC counters
- [x] Tests (25): relation grouping, catalog dedup, POS gating (incl. `n-1`
  suffix and satellite `s`), ambiguity ties, stemmer chains, SQLite roundtrip
- [x] Real-data smoke: 41,690 senses → 13,259 linked (31.8%); per-POS noun
  38.8% / verb 26.8% / adj 33.9% / adv 39.2%; per-CEFR A1 26.5% → C2 37.5%;
  representative-sense spot-checks (bank, bright, quickly) correct
- [x] Gates: pytest 147 passed; ruff/mypy clean
- [x] Commit dated 2026-09-24 (+0500)

## Phase 9 — Thematic Taxonomy
Status: **COMPLETE**

- [x] Fixed versioned hierarchy: 24 top categories + subcategories per
  §18 (170 nodes), stored as node rows shared by UI and PG import
- [x] Deterministic classifier (§50: no LLM): corroborated headword tier
  0.90, WordNet hypernym-chain tier 0.85 (reuses Phase 8 links + catalog),
  multi-keyword gloss tier 0.70–0.80; best evidence per (category, sub) wins
- [x] Multiple categories per sense (§85); sub hit assigns parent top;
  uncategorized counted, never forced; full-refresh idempotent store
- [x] Quality audit (D011 addendum): random-sample precision review
  surfaced single-keyword gloss noise (removed), prone polysemous keywords
  (pruned), stemmer over-stemming (>= 3-char guard, wnlink-v1.1) and
  word-level headword misassignment (gloss corroboration, tax-v1.2);
  coverage 60.1% → 18.5% with sub-level precision near 1.0
- [x] Tests (21 taxonomy + 26 wordnet incl. stemmer guard): hierarchy
  integrity, all tiers, corroboration on/off, multi-category, determinism,
  spec-word classification (§85 list), SQLite roundtrip
- [x] Real-data smoke (scripts/phase9_taxonomy_smoke.py): 7,702 / 41,690
  senses categorized (18.5%), 12,599 assignments, 2,196 multi-category,
  all 24 categories populated; audited sample clean (sleep → daily-rest,
  football → sport-disciplines, terminal → travel-airports, thunder →
  weather)
- [x] Gates: pytest 168 passed; ruff/mypy clean
- [x] Commit dated 2026-09-25 (+0500)

## Phases 10–29 (queued; detailed tasks added as each starts)
10. Vocabulary priority (documented deterministic formula, versioned)
11. Examples & quality indicators
12. Embeddings (BGE-M3, batched, resumable, pgvector + HNSW) — **requires D004 resolved**
13. PostgreSQL vocabulary import (validated, batched, transactional, reports)
14. Search backend (exact/full-text/semantic/hybrid + filters + sorting + pagination, benchmarked)
15. Teacher authentication (Argon2id, server-side sessions)
16. Vocabulary UI (dense spreadsheet table, TanStack Table)
17. Students (list/create/edit/deactivate/profile)
18. Assignment (single/bulk/set/search-result; duplicate prevention; not-assigned filter)
19. Vocabulary sets
20. FSRS (library-backed; HARD→Again MEDIUM→Hard EASY→Good; fixtures)
21. Review interface (one-at-a-time, keyboard shortcuts, duplicate-submission guard)
22. Dashboard (per-student due/overdue/learning/reviewing/mastered)
23. Import/export (CSV/XLSX/JSON, validated import)
24. Security hardening pass
25. Performance pass (realistic volume)
26. Backups & restoration (real restore test)
27. Full end-to-end testing (incl. section-59 acceptance workflow in Playwright)
28. Production readiness (clean-environment verification)
29. Final acceptance report (docs/final-acceptance-report.md)

---

## Open items

- [ ] D004: install pgvector via StackBuilder GUI on this machine before Phase 12
  (fallback documented in decision.md). Owner: user + agent verification.
