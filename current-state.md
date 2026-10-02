# Current State

Last updated: after Phase 23 (see plan.md for phase list)
Honest-state rule applies: this file reflects reality, not intent.

## Current phase
Phase 23 — Security hardening (§39/§40): **COMPLETE** 2026-10-02.
Per-client-IP sliding-window rate limiting (login 10/300s · upload 20/300s
· read 240/60s · write 120/60s; `max_requests <= 0` disables a route
class), CSRF-origin 403 on browser mutating requests, secure headers
(X-Content-Type-Options, X-Frame-Options, Referrer-Policy), and
`_capped_read` on import uploads (oversized → 413 `payload_too_large`).
`SESSION_SECRET` placeholder is rejected at startup in production/staging.
19 new tests (test_security.py); gates green (ruff/mypy; pytest 351;
tsc/vitest/lint/build). Live curl checks verified.
Phase 22 — Import/export (§38/§99): **COMPLETE**. Master-vocabulary
file export (CSV/XLSX/JSON, stable 10-column schema) selected by the
same engine filters as the workbench, student-viewpoint filters
forbidden (D024). Validated import in two steps (preview → commit):
insert-only with deduped appends, conflicting master fields skipped
and reported, invalid rows abort 422 with zero partial writes,
sense_key round-trip verified lossless (export → delete → re-import).
openpyxl + python-multipart added; AppError envelope bug fixed
(instance messages now surface). Frontend: Export/import panel on the
vocabulary workbench. 329 backend tests, 24 frontend tests, all gates
clean.
Phase 21 — Practical teacher dashboard (§36/§98): **COMPLETE**.
Two read models over one SQL definition set (D023): per-student
GET /students/{id}/dashboard (counts assigned/learning/reviewing/
mastered/due/overdue reusing the Phase 20 definitions, next_up =
first §32 queue row via the shared `_due_rows` SQL, difficult = most
HARD ratings in 30 days, recent_reviews = latest §33 events) and
roster GET /dashboard (per-student count rows + totals, attention-need
ordering overdue → due → name, DELETED excluded, INACTIVE opt-in).
Frontend: live /dashboard roster table (totals chips, overdue
highlighted, per-student Review shortcut) and a "Review dashboard"
panel on the student profile ("What should I review next?" card with
Start review, difficult list, recent reviews). No BI features. Live
verified on both servers (restarted to pick up the new code).
Phase 20 — FSRS scheduling + review flow (§31–§35): **COMPLETE**.
Library-backed py-fsrs 6.3.2, deterministic (fuzzing off, no micro
steps), rating mapping exactly HARD→Again / MEDIUM→Hard / EASY→Good.
Full card persisted as JSON (migration b8e5d1f2a3c4); reps/lapses
derived from the immutable §33 event history. Outcome-based learning-
state derivation documented in D022 (NEW/ENCOUNTERED/LEARNING/
REVIEWING; MASTERED = teacher override only). Due queue: overdue →
due today → new in SQL. Live review screen with keyboard shortcuts
and duplicate-submission guard. Live flow verified end-to-end.
Phase 19 — Vocabulary sets (§26): **COMPLETE**. Sets are pure
references to master senses ((set_id, sense_id) PK — structurally
immune to vocabulary duplication, D021). CRUD + membership with the
§29 accounting shape (selected/new/already_in_set/failed), assign-set
composing the Phase 18 assignment service, per-teacher name
uniqueness (409). Frontend: sets list with confirm-delete, set detail
(rename, assign-to-student, remove items), and workbench selection →
add-to-set or create-new-set inline. Live flow verified 7/7.
Phase 18 — Assignment (§28–§31): **COMPLETE**. Single/bulk assignment
via POST /assignments (one endpoint, 1..1000 senses) with §29 layered
duplicate prevention (application pre-check + UNIQUE backstop, proven
by row-count test) and the §29 report (selected/new/already_assigned/
failed); unknown senses reported per-item, never wholesale failure.
PATCH /assignments/{id} applies explicit §31 teacher overrides
(learning_state, per-student priority, active flag). §30 not-assigned
workflow driven from the workbench filter sidebar (student picker +
assigned/not-assigned radios) through the GET browse wrapper.
Commit policy note: AI co-author trailers removed from history
(2026-09-30, content verified identical); commits are now clean.
Phase 17 — Student management (§27/§39/§40): **COMPLETE**. All §27
operations behind teacher-authenticated endpoints: create, edit (true
PATCH semantics — absent fields preserved, sent nulls clear),
deactivate/reactivate, soft delete (learning history preserved, §27
hard rule), open profile, assigned-vocabulary view with learning state
and FSRS due/reps. §40 isolation by WHERE-scoping: foreign student ids
are 404, indistinguishable from unknown (D019). Frontend: students
list with create + lifecycle buttons, profile page with edit,
assigned-vocabulary table and confirm-step delete.
Phase 16 — Vocabulary UI (§23/§54): **COMPLETE**. Dense spreadsheet
workbench on /vocabulary backed by the search engine: 8-column table,
search box with mode selector, facet-driven filter sidebar (all
server-side per §22), sortable headers, SQL pagination, row selection
for future bulk actions. URL-driven state (shareable filtered views,
unit-tested lossless round-trip). Sense detail page (all relations +
provenance) on the new GET /vocabulary/{sense_id}; GET /vocabulary
browse wrapper parity-tested with POST /vocabulary/search (D018).
TanStack Query/Table installed; table uses the official v9 `legacy`
subpath (D018). Login page + session bar live over Phase 15 auth.
Verified live: CORS/credentialed cookie flow :3000→:8737, headless
Chrome hydration of login + workbench.
Phase 15 — Teacher authentication (§5/§39/§91): **COMPLETE**. Argon2id
password hashing; server-side sessions (opaque token in an HTTP-only
cookie, SHA-256 hash in PostgreSQL, 24h TTL, lazy prune, instant
revocation); bootstrap-only first-teacher creation (window closes
forever after; no public registration); login with anti-enumeration
(decoy hash, uniform 401). Endpoints: /auth/bootstrap, /auth/login,
/auth/session, /auth/logout (replacing Phase 4 stubs). The §40
"authenticated teacher" dependency is ready for protected endpoints.
Phase 14 — Search backend (§20–22): COMPLETE. Four-layer search on
POST /api/v1/vocabulary/search: exact/prefix + weighted FTS (headword,
Polish translations, definitions), SQL-composed filters (incl. §22
student assignment/state), semantic (BGE-M3 + HNSW) and hybrid RRF
blend (D016, docs/search.md). All six §21 example queries answer;
benchmark captured in docs/search.md.
Phase 13 — PostgreSQL vocabulary import (§89): COMPLETE. 41,687/41,690
senses in PG (3 junk rows rejected and reported), re-import idempotent,
priority history + denormalized current-priority columns populated.
Phase 12 — Embeddings: **COMPLETE**. Full 41,690-sense generation
finished 2026-09-29 (batch 1303/1303, log
data/construction/phase12_full.log); HNSW index rebuilt over the
complete corpus via --reigate (262s; D016 rule satisfied); semantic
recall verified post-rebuild (bank top-5, 0.054s query). Resumable
(--full --resume), safe to interrupt.
Next: Phase 25 — Performance pass (realistic volume)

