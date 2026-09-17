# Current State

Last updated: after Phase 1 (see plan.md for phase list)
Honest-state rule applies: this file reflects reality, not intent.

## Current phase
Phase 1 — Architecture Foundation: **COMPLETE** (record below)
Next: Phase 2 — Database Foundation

## Completed work
Phase 0 (unchanged this phase):
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
- Backend pytest: 27 passed (health 5, error envelope 8, middleware 6,
  settings 8)
- Frontend vitest: 19 passed (route coverage 15, API client 4)
- Quality gates: ruff clean, mypy clean (28 files), tsc clean, eslint clean,
  `next build` passes (route table shows all 12 routes)
- Live HTTP smoke: X-Request-ID on responses; 404/501 envelopes; access log
  lines with correlation IDs; `health` reports `database: up` when DB reachable

## Tests failed
- None known.

## Known issues
- pgvector is not yet installed (D004 — deferred to Phase 12; StackBuilder
  GUI step pending on this machine). No Phase 2–11 deliverable depends on it.
- Docker is unavailable on this machine; docker-compose.yml exists for
  Docker-capable environments but could not be executed here (D002).
- Domain endpoints return 501 by design until their phase (see plan.md).

## Database state
- PostgreSQL 17.11 running as Windows service.
- Database `vocab_platform` exists, empty (no schema yet — Phase 2).
- Alembic not yet initialized (Phase 2).

## Data state
- Raw datasets present and immutable under `data/raw/` (Git-ignored,
  documented in data/raw/README.md). No processing has started.

## Search state
- Not implemented (Phase 14). Search router registered as 501 stub.

## Deployment state
- Development only. Deployment docs are a Phase 28 deliverable.

## Next task
Phase 2: Alembic setup + core tables (teachers, sessions, students,
vocabulary core, categories, sets, student vocabulary, review history,
FSRS state) with migration up/down + constraint tests, especially
UNIQUE(student_id, master_sense_id).

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
