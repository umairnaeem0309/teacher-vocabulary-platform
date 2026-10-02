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
- [x] Create docker-compose.yml (canonical dev-env config) — REMOVED 2026-10-02 with the Dockerfiles; see D026
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

## Phase 17 (section 27/39/40: student management) — COMPLETE 2026-09-29

- [x] app/core/students.py: service layer (§27 logic out of handlers;
  §40 isolation by WHERE-scoping teacher_id — foreign ids 404;
  PATCH semantics via model_fields_set; per-teacher email uniqueness;
  soft delete preserving all learning history — D019)
- [x] Endpoints (all teacher-authenticated, replacing Phase 4 stubs):
  GET /students (+include_inactive), POST /students,
  GET/PATCH /students/{id}, PATCH /students/{id}/status
  (deactivate/reactivate/delete), GET /students/{id}/vocabulary
  (assigned senses + learning state + FSRS due/reps)
- [x] Frontend: students list (create, show-deactivated toggle,
  deactivate/reactivate), profile page (edit with PATCH semantics,
  assigned-vocabulary table with due dates, delete with explicit
  confirmation per §27), typed students-client.ts
- [x] Tests (6): §27 lifecycle (create/edit/deactivate/reactivate/
  soft-delete + row-survival proof), §40 auth on every endpoint,
  §40 cross-teacher isolation (foreign id 404 on read/edit/status/
  vocabulary/list), validation, empty + populated vocabulary views;
  envelope stub test replaced (endpoint real now)
- [x] Live verification 9/9: login → create → list → edit →
  deactivate → reactivate → soft delete → 404 after delete → 401
  unauthenticated; test rows cleaned up
- [x] Gates: backend ruff/mypy clean, students+envelope 11 passed;
  frontend tsc/eslint clean, vitest 24/24, next build clean
- [x] Docs: D019, current-state.md, architecture.md
- [x] Commit dated 2026-09-29 (+0500)

## Phase 18 (sections 28–31: assignment, duplicates, not-assigned) — COMPLETE 2026-09-30

- [x] app/core/assignments.py: single/bulk assignment (one endpoint,
  1..1000 senses) with §29 layered duplicate prevention — application
  pre-check + UNIQUE(student_id, sense_id) backstop (row-count proven);
  §29 report (selected/new/already_assigned/failed); reactivation of
  inactive records; per-item failures, never wholesale 409 (D020)
- [x] Endpoints (teacher-authenticated, replacing stubs): POST
  /assignments, GET/PATCH /assignments/{assignment_id} — §31 explicit
  teacher overrides (learning_state, teacher_priority_override,
  is_active) with model_fields_set PATCH semantics; student-scoped 404s
- [x] §30 not-assigned: engine predicates (Phase 14) now exposed on the
  GET browse wrapper (student_id/assigned params) and driven from the
  workbench filter sidebar (student picker + assigned/not-assigned)
- [x] Frontend: assign-to-student action on workbench selection with
  the §29 result note; typed assignments-client
- [x] Tests (7): single assign + §30 both directions, §29 duplicate
  bulk with row-count backstop proof, unknown-sense failure report,
  unknown/cross-teacher student 404s, §31 overrides + clearing,
  validation 422s
- [x] Live verification: bulk 2 → selected 2/new 2; re-assign →
  already 2; assigned=true → 2; assigned=false → 41,688 with zero
  overlap; test student cleaned up
- [x] Gates: backend ruff/mypy clean, 303 passed; frontend tsc/eslint
  clean, vitest 24/24, next build clean
- [x] Docs: D020, current-state.md, architecture.md
- [x] Commit dated 2026-09-30 (+0500), no AI attribution (per D021
  policy — see commit-history note in current-state.md)

## Phase 19 (section 26: vocabulary sets) — COMPLETE 2026-09-30