## Completed work
Phase 13:
- Importer (pipeline/storage/pg_import.py, import-v1, D015): validated,
  batched, single-transaction; roots upserted by sense_key (UUIDs +
  embedding FKs preserved), children delete-refreshed, everything
  dropped/duplicated/unmapped reported (data/construction/
  phase13_import_report.json).
- Deterministic CEFR collapse: 6,684 duplicate (sense, source)
  statements resolved to the lowest-(cefr,pos_raw) survivor.
- Migration c3d94a71b6e2: sense_priorities PK (sense_id) → (sense_id,
  version) — Phase 2 schema could not hold D012 history; 83,374 rows
  imported across prio-v1/prio-v1.1.
- refresh_priority_columns: vocabulary_senses.priority_* mirror
  prio-v1.1 (41,687 rows); versioned table stays source of truth.
- Migration roundtrip test sandboxed into disposable vocab_scratch_*
  DBs; env.py accepts programmatic/ALEMBIC_DATABASE_URL override.
  **No test may downgrade the dev DB** — that wiped data twice.
- Stale-checkpoint guard: embedding resume verifies checkpointed work
  is actually stored; mismatch restarts fresh (caught live).

Phase 12:
- Embedding pipeline (pipeline/enrich/embeddings.py, emb-v1, D014,
  docs/embeddings.md): BGE-M3 1024-dim L2-normalized, recipe
  `headword | pos | gloss | ex1 | ex2` (max 2 examples, no metadata per
  §88), per-row text_sha256 change/resume guard, sorted sense_key order,
  immutable-snapshot checkpoints (dataclasses.replace), lazy singleton
  EmbeddingModel with data/models cache.
