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
Status: TODO

- [ ] Alembic setup
- [ ] Core tables: teachers, sessions, students, vocabulary_senses, vocabulary_forms, translations, definitions, examples, cefr_evidence, frequency_evidence, categories, vocabulary_categories, wordnet_relations, vocabulary_flags, vocabulary_sources, vocabulary_priority, student_vocabulary, review_events, fsrs_states, vocabulary_sets, vocabulary_set_items
- [ ] UNIQUE(student_id, master_sense_id) constraint
- [ ] Indexes per master_prompt.md section 42, documented
- [ ] Migration up/down tests, constraint/unique-violation tests
- [ ] Commit

Tests: migration round-trip; UNIQUE constraint violation; FK integrity.

---

## Phase 3 — Source Data Inspection
Status: TODO

- [ ] Streaming inspector for every dataset in data/raw/
- [ ] Machine-readable + human-readable report: docs/data-source-inventory.md
- [ ] Record format, size, counts, schema, fields, IDs, languages, anomalies
- [ ] Commit

Tests: inspector produces deterministic report fixtures.

---

## Phases 4–29 (queued; detailed tasks added as each starts)

4. Source adapters (wiktextract, cefrj, ngsl, octanove, wordnet) — tests per adapter
5. Normalization (form/lemma/POS/sense/definition/translation; display vs search values)
6. Sense identity & deduplication (stable IDs; collision tests; BANK case)
7. CEFR + frequency integration (evidence preservation, conflict handling)
8. WordNet semantic relationships
9. Thematic taxonomy (deterministic mapping, multi-category)
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