- [x] app/core/sets.py: sets as pure references to master senses
  ((set_id, sense_id) PK — no vocabulary duplication, §26; D021);
  membership edits report selected/new/already_in_set/failed (§29
  shape); assign-set composes the Phase 18 assignment service
- [x] Endpoints (teacher-authenticated, replacing stubs): GET/POST
  /sets, GET/PATCH/DELETE /sets/{id}, POST/DELETE /sets/{id}/items,
  POST /sets/{id}/assign; per-teacher name uniqueness (409)
- [x] Frontend: sets list (create, delete with confirm), set detail
  (rename, assign-to-student with report note, remove items), and
  workbench selection → add-to-existing-set or create-new-set inline
- [x] Tests (5): lifecycle (create/rename/delete, 409, 404, 422),
  membership (add/re-add report, removal, corpus-untouched assertion),
  assign-set (new 3 → re-assign already 3 → visible in profile),
  cross-teacher 404s, per-teacher duplicate names allowed
- [x] Live verification 7/7: create → add 3 (new 3) → re-add
  (already 3) → detail items 3 → duplicate name 409 → delete 200 →
  404 after delete
- [x] Gates: backend ruff/mypy clean, 308 passed; frontend tsc/eslint
  clean, vitest 24/24, next build clean
- [x] Docs: D021, current-state.md, architecture.md
- [x] Commit dated 2026-09-30 (+0500), no AI attribution

## Phase 20 (sections 31-35: FSRS scheduling + review flow) — COMPLETE 2026-09-30

- [x] py-fsrs 6.3.2 (FSRS-6) added; deterministic config: fuzzing off,
  learning/relearning steps empty (§31 documented transitions; D022);
  rating mapping exactly HARD→Again(1), MEDIUM→Hard(2), EASY→Good(3)
- [x] Migration b8e5d1f2a3c4: student_fsrs_states.state_json (full card
  round-trip; scalars stay denormalized for queue scans)
- [x] app/core/reviews.py: record-review (FSRS update + §33 immutable
  event with previous/new card state + due dates + §31 state move),
  due queue (overdue → due today → new; SQL bucketed ordering),
  outcome-based learning-state derivation (NEW/ENCOUNTERED/LEARNING/
  REVIEWING; MASTERED only via teacher override — D022)
- [x] Endpoints (teacher-authenticated, replacing stubs): GET
  /reviews/due, POST /reviews, GET /fsrs/parameters
- [x] Frontend: live review screen (§32) — one card at a time, reveal,
  HARD/MEDIUM/EASY, keyboard shortcuts 1/2/3 + H/M/E + Space, in-flight
  duplicate-submission guard, queue-clear state
- [x] Tests (6): §6 mapping, deterministic interval fixtures (grow 2d →
  ~2wk; lapse collapse), due-queue ordering + post-review exclusion,
  state moves, §33 chain integrity (previous==prior new, first has no
  prior), validation + §40 isolation, parameters endpoint
- [x] Live verification: queue 1 → EASY (grade 3, ENCOUNTERED, ~1d out,
  queue 0) → HARD (grade 1, LEARNING, reps 2) → history intact;
  cleaned up
- [x] Gates: backend ruff/mypy clean, 314 passed; frontend tsc/eslint
  clean, vitest 24/24, next build clean
- [x] Docs: D022, current-state.md, architecture.md
- [x] Commit dated 2026-09-30 (+0500), no AI attribution

## Phase 21 (sections 36/98: practical teacher dashboard) — COMPLETE 2026-10-01

- [x] Backend app/core/dashboard.py: per-student §36 payload (counts
  assigned/learning/reviewing/mastered/due/overdue with the Phase 20
  SQL definitions, next_up = first §32 queue row, difficult = most
  HARD ratings in 30 days (top 5), recent_reviews = latest events) +
  §98 roster rollup (per-student count rows + totals; attention-need
  ordering overdue → due → name; DELETED excluded, INACTIVE opt-in)