- pgvector storage (pipeline/storage/pg_store.py): ensure_sense_rows
  (idempotent v0-bootstrap of vocabulary_senses with app-generated uuid4
  ids per D006), existing_embedding_shas, upsert_embeddings
  (CAST(:emb AS vector); psycopg3 rejects :param::vector),
  delete_other_versions (exactly one current version), count_embeddings,
  nearest_senses (cosine over HNSW).
- Migration 7b2c91a4e8f5: sense_embeddings — vector(1024),
  UNIQUE(sense_id, embedding_version), version btree, HNSW
  ix_sense_embeddings_hnsw (vector_cosine_ops); EXPECTED_TABLES updated.
- Deps: sentence-transformers 6.1.0, pgvector, torch 2.14.0+cpu,
  transformers 5.17.0 (uv add; CUDA unavailable on this workstation).
- Real-data smoke (scripts/phase12_embeddings_smoke.py, --limit 96
  --probes): 96 senses embedded (0.4s encode, 43.7s total incl. load),
  rows=96 versions=1; re-run idempotent — 96/96 skipped_unchanged,
  0 re-embedded, checkpoint resume verified on real data. Probes printed
  but uninformative at limit=96 (candidate pool = 96 lowest-rank
  a–about senses); nearest-neighbor quality must be judged after the
  full 41,690-sense run. BGE-M3 weights were downloaded via ModelScope
  mirror (HF CDN stalled repeatedly on this network) and sha256-verified
  (b5e0ce34…daad38) into the HF cache; model loads with HF_HUB_OFFLINE=1.
- Throughput: benchmark 2.2 texts/s on synthetic repeats; real-run
  measurement ~0.75 senses/s (longer gloss+example texts) → full run
  ≈ 15h, launched detached (docs/embeddings.md documents the method).
  Post-benchmark honesty fix: initial 5.4h estimate was benchmark-only.
Phase 11:
- Example integration (pipeline/enrich/examples.py, ex-v1, D013):
  Wiktextract sense examples + WordNet synset examples (joined through
  Phase 8 links) cleaned, deduplicated, source-ordered, capped at 5 per
  sense, per-row provenance in the new sense_examples table (full
  refresh, idempotent).
- Quality indicators (pipeline/enrich/quality.py, qual-v1, D013): the
  §87 minimum eight — translation available/confidence, definition
  available, example available, CEFR available, frequency available,
  category confidence, composite sense_confidence — deterministic from
  stored evidence, missing = 0.0 (never invented); incomplete senses
  retained (§87). sense_confidence is an evidence-coverage view, kept
  separate from Phase 10 priority by design.
- Real-data smoke (scripts/phase11_quality_smoke.py): 52,824 examples
  for 25,693 senses (44,061 wiktextract + 8,763 wordnet; 3,271 unclean,
  36 duplicate, 3,836 over-cap dropped); indicators for all 41,690
  senses — translation 13,162 / definition 41,688 / example 25,693 /
  CEFR 24,137 / frequency 17,161 / category 7,702; mean
  sense_confidence 0.5089; 1 zero-evidence sense retained, none deleted.
Phase 10 (audit + fixes):
- D012 addendum: programmatic + stratified-sample audit surfaced slur-
  class senses un-penalized (brown slur sense at VERY HIGH 0.7412) and
  raw gloss token counting overstating depth ("a lady s maid" → 4
  tokens). Fixed in prio-v1.1: derogatory/offensive/slur joined hard
  markers (×0.5), quality counts significant tokens (≥ 2 alnum chars).
  Post-fix audit PASS: 0 level/recompute/ordering anomalies, flagged
  mean 0.299 vs clean 0.589, CEFR gradient A1 0.612 → C2 0.502, all 322
  slur-class senses below VERY HIGH, boundary strata clean; prio-v1 rows
  retained (history never destroyed, §86).
