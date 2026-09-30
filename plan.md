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

## Phase 10 — Vocabulary Priority
Status: **COMPLETE**

- [x] Documented, deterministic, versioned formula (prio-v1, D012,
  docs/priority-scoring.md): `score = (0.35·frequency + 0.15·learner +
  0.20·polish + 0.30·quality) × penalty` — never CEFR alone, never raw
  frequency alone (§86); multiple signals with full component breakdown
  stored (§16)
- [x] Components: NGSL-tuned frequency curve rank^-0.07 (far-tail floor,
  missing → neutral); CEFR as mild learner relevance A1 1.0 → C2 0.55
  (never disqualifying, §14); Polish usefulness = mean D007 confidence
  (missing → neutral 0.5, not zero, §127); quality = examples + gloss
  depth + WordNet link; flag penalty hard ×0.5 / soft ×0.75 each, floor
  0.25, applied directly so VERY LOW is reachable
- [x] Fixed quantile-free levels VERY HIGH ≥ 0.70 / HIGH ≥ 0.55 /
  MEDIUM ≥ 0.40 / LOW ≥ 0.25 / VERY LOW below; all-neutral floor 0.35 LOW
- [x] Construction DB: sense_priorities keyed (sense_key, version) —
  new versions add rows, history never destroyed (§86)
- [x] Tests (18): component curves, weights sum, all-neutral floor,
  penalty semantics, thresholds, C2-not-disqualified, missing-signals
  neutrality, explainability round-trip, determinism, version history
- [x] Real-data smoke (scripts/phase10_priority_smoke.py): 41,690 senses
  scored; prio-v1.1: VERY HIGH 3,814 / HIGH 17,109 / MEDIUM 11,860 /
  LOW 5,266 / VERY LOW 3,641; per-CEFR gradient A1 (2,294 VERY HIGH,
  104 VERY LOW) → C2 (0 VERY HIGH, 23 VERY LOW); top `have` 0.853,
  bottom junk `aa` 0.110
- [x] Quality audit (D012 addendum, scripts/phase10_priority_audit.py):
  stratified samples + programmatic checks surfaced slur senses un-
  penalized (brown slur sense at VERY HIGH) and raw gloss token counting
  overstating depth ("a lady s maid" → 4 tokens); fixed in prio-v1.1
  (slur-class hard markers, significant-token gloss depth), history kept
  (prio-v1 rows survive); post-fix audit PASS with 0 anomalies
- [x] Gates: pytest 189 passed; ruff/mypy clean
- [x] Commits dated 2026-09-26 / 2026-09-27 (+0500)

## Phase 11 — Examples & Quality Indicators
Status: **COMPLETE**

- [x] Example integration (pipeline/enrich/examples.py, ex-v1, D013):
  Wiktextract sense examples + WordNet synset examples (via Phase 8
  links) cleaned, deduplicated casefold-first-wins, source-ordered,
  capped at 5/sense, per-row provenance; full-refresh sense_examples
  table (sense_key, position, text, source)
- [x] Quality indicators (pipeline/enrich/quality.py, qual-v1, D013):
  the §87 minimum set — translation available/confidence, definition
  available, example available, CEFR available, frequency available,
  category confidence, composite sense_confidence (0.30/0.25/0.20/0.15/
  0.10) — deterministic, missing evidence = 0.0, never invented
- [x] sense_confidence kept separate from priority (D013): evidence
  coverage view, not teaching rank; incomplete senses retained (§87)
- [x] Tests (22): cleaning bounds, dedup, cap, source order,
  determinism, indicator semantics (full/zero/clamps/saturation),
  batch report, JSON stability, store roundtrip + replace/refresh
- [x] Real-data smoke (scripts/phase11_quality_smoke.py): 52,824
  examples for 25,693 senses (44,061 wiktextract + 8,763 wordnet; 3,271
  unclean, 36 duplicate, 3,836 over-cap dropped); indicators for all
  41,690 senses — translation 13,162, definition 41,688, example 25,693,
  CEFR 24,137, frequency 17,161, category 7,702, mean sense_confidence
  0.5089; 1 zero-evidence sense retained, none deleted (§87)
- [x] Gates: pytest 211 passed; ruff/mypy clean
- [x] Commit dated 2026-09-27 (+0500)

## Phase 12 — Embeddings
Status: **COMPLETE (code, tests, docs)** — full 41,690-sense generation
RUNNING detached since 2026-09-28 (measured ~0.75 senses/s on real texts
→ ≈15h; resumable, checkpointed, safe to interrupt; progress in
data/construction/emb-v1_checkpoint.json, method in docs/embeddings.md).

- [x] D014: model lock BAAI/bge-m3 (1024-dim, L2-normalized, cosine),
  recipe emb-v1 `headword | pos | gloss | ex1 | ex2` (max 2 examples,
  no metadata per §88), text_sha256 skip/re-embed guard, one-version
  storage (no history — rebuildable derived view)
