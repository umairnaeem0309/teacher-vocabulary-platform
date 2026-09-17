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

---

# Decision D005

## Date
2026-09-17

## Decision
All API errors — domain, schema-validation, framework and unhandled — return
one uniform envelope:
`{"error": {"code", "message", "details", "request_id"}}`.
Endpoints whose functionality belongs to a later phase are registered as
honest 501 stubs (code `not_implemented`, with the planned phase in details)
instead of being omitted or faked.

## Reason
Section 55 requires structured, consistent, actionable, safe errors. A single
envelope lets the frontend have one error path (ApiError) and gives users a
correlation ID that matches server logs (section 56). The 501 convention keeps
the API surface complete and self-documenting from Phase 1 while never
claiming unimplemented features work.

## Alternatives considered
RFC 7807 problem+json (viable, but adds negotiation complexity without a
consumer that needs it); per-domain error shapes (rejected: inconsistent,
duplicated client handling); omitting unimplemented endpoints (rejected:
clients and tests cannot distinguish "missing" from "planned").

## Status
Accepted