Phase 10:
- Deterministic priority scoring (pipeline/enrich/priority.py, prio-v1.1
  after audit, D012, docs/priority-scoring.md): `score = (0.35·frequency +
  0.15·learner + 0.20·polish + 0.30·quality) × penalty` — multiple
  signals, never CEFR or raw frequency alone (§86); full component
  breakdown stored per sense (§16); fixed quantile-free levels
  VERY HIGH ≥ 0.70 … VERY LOW < 0.25.
- Missing evidence is neutral (0.5), never a penalty (§127); CEFR floors
  at 0.55 so a C2 word is never disqualified (§14); flag penalty is
  multiplicative (hard ×0.5 set-wise, soft ×0.75 each, floor 0.25) and
  applied directly so flags move senses across level bands.
- Construction DB: sense_priorities keyed (sense_key, version) — new
  formula versions add rows, history never destroyed (§86).
- Real-data smoke (scripts/phase10_priority_smoke.py): 41,690 senses →
  VERY HIGH 3,814 / HIGH 17,109 / MEDIUM 11,860 / LOW 5,266 / VERY LOW
  3,641; per-CEFR gradient A1 (2,294 VERY HIGH / 104 VERY LOW) → C2
  (0 VERY HIGH / 23 VERY LOW); top `have` 0.853, bottom junk `aa` 0.110.
Phase 9 (audit + fixes):
- D011 addendum: random-sample precision audit of taxonomy surfaced four
  defect classes — single-keyword gloss noise (0.65 tier removed), prone
  polysemous keywords (water/flight/score/wake/run pruned), shared-stemmer
  over-stemming of short words (dose→do; fixed with ≥ 3-char guard,
  wnlink-v1.1), and headword-tier word-level misassignment (fast
  "light-sensitive" → food-diets; fixed by requiring same-category gloss
  corroboration with headword-stem exclusion, tax-v1.2).
- Final real-data numbers: 7,702/41,690 senses categorized (18.5% vs the
  pre-audit 60.1%), 12,599 assignments, 2,196 multi-category, all 24
  categories populated, audited sub-level sample clean. Precision over
  coverage for teacher-facing filters; coverage grows with future
  evidence-driven version bumps.
Phase 9:
- Deterministic thematic taxonomy (pipeline/enrich/taxonomy.py, tax-v1,
  D011): 24 top categories + subcategories per §18 (170 nodes), three
  evidence tiers — headword 0.90, WordNet hypernym-chain 0.85 (reuses
  Phase 8 links/catalog), gloss keywords 0.60–0.80; best per (category,
  sub) wins; multiple categories per sense; uncategorized counted, never
  forced; categories are retrieval/filtering aids, not a search
  prerequisite (§18, §85).
- Construction DB: taxonomy_nodes + sense_categories tables with full-
  refresh idempotent upserts; QC counters.
- Real-data smoke (scripts/phase9_taxonomy_smoke.py): 25,053 / 41,690
  senses (60.1%) categorized, 81,196 assignments, 11,645 multi-category
  senses, all 24 categories populated; spot checks correct (thunder →
  weather 0.90 headword, hungry → emotions+food-cooking 0.85 chain,
  salary → money-income 0.90).
Phase 8:
- Synset catalog in construction DB (pipeline/enrich/wordnet.py +
  pipeline/storage/sqlite_store.py): 107,519 synsets, 125,249 relations
  grouped synonym/hypernym/hyponym/related (unknown types preserved
  verbatim, no reverse edges invented), keyed by WordNet's own synset ids
  so the Phase 13 PostgreSQL import joins the same source of truth (D010).
- Sense→synset linking (wnlink-v1): POS-gated + deterministic —
  monosemous WordNet assertion 0.80, definition-match (D008 token rules +
  light inflection stemmer) ≥ 0.60, shared-tokens tier 0.70 (definition or
  WordNet members, headword excluded); missing/ambiguous evidence never
  links, every miss is counted in the QC report.
