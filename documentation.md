# English–Polish Vocabulary Platform — Client Documentation

A teacher-facing web application for teaching English vocabulary to
Polish-speaking students. It covers the whole loop: **discover** useful
vocabulary from a large curated corpus, **organise** it, **assign** it to
students without duplicates, and **review** it with FSRS spaced
repetition until it is learned.

This document explains what the platform does, how to set it up on a
machine, how to run it day to day, and how to keep the data safe.

---

## 1. What this is

- **For:** one teacher working with their Polish-speaking students.
- **Runs:** entirely on one local machine. No cloud account, no server
  rental, no monthly cost. (Decision D026: local-only scope.)
- **Built with:** Next.js + TypeScript (frontend) · FastAPI + PostgreSQL 17
  + pgvector (backend). See `architecture.md` for the full technical view.

The vocabulary itself is a **sense-level** corpus of ~41,690 English
senses built from trusted sources (Wiktextract, English WordNet, NGSL,
CEFR-J), each with definitions, Polish translations, CEFR level,
priority and frequency evidence.

---

## 2. What it can do (features)

### Vocabulary discovery
- **Lexical search** over English headwords, Polish translations and
  definitions (PostgreSQL full-text search), including prefix matching.
- **Semantic search** — describe a topic in plain English
  ("things needed when traveling") and get relevant vocabulary even when
  the exact words never appear together.
- **Hybrid search** — a documented, deterministic blend of lexical +
  semantic + metadata (0.60/0.35/0.05), with an exact-headword floor.
- **Filters** (compose in the database): CEFR level, part of speech,
  priority level (incl. "HIGH+"), topic/category (with all
  subcategories), frequency bands, flags (rare/archaic/technical…),
  student assignment, learning state, due now, difficult, teacher
  priority, and **translation availability** (reliable / multiple /
  uncertain / missing Polish — §42).
- **Sorting** by relevance, headword, Polish translation, CEFR, topic,
  part of speech, priority, frequency, or the student's learning status.
- **Dense workbench table** with multi-select, server-side pagination,
  and a shareable URL for every view (query, filters, sort, page).

### Copy to students (§20/§37)
Select rows in the workbench and copy them to the clipboard in four
formats, ready to paste into a message:
- English only
- English — Polish
- English — definition
- English — Polish — definition

### Vocabulary sets (§26)
Group any senses into a named set (sets reference the master senses, so
they never duplicate vocabulary), rename/describe them, add/remove items,
and assign a whole set to a student in one action.

### Students & assignment (§28–§30)
- Create/edit students; every screen is isolated to your own students.
- **Assign** senses or sets; duplicates are prevented at the application
  and database layers, and the report tells you what was new vs already
  assigned.
- See a student's assigned vocabulary, filterable by due/overdue/
  difficult/learning state.

### Review with FSRS (§31–§38)
- **Review queue**: overdue first, then due today, then new cards.
- **Selection** (§36): focus a session on a vocabulary set, difficult
  cards, particular learning states, or a headword search.
- Rate each card **HARD / MEDIUM / EASY** (mapped to FSRS Again/Hard/Good);
  the next due date is computed by the FSRS-6 algorithm.
- **Configurable keyboard shortcuts** (§35): set the keys for
  reveal/HARD/MEDIUM/EASY in Settings.
- **Reset or adjust** a card's review state where appropriate (§38) —
  reset returns it to new; the review history is still kept.
- Learning states: NEW → ASSIGNED → ENCOUNTERED → LEARNING → REVIEWING →
  MASTERED.

### Dashboards
- Per-student profile with due/overdue counts, difficult cards and recent
  reviews.
- Teacher dashboard overview.

### Import / export
Export vocabulary to CSV, XLSX or JSON; import with validation and a
§29-style report.

### Security
Teacher login with Argon2id password hashing, server-side sessions,
rate limiting, origin checks and secure headers. Students do **not** log
in — the teacher shares vocabulary with them as text (copy feature).

---

## 3. Machine requirements

| Component | Requirement |
|---|---|
| Operating system | Windows 10/11 (primary target), or Linux/macOS |
| Node.js | 22 or newer |
| pnpm | `npm install -g pnpm` |
| Python | 3.12 or newer |
| uv | https://docs.astral.sh/uv/ |
| PostgreSQL | 17 (native install) |
| pgvector | the `vector` extension for PostgreSQL 17 |
| Disk | ~15 GB free (source data + database + tool caches) |
| Browser | any modern browser (Chrome is used for the automated tests) |

---

## 4. Setting up on a new machine

> The order matters: database → backend → frontend → data.

### 4.1 Get the project
Unzip the project folder somewhere permanent, e.g.
`C:\VocabularyPlatform`. Open a terminal in that folder.

### 4.2 Environment file
```bash
cp .env.example .env
```
Edit `.env` only if your PostgreSQL user/password/port differ from the
defaults (`postgres` / `postgres` @ `localhost:5432`).

