# Current State

Last updated: after Phase 10 (see plan.md for phase list)
Honest-state rule applies: this file reflects reality, not intent.

## Current phase
Phase 10 — Vocabulary Priority: **COMPLETE** (record below)
Next: Phase 11 — Examples & Quality Indicators

## Completed work
Phase 10:
- Deterministic priority scoring (pipeline/enrich/priority.py, prio-v1,
  D012, docs/priority-scoring.md): `score = (0.35·frequency + 0.15·learner
  + 0.20·polish + 0.30·quality) × penalty` — multiple signals, never CEFR
  or raw frequency alone (§86); full component breakdown stored per sense
  (§16); fixed quantile-free levels VERY HIGH ≥ 0.70 … VERY LOW < 0.25.
- Missing evidence is neutral (0.5), never a penalty (§127); CEFR floors
  at 0.55 so a C2 word is never disqualified (§14); flag penalty is
  multiplicative (hard ×0.5 set-wise, soft ×0.75 each, floor 0.25) and
  applied directly so flags move senses across level bands.
- Construction DB: sense_priorities keyed (sense_key, version) — new
  formula versions add rows, history never destroyed (§86).
- Real-data smoke (scripts/phase10_priority_smoke.py): 41,690 senses →
  VERY HIGH 3,828 / HIGH 17,219 / MEDIUM 11,985 / LOW 5,147 / VERY LOW
  3,511; per-CEFR gradient A1 (2,302 VERY HIGH / 90 VERY LOW) → C2
  (0 VERY HIGH / 22 VERY LOW); top `have` 0.853, bottom junk `aa` 0.110.
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
- Backend pytest: 186 passed (+18 priority)
- Frontend vitest: 19 passed (route coverage 15, API client 4)
- Quality gates: ruff clean, mypy clean (34 files), tsc clean, eslint clean,
  `next build` passes (route table shows all 12 routes)
- Live HTTP smoke: X-Request-ID on responses; 404/501 envelopes; access log
  lines with correlation IDs; `health` reports `database: up` when DB reachable

## Tests failed
- None known.

## Known issues
- pgvector is not yet installed (D004 — deferred to Phase 12; StackBuilder
  GUI step pending on this machine). No Phase 3–11 deliverable depends on it.
- Docker is unavailable on this machine; docker-compose.yml exists for
  Docker-capable environments but could not be executed here (D002).
- Domain endpoints return 501 by design until their phase (see plan.md).

## Database state
- PostgreSQL 17.11 running as Windows service.
- Database `vocab_platform` at Alembic head `4c047544de4d` ("create core
  schema", 25 tables). No data rows yet (pipeline starts Phase 4+).
- Round-trip verified: downgrade base -> upgrade head reproduces schema.

## Data state
- Raw datasets present and immutable under `data/raw/` (Git-ignored,
  documented in data/raw/README.md).
- Pipeline (150k-line Wiktextract sample = ~1.4% of dump): adapters →
  normalize → identity → enrich → SQLite construction DB. 41,690 master
  senses persisted; CEFR 57.9%, frequency 41.2%, Polish 31.6%, examples
  60.3%; 970 CEFR conflicts preserved with flags; WordNet 13,263 linked
  (wnlink-v1.1); taxonomy 7,702 categorized (tax-v1.2); priorities 41,690
  scored (prio-v1). QC via store.qc_summary().
- **Inspected** (Phase 3): full inventory in docs/data-source-inventory.md.

## Search state
- Not implemented (Phase 14). Search router registered as 501 stub.

## Deployment state
- Development only. Deployment docs are a Phase 28 deliverable.

## Next task
Phase 11: Examples & quality indicators — extract and store example
sentences per sense with quality indicators (sections 87, 16), feeding
the Phase 10 quality component with real per-sense data.

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