- [x] pipeline/enrich/embeddings.py: deterministic sorted-order batch
  generation, immutable-snapshot checkpoints (dataclasses.replace),
  lazy singleton EmbeddingModel (cache data/models)
- [x] pipeline/storage/pg_store.py: ensure_sense_rows (idempotent
  v0-bootstrap, app-generated uuid4 per D006), existing_embedding_shas,
  upsert_embeddings (CAST(:emb AS vector)), delete_other_versions,
  count_embeddings, nearest_senses (HNSW cosine)
- [x] Migration 7b2c91a4e8f5: sense_embeddings vector(1024),
  UNIQUE(sense_id, embedding_version), HNSW vector_cosine_ops index;
  EXPECTED_TABLES updated
- [x] Tests (13): FakeModel recipe/skip/resume/checkpoint/determinism
  + 2 PG tests (roundtrip+nearest, delete_other_versions);
  test_migrations strict table test extended
- [x] Real-data smoke (--limit 96 --probes): rows=96 versions=1;
  re-run idempotent (96/96 skipped_unchanged, 0 re-embedded); checkpoint
  resume verified; probes uninformative at limit=96 (pool = lowest-rank
  a–about senses) — judge neighbor quality after full run
- [x] BGE-M3 weights sha256-verified (b5e0ce34…daad38) into HF cache;
  downloaded via ModelScope mirror (HF CDN stalled repeatedly); loads
  offline; throughput measured ~2.2 texts/s CPU
- [x] docs/embeddings.md (§88 deliverable: instructions, recipe,
  versioning, mirror notes)
- [x] Gates: pytest 231 passed; ruff/mypy clean
- [x] Commit dated 2026-09-27 (+0500)

## Phase 13 (section 89: PostgreSQL vocabulary import) — COMPLETE 2026-09-28

- [x] pipeline/storage/pg_import.py (import-v1): validated, batched,
  single-transaction import; root rows upserted by sense_key (UUIDs and
  embedding FKs preserved across re-imports); children delete-refreshed;
  orphans/duplicates/unmapped tags reported, never dropped
- [x] collapse_cefr: deterministic lowest-(cefr,pos_raw) survivor for the
  6,259 duplicate (sense, source) statements (6,684 collapsed on real data)
- [x] Migration c3d94a71b6e2: sense_priorities PK (sense_id) ->
  (sense_id, version) — Phase 2 schema could not represent D012 priority
  history; ORM updated to match
- [x] refresh_priority_columns: denormalized priority_* on
  vocabulary_senses mirror prio-v1.1 (41,687 rows populated); versioned
  table remains source of truth (section 86)
- [x] scripts/phase13_import.py + phase13_verify.py; real import:
  41,687/41,690 inserted (3 junk rows rejected + reported), re-import
  idempotent (inserted=0, updated=41,687)
- [x] Tests (17): validation/normalize/collapse/report unit tests + PG
  roundtrip, idempotent re-import, UUID preservation, delete-refresh,
  rollback safety, priority backfill; test_constraints source key made
  session-unique (isolation)
- [x] test_migrations roundtrip sandboxed: disposable vocab_scratch_* DB
  (created/dropped per run), env.py programmatic URL override;
  **downgrade may never target the dev DB** (it wiped data twice — D015)
- [x] Stale-checkpoint guard in phase12 script: resume verifies
  checkpointed senses are actually stored; restarts fresh on mismatch
- [x] Gates: pytest 251 passed; ruff/mypy clean
- [x] Full embedding generation relaunched (detached, ~15h; per-batch
  persistence verified live: checkpoint N -> N×32 rows)
- [x] Commit dated 2026-09-28 (+0500)

## Phase 14 (sections 20–22: four-layer search) — COMPLETE 2026-09-29

- [x] Migration a7f3b2c9d4e1: generated tsvector columns on
  vocabulary_senses (A-weighted headword, B-weighted definition preview),
  sense_translations, sense_definitions + GIN indexes; ORM updated
- [x] pipeline/search/engine.py: Layer 1 exact/prefix (headword+forms) +
  weighted FTS (senses, Polish translations, definitions); Layer 2 filters
  composed in SQL (CEFR/POS/priority/category subtree/bands/flags/student
  assignment+state+due/difficulty/teacher overrides); Layer 3 semantic
  (BGE-M3 query embed, HNSW cosine, never embeds rows at search time);
  Layer 4 hybrid RRF blend 0.60/0.35/0.05 + prefix floor (D016, docs/search.md)
- [x] Two-stage lexical fallback: strict multi-word query retries loose
  OR on zero hits (§21 topic phrases answer; precision preserved)
- [x] Browse semantics: empty query + non-relevance sorts are full-set
  SQL-ordered pages (fixed lex-score truncation bug before Python re-sort)
