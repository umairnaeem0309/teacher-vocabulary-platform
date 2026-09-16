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
- PostgreSQL 17 (native, or Docker via the provided compose file)
- pgvector (needed from Phase 12; see decision.md D004)

## Setup

### 1. Environment

```bash
cp .env.example .env   # adjust DATABASE_URL if your credentials differ
```

### 2. Database

Either use Docker Compose (Docker-capable machines):

```bash
docker compose up -d db
```

…or a native PostgreSQL 17 instance:

```bash
createdb -U postgres vocab_platform
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

## Development status

Phase 0 (project initialization) is complete — see `current-state.md`.
Application features are implemented phase by phase; do not assume any
feature works until `current-state.md` marks it verified.