- [x] Endpoints (teacher-authenticated, §40-scoped, read-only):
  GET /students/{id}/dashboard, GET /dashboard (new dashboard router
  module registered in routers.py)
- [x] Queue SQL extracted to app/core/reviews.py `_due_rows` and shared
  with the dashboard so next_up can never disagree with the review
  queue (D023); due_queue public shape/auth unchanged
- [x] Frontend: live /dashboard page (§98 roster table with totals,
  per-student counts, overdue highlighted, Review shortcut) +
  "Review dashboard" panel on the student profile (counts, "What
  should I review next?" card with Start review, difficult list,
  recent reviews); dashboard-client.ts typed wrappers; routes.ts
  phase mapping for /dashboard moved 22 → 21
- [x] Tests (4, DB-backed): empty student, live flow (assign → next_up;
  HARD → learning/difficult/recent; backdated → overdue + flag;
  end-of-today → due; far-future → falls out), state counts + §40
  isolation + overview parity, overview isolation + attention-need
  ordering via real FSRS cards; cleanup in finally
- [x] Live verification: restarted backend on 8737 (needs PYTHONPATH=..),
  GET /dashboard + GET /students/{id}/dashboard via curl; frontend
  rebuilt and restarted on 3000 (page title + tagline present)
- [x] Gates: backend ruff/mypy clean, 318 passed; frontend tsc/eslint
  clean, vitest 24/24, next build clean
- [x] Docs: D023, plan.md, current-state.md, architecture.md
- [x] Commit dated 2026-10-01 (+0500), no AI attribution

## Phase 22 (sections 38/99: import/export) — COMPLETE 2026-10-01

- [x] Exports (POST /exports/vocabulary, teacher-authenticated):
  CSV / XLSX / JSON file downloads over master vocabulary with the
  stable 10-column schema; selection reuses the Phase 14 engine's
  filter composition (export = exactly what the filtered workbench
  shows); deterministic order; 50k-row cap; student-viewpoint filters
  forbidden (extra=forbid → 422, D024)
- [x] Imports (teacher-authenticated, multipart): POST
  /imports/vocabulary/preview (parse + validate + classify, zero
  writes) and POST /imports/vocabulary (re-validate + commit in one
  transaction); CSV (RFC-4180, BOM tolerated), XLSX (openpyxl
  read-only, first sheet), JSON (array of objects); 10k-row cap;
  header + per-row validation (headword required, POS/CEFR/flag
  whitelists, length caps, unknown sense_key)
- [x] §99 safeguards (D024): insert-only (INSERT senses, APPEND
  deduped translations/examples/flags; no UPDATE/DELETE anywhere);
  conflicting master fields → row skipped and reported, never
  overwritten; invalid rows abort with 422 and a per-row report
  (zero partial writes, proven by test)
- [x] Identity round-trip: sense_key from export reattaches; keyless
  rows derive the D008 key via the exact Phase 6 chain
  (make_sense_key ∘ search_key ∘ canonical_pos ∘ clean_gloss —
  verified 300/300 against stored keys); export → delete → re-import
  reproduces the same sense_key and content (test)
- [x] Dependencies: openpyxl 3.1.5 (+ types-openpyxl stubs group),
  python-multipart; app/core/exports.py + app/core/imports.py;
  imports.py/exports.py stubs replaced; mypy pipeline override
  documented (identity now reachable from app)
- [x] Bug fix found by tests: AppError.__init__ never stored the
  instance message — envelopes showed the class default; specific
  422 messages now reach clients
- [x] Frontend: Export/import panel on the vocabulary workbench
  (format picker + filtered download; file upload → Validate →
  per-row status report → Import N new sense(s) with insert-only
  notice); io-client.ts with Blob download + multipart posts