- Real-data smoke (scripts/phase8_wordnet_smoke.py): 41,690 senses →
  13,259 linked (31.8%); per-POS noun 38.8% / verb 26.8% / adj 33.9% /
  adv 39.2%; per-CEFR A1 26.5% → C2 37.5%; representative senses verified
  (bank-financial → financial institution, quickly → with speed,
  bright → emitting light; heuristic 0.70 near-field siblings documented).
Phase 7:
- CEFR reconciliation (D009): POS-aware, single/unanimous/conflict tiers,
  conflicts preserved with flags (970 in sample), unknown stays unknown.
- Frequency: best-rank dedup + bands (display metadata only, separate from
  priority per sections 15–16).
- SQLite construction DB (pipeline/storage/): batched idempotent upserts,
  run log, QC summary; 41,690 senses persisted from the 150k-line sample.
Phase 6 (unchanged):
- Sense identity layer (pipeline/identity/identity.py): (word, POS) groups,
  gloss-token clustering with anti-over-merge bias, stable unique
  sense_key format (sensekey-v1, D008), provenance/evidence-union on merge.
- docs/sense-identity.md documenting rules, key format and measured results.
- Real-data smoke: 47,327 candidates → 41,686 master senses, 0 collisions,
  BANK acceptance verified on real data.
Phase 5 (unchanged):
- Normalization primitives: display vs search keys (NFC, casefold,
  diacritics incl. NFD-invariant ł/ø/ß, punctuation), gloss cleaning,
  American-spelling helper (section 81).
- Total cross-source POS mapping (CEFR-J phrases, Wiktextract tags,
  WordNet letters → canonical noun/verb/adjective/adverb/phrase/other).
- D007: deterministic word→sense Polish translation alignment
  (inline/cognate/token/position, versioned align-v1, confidences stored;
  docs/translation-alignment.md).
- NormalizedSenseCandidate merge producing Phase 6 input: Wiktextract
  senses + aligned translations + word-level CEFR/frequency/WordNet
  evidence; real-data smoke on 150k dump lines → 47,327 candidates.
Phase 4 (unchanged):
- Shared normalized-record contract and AdapterRun stats (processed/skipped/
  failed/warning/read) per section 45.
- Five adapters, one module each (section 80): cefrj, octanove, ngsl
  (exact CSV parsing with validation/warnings), wiktextract (streaming
  English-entry extraction with senses/tags/Polish translations), wordnet
  (synsets + 16 typed relation types + lemma links).
- Real-data smoke verification against all five raw files; statistics match
  the Phase 3 inventory exactly; nothing silently dropped.
Phase 3 (unchanged):
- Streaming inspectors for all 5 datasets (pipeline/sources/); unit tests
  with synthetic fixtures.
- Full Wiktextract streaming pass (10,913,996 lines, 908s, 0 malformed) plus
  50k-entry English profile; exact CSV/WordNet statistics.
- docs/data-source-inventory.md + machine-readable data/source-inventory.json
  (both formats, per section 79) with ETL implications and cross-source
  integration notes.
Phase 2 (unchanged):
- Alembic initialized (env.py wired to app settings; no duplicated config).
- 25-table core schema via one autogenerated migration: identity (teachers,
  sessions, students), master vocabulary (senses/forms/definitions/
  translations/examples, source registry + per-record provenance, CEFR and
  frequency evidence, flags, WordNet synsets/relations/links, categories,
  priorities) and learning (student_vocabulary, FSRS state, review events,
  sets, teacher priority overrides).
- Mandatory UNIQUE(student_id, sense_id) enforced at DB level and tested.
- Indexes per section 42; enum values stored as readable strings (D006).
- Migration up/down round-trip verified against real PostgreSQL.
Phase 0-1 (unchanged):
- Repository/dataset/tooling inspection; native PostgreSQL 17 + `vocab_platform`
  database; FastAPI + Next.js skeletons; documentation set; first commit.
Phase 1:
- Backend core: validated settings (fail-fast), correlation-ID context,
  structured logging (console/JSON, sensitive-key masking), typed error
  hierarchy, uniform error envelope, correlation + access-log middleware,
  CORS from settings, global exception handlers (AppError/schema-422/
  HTTP/500), domain router registry (11 domains) with honest 501 stubs (D005).
