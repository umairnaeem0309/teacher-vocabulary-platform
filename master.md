# MASTER.md — Project Constitution

## English–Polish Vocabulary Teaching & FSRS Platform

This file is the permanent project constitution. It is derived from
`master_prompt.md` (implementation decisions) and `requiremnts.txt` (BRD,
functional source of truth). It changes only when a genuinely permanent
project rule changes.

---

## 1. Product Purpose

A production-ready, teacher-facing web application for teaching English
vocabulary to Polish-speaking students. It is a vocabulary discovery,
management, assignment, manual-review and FSRS spaced-repetition system —
not a general-purpose language-learning platform.

Core workflow:

```text
FIND → FILTER → SELECT → ASSIGN → REVIEW → RECORD RESULT → FSRS → NEXT REVIEW
```

## 2. Non-Negotiable Requirements

1. Master vocabulary is global; student learning records are separate.
2. Vocabulary identity is **sense-level** — never English spelling alone.
   `UNIQUE(student_id, master_sense_id)` is mandatory at the database level.
3. CEFR = difficulty. Frequency = occurrence. Vocabulary Priority = learner
   usefulness. Teacher priority = per-student override. Learning state and
   FSRS state = per-student. These concepts remain separate.
4. Comprehensive vocabulary: rare/archaic/technical senses are retained
   (lower priority is allowed; deletion is not).
5. Semantic search uses precomputed embeddings (BGE-M3) + pgvector. No
   external LLM is required for search, classification or priority.
6. Every review creates an immutable review-history event.
7. Raw source data is immutable; provenance is preserved.
8. Incomplete metadata never causes deletion of a vocabulary sense.

## 3. Technology Stack (locked)

| Layer | Choice |
|---|---|
| Frontend | Next.js + TypeScript + Tailwind CSS + shadcn/ui + TanStack Query + TanStack Table |
| Backend | Python + FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic |
| Database | PostgreSQL 17 + pgvector |
| Construction DB | SQLite (pipeline only, never production) |
| Python tooling | uv |
| Frontend tooling | pnpm |
| Dev services | Docker Compose (where available) |
| Embeddings | BAAI/bge-m3, generated at construction time |
| Auth | Email + password, Argon2id, HTTP-only session cookie, server-side sessions in PostgreSQL |
| SRS | FSRS only (HARD→Again, MEDIUM→Hard, EASY→Good); never SM-2 |

## 4. Data Principles

- Sense-level identity with stable internal master sense IDs.
- Pipeline: RAW → ADAPTERS → NORMALIZED → SENSE IDENTITY → TRANSLATIONS →
  DEFINITIONS → CEFR → FREQUENCY → WORDNET → FLAGS → TAXONOMY → PRIORITY →
  QUALITY → EMBEDDINGS → QC → SQLite → PostgreSQL.
- Every stage independently testable; deterministic and reproducible.
- Store provenance and confidence; never silently discard malformed records.
- Stream large datasets; never load the 2.7 GB Wiktextract dump into RAM.

## 5. Security Principles

- Argon2id password hashing; HTTP-only secure session cookies.
- Authorization checks on every protected endpoint; never trust client IDs.
- Student isolation; private links use cryptographically secure tokens.
- Input validation, CSRF protection where applicable, rate limiting where
  appropriate, environment-based secrets, SQL-injection and XSS prevention.
- Never expose credentials, stack traces or internal paths in API responses.

## 6. Testing Principles

- Tests are written with the feature, not after the project.
- Pytest (backend), Vitest (frontend), Playwright (E2E).
- Unit: normalization, sense identity, CEFR, frequency, priority, taxonomy,
  FSRS mapping. Integration: DB, API, search, assignment, auth.
- The final acceptance workflow (master_prompt.md section 59) is automated.

## 7. Git Principles

- Conventional commits; meaningful, scoped changes — never one giant commit.
- Project starts 2026-09-16; chronological dates with `+0500` timezone.
- No artificial contributors or AI attribution in history.
- Never claim implemented features that were not tested.

## 8. Documentation Rules

Mandatory at repo root: `master.md`, `decision.md`, `current-state.md`,
`architecture.md`, `plan.md`, `README.md`, plus `docs/` as needed.
`current-state.md` must reflect reality (PARTIAL / NOT VERIFIED / DEFERRED
statuses are used when honest). Documentation is updated every phase.

## 9. Implementation Phases

Phases 0–29 as defined in `master_prompt.md` sections 76–105 and tracked in
`plan.md`. Sequential execution: no phase starts while a dependency phase is
knowingly broken.

## 10. Prohibited Shortcuts

- Never: SQLite in production, SM-2, deleting rare vocabulary, CEFR-as-
  usefulness, spelling-as-identity, per-search/per-record LLM calls,
  manual categorization of every sense, loading enormous files into RAM,
  skipping tests, placeholder data where real data exists, hardcoded
  results/dates, duplicated master vocabulary per student, silent record
  loss, single-phase builds, one giant commit.