- [x] API: POST /api/v1/vocabulary/search + GET .../search/filters;
  request/response Pydantic models; stub test replaced (error envelope)
- [x] HNSW operational rule: rebuild index after bulk loads (--reindex
  flag on phase12 script); incremental-graph recall failure diagnosed
  (self distance 0.0 direct, absent from index top-50 at ef_search=200)
- [x] Tests (21): ranking units (RRF/metadata/weights/determinism/exact-
  beats-semantic), API lexical/browse/pagination/determinism, §21 queries
  (all 6 return hits), §22 assignment filter with real student rows
  (assigned vs NOT ASSIGNED, in SQL), semantic self-match (sha-verified
  recipe from construction.sqlite), hybrid blend + rank provenance;
  semantic tests skip cleanly while the Phase 12 run is in progress
- [x] scripts/phase14_search_benchmark.py: per-mode latency + top-3
  probes; numbers captured in docs/search.md (inflated ~2x by the
  concurrent embedding run, stated honestly)
- [x] Docs: D016, docs/search.md, current-state.md, architecture.md
- [x] Gates: pytest all green (incl. 21 search tests), ruff/mypy clean
- [x] Commit dated 2026-09-29 (+0500)

## Phase 15 (section 91: teacher authentication) — COMPLETE 2026-09-29

- [x] app/core/auth.py: Argon2id hashing (argon2-cffi defaults), 32-byte
  opaque session tokens stored as SHA-256 hashes (never plaintext), 24h
  TTL, lazy pruning of expired sessions, idempotent revocation,
  registration validation (email/name/password policy)
- [x] Endpoints replacing stubs: POST /auth/bootstrap (first teacher
  only; 403 bootstrap_closed forever after), POST /auth/login (no user
  enumeration + decoy hash timing), GET /auth/session (§40 dependency
  reference), POST /auth/logout (server-side revocation + cookie clear)
- [x] Cookie: session_token, HttpOnly, SameSite=Lax, Secure in
  production/staging, Max-Age = TTL; app.state.settings wired
- [x] Tests (13): §91 checklist — valid login, invalid password,
  expired session (dead + pruned), unauthorized request, logout —
  plus bootstrap closure, cookie flags, hash-at-rest (token never in
  DB), garbage cookie, inactive teacher, anti-enumeration, validation
- [x] Live bug caught: lazy prune rolled back on a non-committing
  connection; resolve now runs in engine.begin()
- [x] Gates: pytest 284 passed; ruff/mypy clean
- [x] Docs: D017, current-state.md, architecture.md, .env.example
- [x] Commit dated 2026-09-29 (+0500)

## Phase 16 (section 23/54: vocabulary UI + browse/detail API) — COMPLETE 2026-09-29

- [x] GET /api/v1/vocabulary — filtered browse, a GET wrapper over the
  Phase 14 engine (identical coercion/sort/pagination; parity-tested
  against POST /vocabulary/search; D018)
- [x] GET /api/v1/vocabulary/{sense_id} — full detail (forms,
  definitions, translations, examples, categories, frequency evidence,
  priority versions); 404 envelope for unknown/invalid ids
- [x] TanStack Query + TanStack Table installed (pnpm; table via the
  official `legacy` v8-compat subpath of v9 — D018)
- [x] Vocabulary workbench page: dense 8-column table (headword, POS,
  CEFR, Polish, definition, priority, frequency, score), search box,
  mode selector, sortable headers, SQL-side pagination, row selection
  (bulk actions land with phases 18/19)
- [x] Filter sidebar driven by /search/facets (CEFR, POS, priority,
  priority-min, category, frequency band, max rank, flags) — all
  composed server-side per §22
- [x] URL-driven state (q/mode/sort/filters/page): shareable views,
  lossless round-trip, unit-tested (5 tests)
- [x] Sense detail page (all relation lists + provenance) wired to the
  new endpoint; login page real (POST /auth/login); session bar with
  logout on workbench pages
- [x] Live verification: CORS preflight + credentialed cookie flow from
  :3000 → :8737, all pages 200, headless Chrome hydration of login and
  workbench; semantic recall re-verified after final HNSW rebuild
- [x] Embedding run COMPLETED this phase (batch 1303/1303, 41,690
  embeddings, versions=1); --reindex executed over the full corpus
  (262s); bank self-recall confirmed at 0.054s query time
- [x] Gates: backend 292 passed, ruff/mypy clean; frontend tsc, eslint,
  vitest 24/24, next build clean
- [x] Docs: D018, current-state.md, architecture.md
- [x] Commit dated 2026-09-29 (+0500)

## Phases 17–29 (queued; detailed tasks added as each starts)
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

- [x] D004: pgvector — RESOLVED 2026-09-27 (StackBuilder no longer ships
  pgvector; community prebuilt 0.8.6 for PG 17 installed and verified.
  See D004 addendum. Production must replace with a trusted build.)