### 4.3 Database
Create the database and enable pgvector:
```bash
createdb -U postgres vocab_platform
psql -U postgres -d vocab_platform -c "CREATE EXTENSION vector;"
```
Apply the schema:
```bash
cd backend
uv sync
uv run alembic upgrade head
```

### 4.4 Load the vocabulary data
The platform ships with a **database dump** (the built corpus + review
data) under `data/backups/`. Restore it instead of re-running the
multi-hour construction pipeline:
```bash
cd backend
PYTHONPATH=.. uv run python ../scripts/db_backup.py restore \
  ../data/backups/vocab_platform_YYYYmmdd_HHMMSS.dump --target-db vocab_platform --clean
```
If the PostgreSQL client tools (`pg_dump`/`pg_restore`) are not on the
system `PATH`, set `PG_BIN` to the PostgreSQL `bin` folder (e.g.
`C:/Program Files/PostgreSQL/17/bin`).
Migrate forward if the dump predates the current schema:
```bash
uv run alembic upgrade head
```

### 4.5 Frontend
```bash
cd ../frontend
pnpm install
```

### 4.6 First run & teacher account
Start the backend, then the frontend (two terminals):
```bash
# terminal 1
cd backend && uv run uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend && pnpm dev     # http://localhost:3000
```
On first launch the app opens a one-time **bootstrap** window where you
create the single teacher account; afterwards, log in normally.

Health check: `curl http://localhost:8000/api/v1/health`
→ `{"status":"ok","database":"up", ...}`.

### 4.7 Automatic backups (§51)
Register a daily backup (Windows Task Scheduler or cron), from the
project root:
```bash
python scripts/install_backup_schedule.py install --time 02:00 --keep 7
```
Check it with `... status`, show the job with `... print`, remove it with
`... remove`. See `docs/backups.md` for details and the restore/verify
procedure.

---

## 5. Day-to-day use

1. **Find vocabulary** — open *Vocabulary*, type a search or use a topic
   phrase, narrow with filters, and sort as needed.
2. **Build a set or assign** — tick the senses you want, then either
   *Assign* them to a student or *Add to set*.
3. **Copy for a student** — with rows selected, use the **copy** buttons
   (EN / EN+PL / EN+def / all) and paste into a message.
4. **Review** — open a student, click *Start review* (or *Review
   difficult* / *Review set*) and work through the queue with the
   keyboard.
5. **Track progress** — the student profile and dashboard show due,
   overdue, difficult and recent activity.

---

## 6. Keeping data safe

- A **daily automatic backup** runs once you register the scheduled job
  (section 4.7). Dumps go to `data/backups/` and the newest 7 are kept.
- Take a **manual backup** before any risky operation:
  ```bash
  cd backend
  PYTHONPATH=.. uv run python ../scripts/db_backup.py backup --keep 7
  ```
- **Verify a backup restores** (real restoration test into a scratch DB):
  ```bash
  PYTHONPATH=.. uv run python ../scripts/db_backup.py verify --fresh
  ```
- Copy dumps **off the machine** for real disaster recovery — the
  backups live locally by default.

Full details: `docs/backups.md`.

---

## 7. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `password authentication failed` | Check `DATABASE_URL` in `.env`; make sure PostgreSQL is running. |
| `type "vector" does not exist` | pgvector not installed: run `CREATE EXTENSION vector;` on the database. |
| `pg_dump`/`pg_restore` not found | Set `PG_BIN` to the PostgreSQL `bin` directory. |
| Search returns nothing | Broaden filters; the corpus is sense-level, so a very specific phrase may match fewer senses. |
| Semantic search slowest on first query | The embedding model loads on first use (~260 ms/query on CPU); repeats are cached. |
| Backup task did not run | Open Task Scheduler (Windows) or `crontab -l` (Unix); confirm the interpreter path and `PG_BIN` are valid for the scheduled context. |

---

## 8. Verifying the installation

From the project root:
```bash
cd backend  && uv run pytest
cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint . && pnpm exec vitest run
```
Expected current results: backend **379 passed**, frontend type-check and
lint clean, unit tests **27 passed**. The end-to-end acceptance suite
(`pnpm exec playwright test`, 7 tests) exercises the full workflow against
the real stack.

For a full local-readiness report (clean install, clean database,
migrations, production stack, backups, docs) run:
```bash
cd backend && PYTHONPATH=.. uv run python ../scripts/phase28_readiness.py
```

---

## 9. Where to read more

| Document | Contents |
|---|---|
| `README.md` | Quick start and repository overview |
| `architecture.md` | How the system is actually built |
| `current-state.md` | Honest per-phase status (what is verified) |
| `plan.md` | Phase-by-phase implementation plan |
| `decision.md` | Every architecture decision (D001–D031) |
| `docs/search.md` | Search architecture, sorts, filters, performance |
| `docs/backups.md` | Backup / retention / restore / automatic scheduling |
| `docs/e2e.md` | End-to-end acceptance test harness |
| `docs/final-acceptance-report.md` | §105 acceptance verdict and evidence |
