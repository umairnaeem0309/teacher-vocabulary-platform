# English–Polish Vocabulary Teaching & FSRS Platform

Teacher-facing web platform for teaching English vocabulary to
Polish-speaking students: vocabulary discovery (lexical + semantic),
management, student assignment with sense-level duplicate prevention,
manual review and FSRS spaced repetition.

- `master.md` — project constitution
- `decision.md` — architecture decision log
- `current-state.md` — honest operational state (updated every phase)
- `architecture.md` — actual implemented architecture
- `plan.md` — phase plan (Phases 0–29)
- `master_prompt.md` / `requiremnts.txt` — original specification + BRD

## Stack

Next.js + TypeScript + Tailwind (+ shadcn/ui, TanStack Query/Table) ·
FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic · PostgreSQL 17 + pgvector ·
uv (Python) · pnpm (frontend) · BGE-M3 embeddings (construction-time).

## Repository layout

```text
backend/    FastAPI application (Python, uv)
frontend/   Next.js application (pnpm)
pipeline/   Vocabulary construction pipeline (later phases)
docs/       Project documentation
data/raw/   Immutable source datasets (Git-ignored; see data/raw/README.md)
```

## Prerequisites

- Node 22+ and pnpm (`npm i -g pnpm`)
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 17 (native install; this project runs entirely on one local machine)
- pgvector (needed from Phase 12; see decision.md D004)

## Setup

### 1. Environment

```bash
cp .env.example .env   # adjust DATABASE_URL if your credentials differ
```

### 2. Database

This project is local-only: it uses a native PostgreSQL 17 instance on the
host machine (no containers, no deployment). See `docs/environment.md`.

```bash
createdb -U postgres vocab_platform
psql -U postgres -d vocab_platform -c "CREATE EXTENSION vector;"   # pgvector (D004)
cd backend && uv run alembic upgrade head                          # schema (§63)
```

### 3. Backend

```bash
cd backend
uv sync                     # install dependencies
uv run pytest               # run tests
uv run uvicorn app.main:app --reload --port 8000
```

Health check: `curl http://localhost:8000/api/v1/health`
→ `{"status":"ok","database":"up", ...}`

### 4. Frontend

```bash
cd frontend
pnpm install
pnpm dev                    # http://localhost:3000
```

## Testing

```bash
cd backend  && uv run pytest                        # backend suite (359 tests)
cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint .
cd frontend && pnpm exec vitest run                 # frontend unit tests (26)
cd frontend && pnpm exec playwright test            # E2E acceptance, §59/§60/§61 (docs/e2e.md)
cd backend  && PYTHONPATH=.. uv run python ../scripts/phase28_readiness.py
                                                     # full local-readiness gate (§104, docs/environment.md)
```

Backups and the real restore test: `docs/backups.md`.

## Scope

Local, single-machine operation only (native PostgreSQL 17, `uvicorn` and
`next dev` on the host). There is no container, cloud or deployment target,
and none is needed to satisfy `requiremnts.txt` (it never mentions Docker).
See decision.md D026.

## Development status

All phases (0–29) are complete — see `current-state.md` for the
honest per-phase state and `docs/final-acceptance-report.md` for the
§105 final acceptance verdict (ACCEPTED for local operation, 2026-10-03).
Do not assume any feature works until `current-state.md` marks it
verified.