- Frontend: complete section-53 route structure (12 routes incl. dynamic),
  route manifest as single source of truth, honest placeholders, typed API
  client (ApiError) mirroring the envelope; Vitest wired.

## Tests passed
- Backend pytest: 329 passed (incl. 13 auth, 21 search, 17 import,
  8 vocabulary browse/detail, 6 students, 7 assignments, 5 sets,
  6 reviews/FSRS, 4 dashboard, 11 import/export, 16 embeddings,
  7 pgvector, sandboxed migration roundtrip)
- Frontend vitest: 24 passed (route coverage 15, API client 4,
  table URL state 5)
- Quality gates: ruff clean, mypy clean (41 files), tsc clean, eslint clean,
  `next build` passes (route table shows all 12 routes)
- Live HTTP smoke: X-Request-ID on responses; 404/501 envelopes; access log
  lines with correlation IDs; `health` reports `database: up` when DB reachable

## Tests failed
- None known.

## Known issues
- pgvector 0.8.6 installed 2026-09-27 from a community prebuilt
  (andreiramani/pgvector_pgsql_windows, MSVC-compiled for PG 17; D004
  addendum) after StackBuilder dropped pgvector from its catalog — the DLL
  is an unsigned third-party build; acceptable for local development only.
  **Production (Phase 28) must replace it with a trusted build** (VS Build
  Tools source compile or a distribution that ships pgvector).
- Container/deployment scaffolding removed 2026-10-02: `docker-compose.yml`,
  `backend/Dockerfile` and `frontend/Dockerfile` deleted. The project runs
  natively on one local machine and `requiremnts.txt` never requires Docker
  (D026). Historical D002 note is retained; the compose file is gone.
- Domain endpoints return 501 by design until their phase (see plan.md).

## Tests passed
- Backend pytest: 351 passed (phase 23 adds test_security.py: 19 rate-limit/CSRF/origin/payload tests)
- Frontend vitest: 24 passed
- Quality gates: ruff clean, mypy clean, tsc clean, eslint clean, `next build` passes
- Live HTTP smoke: secure headers present; cross-origin POST → 403; same-origin → 401; origin-less → 401; 12 rapid logins → 401×5 + 429×4; envelopes carry `X-Request-ID` + `request_id`.

## Tests failed
- None known.

## Known issues
- PostgreSQL 17.11 running as Windows service.
- Database `vocab_platform` at Alembic head `c3d94a71b6e2` (priority
  history PK; 27 tables incl. sense_embeddings).
- Data: 41,687 vocabulary_senses (imported Phase 13, ids stable across
  re-imports), 83,374 sense_priorities (prio-v1 + prio-v1.1),
  priority_* columns populated (prio-v1.1); sense_embeddings filling
  via the detached Phase 12 run (checkpoint == stored rows).
- Extension `vector` 0.8.6 (pgvector) installed 2026-09-27 — verified via
  psql and the backend stack: round-trip, `<->` operators, HNSW index.
- Migration roundtrip runs in disposable scratch DBs only (D015: the dev
  DB must never be downgraded by tests).

## Data state
- Raw datasets present and immutable under `data/raw/` (Git-ignored,
  documented in data/raw/README.md).
- Pipeline (150k-line Wiktextract sample = ~1.4% of dump): adapters →
  normalize → identity → enrich → SQLite construction DB. 41,690 master
  senses persisted; CEFR 57.9%, frequency 41.2%, Polish 31.6%, examples
  60.3%; 970 CEFR conflicts preserved with flags; WordNet 13,263 linked
  (wnlink-v1.1); taxonomy 7,702 categorized (tax-v1.2); priorities 41,690
  scored (prio-v1.1; prio-v1 history retained); examples 52,824 integrated
  for 25,693 senses (ex-v1); quality indicators 41,690 (qual-v1). QC via
  store.qc_summary().
- **Inspected** (Phase 3): full inventory in docs/data-source-inventory.md.

## Search state
- Live since Phase 14 (see above).

## Deployment state
- None and not required: local-only operation (D026). The final phase verifies
  a clean **local** reinstall/run, not a deployment.