- [x] Tests (11, DB-backed): auth 401s; CSV/JSON/XLSX round-trips;
  filter selection; student-viewpoint rejection; lifecycle (preview
  → commit → verify rows/translations → re-import touches nothing);
  xlsx+json import; validation abort with zero writes; bad
  headers/flags/unknown key; export→wipe→re-import roundtrip
- [x] Gates: backend ruff/mypy clean, 329 passed; frontend tsc/eslint
  clean, vitest 24/24, next build clean
- [x] Docs: D024, plan.md, current-state.md, architecture.md
- [x] Commit dated 2026-10-01 (+0500), no AI attribution

## Phases 21–29 (queued; detailed tasks added as each starts)
20. FSRS (library-backed; HARD→Again MEDIUM→Hard EASY→Good; fixtures) — COMPLETE above
19. Vocabulary sets
20. FSRS (library-backed; HARD→Again MEDIUM→Hard EASY→Good; fixtures)
21. Review interface (one-at-a-time, keyboard shortcuts, duplicate-submission guard) — COMPLETE in Phase 20 above
22. Dashboard (per-student due/overdue/learning/reviewing/mastered) — COMPLETE as Phase 21 above
23. Import/export (CSV/XLSX/JSON, validated import) — COMPLETE as Phase 22 above
24. Security hardening pass — COMPLETE 2026-10-02
   - Rate limiting: per-client-IP fixed window, route-class budgets (login 10/300s · upload 20/300s · read 240/60s · write 120/60s); `max_requests <= 0` disables a class; never resets on higher counts.
   - CSRF: 403 on cross-origin browser mutating requests when origins are configured (GET/OPTIONS exempt; origin-less = non-browser curl clients allowed).
   - Credentials: `SESSION_SECRET` must not be the placeholder `change-me-in-later-phases` in production/staging — startup error (D025).
   - Safe file handling: `_capped_read` enforces `upload_max_bytes` before import bodies fully materialize; oversized → 413 (`PayloadTooLargeError`).
   - Secure headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy).
   - 19 new tests in `backend/tests/test_security.py`; gates: ruff/mypy clean, pytest 351 passed, tsc/vitest/lint/next build green, live curl verified (cross-origin POST → 403, same-origin → 401, origin-less → 401, 12 rapid logins → 401+429, envelope carries request_id).
   - Docs: D025 in decision.md, current-state.md + architecture.md Security section, `.env.example` SECURITY block.
   - Commit `feat/security: security hardening pass (phase 23)` (plain git commit, per D021).
25. Performance pass (realistic volume) — COMPLETE 2026-10-02
   - `scripts/phase25_perf_benchmark.py`: end-to-end HTTP p50 over the full
     DB (41,687 senses) for lexical/semantic/hybrid search, browse at 50/200
     rows, sense detail, bulk assignment (new + already), student profile,
     review queue, dashboards, students list. Report written to
     `data/construction/phase25_perf_report.json`.
   - Measured: cold semantic unique query ~450–680 ms (CPU embed); repeated
     semantic ~70–90 ms; hybrid repeat ~170 ms; everything else 10–100 ms.
   - Fixes (D027): bounded query-embedding LRU cache (≈830→~80 ms repeats);
     frontend page-size clamp corrected 500→200 to match API `MAX_LIMIT`
     (a >200 page size previously returned 422 and broke the table).
   - Gates: ruff/mypy clean, pytest 351 passed; frontend tsc/eslint clean,
     vitest 24/24, next build green.
26. Backups & restoration (real restore test) — local pg_dump/pg_restore per D026
27. Full end-to-end testing (incl. section-59 acceptance workflow in Playwright)
28. Local readiness (clean-environment verification; no deployment per D026)
29. Final acceptance report (docs/final-acceptance-report.md)

---

## Open items

- [x] D004: pgvector — RESOLVED 2026-09-27 (StackBuilder no longer ships
  pgvector; community prebuilt 0.8.6 for PG 17 installed and verified.
  See D004 addendum. Production must replace with a trusted build.)
