# Decision Log

ADR-style log. Decisions are never silently reversed: a superseded decision
stays listed, with the new decision referencing it.

---

# Decision D001

## Date
2026-09-16

## Decision
Use PostgreSQL 17 as the production and development database.

## Reason
The BRD requires PostgreSQL; the platform needs relational integrity,
full-text search and (with pgvector) vector search in one system.

## Alternatives considered
SQLite (construction pipeline only), MongoDB.

## Status
Accepted

---

# Decision D002

## Date
2026-09-16

## Decision
Install PostgreSQL 17 natively on the development machine (Windows) instead
of running it via Docker Compose.

## Reason
Docker is not installed on this machine and WSL is unavailable, so Compose
services cannot run here. Native PostgreSQL 17.11 (EDB build) was installed
via winget and verified running as a Windows service. Docker Compose
configuration is still provided for environments that have Docker.

## Alternatives considered
Docker Desktop (rejected: not installed; WSL missing), WSL2 PostgreSQL
(rejected: WSL not installed).

## Status
Accepted (environment-specific; Compose remains the canonical dev-env config)

---

# Decision D003

## Date
2026-09-16

## Decision
Backend uses a synchronous SQLAlchemy 2 engine with the psycopg3 driver.

## Reason
FastAPI runs sync endpoints on a threadpool; the workload is
database-bound rather than concurrency-bound (single-teacher tool). Sync
SQLAlchemy is simpler, fully supported by Alembic, and avoids async-ORM
pitfalls. Revisit only under measured load.

## Alternatives considered
asyncpg + async ORM (more complexity, weaker Alembic fit), raw psycopg
(no ORM/migrations path).

## Status
Accepted

---

# Decision D004

## Date
2026-09-16

## Decision
pgvector installation is deferred to the point of first need (Phase 12
embeddings). Target: EDB StackBuilder GUI ("Database Extensions → pgvector")
on this machine; fallback: VS Build Tools + source compile.

## Reason
pgvector has no scriptable installer on Windows (StackBuilder is GUI-only
and its download index is not anonymously reachable). It is not required by
any Phase 0–11 deliverable. The health endpoint tests plain PostgreSQL
connectivity, which is what Phase 0 acceptance requires.

## Alternatives considered
Installing VS 2022 Build Tools (~2–6 GB) immediately to compile from source
(rejected: heavy, not needed until Phase 12); switching database technology
(prohibited by master_prompt.md section 121).

## Status
Accepted — OPEN ITEM tracked in current-state.md and plan.md