## Next task
Phase 23 (plan-queue 24): Security hardening pass (§39/§40 checklist,
rate limiting where appropriate, CSRF review, safe file handling
review).

---

## Phase 7

### Status
COMPLETE

### Implemented
- pipeline/enrich/cefr.py, frequency.py, applier.py
- pipeline/storage/sqlite_store.py (construction DB)

### Tests
- backend/tests/test_enrichment.py (17 tests)

### Test Result
PASS (122/122 backend; gates green)

### Known Issues
- pgvector pending (D004, needed Phase 12)
- CEFR POS-mismatch evidence downgraded but kept — rule documented (D009)

### Database Changes
- SQLite construction DB created at data/construction/construction.sqlite
  (pipeline workbench only — production PostgreSQL schema unchanged)

### Documentation Updated
- plan.md, current-state.md, decision.md (D009)

### Git Commit
feat: add CEFR and frequency enrichment with construction DB (2026-09-23 +0500)

### Next Phase
Phase 8 — WordNet and Semantic Relationships

---

## Phase 6

### Status
COMPLETE

### Implemented
- pipeline/identity/identity.py (clustering, keys, merge)
- docs/sense-identity.md; D008 in decision.md

### Tests
- backend/tests/test_sense_identity.py (15 tests incl. BANK acceptance)
- Real-data smoke (results in plan.md and docs/sense-identity.md)

### Test Result
PASS (105/105 backend; gates green)

### Known Issues
- pgvector pending (D004, needed Phase 12)
- Lexical clustering cannot merge paraphrases with disjoint vocabulary —
  safe direction (extra senses, not lost meanings); revisit with WordNet
  (Phase 8) and embeddings (Phase 12) under a new key version if needed

### Database Changes
- None yet (master senses still in-memory; SQLite persistence in Phase 7
  construction step)

### Documentation Updated
- plan.md, current-state.md, decision.md (D008), docs/sense-identity.md

### Git Commit
feat: add sense identity resolution with stable keys (2026-09-22 +0500)

### Next Phase
Phase 7 — CEFR and Frequency Integration

---

## Phase 5

### Status
COMPLETE

### Implemented
- pipeline/normalize/clean.py, pos.py, align.py (D007), normalizer.py
- docs/translation-alignment.md

### Tests
- backend/tests/test_normalization.py (31 tests)
- Real-data smoke: 150k-line Wiktextract sample → 47,327 normalized
  candidates; 31.5% senses with PL; BANK → 42 senses w/ cognate-only
  translations on unrelated senses (correct)

### Test Result
PASS (90/90 backend; gates green)

### Known Issues
- pgvector pending (D004, needed Phase 12)
- Position-fallback translations carry 0.35 confidence by design; some
  misassignment is expected and marked — improvement path documented in D007

### Database Changes
- None yet (normalized candidates are in-memory; Phase 6 adds identity +
  SQLite construction persistence)

### Documentation Updated
- plan.md, current-state.md, decision.md (D007), docs/translation-alignment.md

### Git Commit
feat: add normalization layer with translation alignment heuristic (2026-09-21 +0500)

### Next Phase
Phase 6 — Sense Identity

---

## Phase 4

### Status
COMPLETE

### Implemented
- pipeline/records.py (SourceCefrRecord etc. live in adapters; stats/run)
- pipeline/sources/cefrj_adapter.py, octanove_adapter.py, ngsl_adapter.py,
  wiktextract_adapter.py, wordnet_adapter.py

### Tests
- backend/tests/test_source_adapters.py (13 tests, synthetic fixtures)
- Real-data smoke runs (manual, results recorded in plan.md)

### Test Result
PASS (59/59 backend; gates green)

### Known Issues
- pgvector pending (D004, needed Phase 12)
- WordNet relation records reference synsets that may fall outside the
  parsed set in later normalization — link resolution happens in Phase 8

### Database Changes
- None (adapters produce in-memory normalized records; SQLite construction
  DB arrives with Phase 5/6 persistence)

### Documentation Updated
- plan.md, current-state.md

### Git Commit
feat: add source adapters for all five datasets (2026-09-20 +0500)

### Next Phase
Phase 5 — Normalization

---

## Phase 3

### Status
COMPLETE

### Implemented
- pipeline/sources/csv_sources.py (CEFR-J, Octanove, NGSL)
- pipeline/sources/wordnet_inspect.py
- pipeline/sources/wiktextract_inspect.py (streaming)
- pipeline/inspect_all.py (report generator)
- docs/data-source-inventory.md, data/source-inventory.json

### Tests
- backend/tests/test_source_inspectors.py (6 synthetic-fixture tests)

### Test Result
PASS (46/46 backend; gates green)

### Known Issues
- pgvector pending (D004, needed Phase 12)
- Octanove has 58 duplicate (headword, POS) pairs and 2 empty POS values —
  handled by Phase 7 evidence policy, not blocking
- Wiktextract translations are word-level, not sense-level — Phase 5 must
  define and document the gloss-alignment heuristic (D-decision)

### Database Changes
- None

### Documentation Updated
- plan.md, current-state.md, docs/data-source-inventory.md (new),
  data/source-inventory.json (new, Git-ignored), .gitignore

### Git Commit
feat: add dataset inspection pipeline and source inventory report (2026-09-19 +0500)

### Next Phase
Phase 4 — Source Adapters

---

## Phase 2

### Status
COMPLETE

### Implemented
- Alembic + migrations/env.py wired to settings
- app/db/models/: base (naming convention, timestamps), enums, identity,
  vocabulary (12 tables), learning (7 tables); models/__init__ aggregator
- Initial migration 4c047544de4d "create core schema" (25 tables)

### Tests
- tests/test_migrations.py (schema presence, round-trip, unique constraint)
- tests/test_constraints.py (duplicate prevention, FKs, uniqueness, enum)

### Test Result
PASS (40/40 backend; gates green)

### Known Issues
- pgvector pending (D004, needed Phase 12); no other known issues

### Database Changes
- Initial schema created (25 tables); see D006 for identity/integrity model

### Documentation Updated
- plan.md, current-state.md, decision.md (D006), architecture.md

### Git Commit
feat: add database foundation with Alembic migrations and core schema (2026-09-18 +0500)

### Next Phase
Phase 3 — Source Data Inspection

---

## Phase 1

### Status
COMPLETE

### Implemented
- Backend: core.settings (validated), core.context, core.logging,
  core.errors, core.middleware, api.exception_handlers, api.v1.routers +
  11 domain routers (501 stubs), CORS wiring
- Frontend: lib/routes.ts (manifest), 12 route pages, components/
  PagePlaceholder, lib/api.ts (ApiError), vitest config + tests

### Tests
- backend/tests/test_health.py, test_error_envelope.py, test_middleware.py,
  test_settings.py
- frontend/tests/routes.test.ts, tests/api-client.test.ts

### Test Result
PASS (backend 27/27; frontend 19/19; all gates green)

### Known Issues
- pgvector pending (D004); Docker unavailable (D002); domain endpoints 501
  by design until their phases

### Database Changes
- None (schema arrives in Phase 2 via Alembic)

### Documentation Updated
- architecture.md, plan.md, decision.md (D005), current-state.md, .env.example

### Git Commit
- feat: add backend core with logging, error envelope and domain routers
- feat: add frontend route structure and typed API client
- docs: record architecture foundation decisions and phase state
(all dated 2026-09-17 +0500)

### Next Phase
Phase 2 — Database Foundation

---

## Phase 0

### Status
COMPLETE

### Implemented
- Repository/dataset/tooling inspection
- Native PostgreSQL 17 + `vocab_platform` database
- FastAPI backend skeleton with health endpoints
- Next.js + Tailwind frontend skeleton (build verified)
- Documentation set, .env.example, .gitignore, docker-compose.yml
  (for Docker-capable environments)

### Tests
- backend/tests/test_health.py (5 tests)

### Test Result
PASS

### Known Issues
- pgvector pending (D004); Docker unavailable (D002)

### Database Changes
- Created database `vocab_platform` (no schema yet)

### Documentation Updated
- master.md, decision.md, current-state.md, architecture.md, plan.md,
  README.md, docs/environment.md, data/raw/README.md

### Git Commit
feat: Initialize project structure and documentation (2026-09-16T10:30:00 +0500)

### Next Phase
Phase 1 — Architecture Foundation
