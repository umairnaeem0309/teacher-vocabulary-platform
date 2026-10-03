# Setup — Run from the GitHub Zip (Client Deliverable)

This is the one-page runbook for the client: download the GitHub zip,
install the prerequisites, restore the database dump, and run the demo.

---

## 1. Prerequisites (one-time per machine)

| Component | Required | Notes |
|---|---|---|
| PostgreSQL | 17 | Native install. `postgres` user / `postgres` password / `localhost:5432` |
| `vector` extension | Yes | `CREATE EXTENSION vector;` on the `vocab_platform` database |
| Python | 3.12+ | For the backend |
| `uv` | Yes | https://docs.astral.sh/uv/ — used to install the backend |
| Node.js | 22+ | For the frontend |
| `pnpm` | Yes | `npm install -g pnpm` |
| Browser | Chrome | Used for the demo and the automated check |

> The GitHub zip contains **no data** and **no `node_modules`/`.venv`** —
> those are installed on first run.

---

## 2. Get the project

1. Download `vocab-platform.zip` from GitHub and unzip it somewhere
   permanent, e.g. `C:\VocabularyPlatform`.
2. Open a terminal in that folder.

---

## 3. Environment file

```bash
cp .env.example .env
```

Edit `.env` **only if** your PostgreSQL user, password, or port differ
from the defaults (`postgres` / `postgres` @ `localhost:5432`).

---

## 4. Database (schema + vector extension)

```bash
createdb -U postgres vocab_platform
psql -U postgres -d vocab_platform -c "CREATE EXTENSION vector;"
```

---

## 5. Backend (install + migrate)

```bash
cd backend
uv sync
uv run alembic upgrade head
```

If you restored a dump that predates the current schema, also run:

```bash
uv run alembic upgrade head
```

---

## 6. Load the vocabulary data (from the dump, not `data/raw`)

The GitHub zip ships with a **database dump** under
`data/backups/` (the original `data/raw` corpora are **not** needed):

```bash
uv run python ../scripts/db_backup.py restore \
  ../data/backups/vocab_platform_YYYYmmdd_HHMMSS.dump \
  --target-db vocab_platform --clean
```

- `--clean` drops existing objects first.
- `--no-owner --no-privileges` are always used, so a dump restores across
  local roles.
- The `vector` extension is recreated by the dump itself.
- The dump contains the built corpus + review data (~41,690 senses,
  embeddings, and learning state). It is a **custom-format** `pg_dump`
  restore, not a re-run of the multi-hour construction pipeline.

> If the PostgreSQL `pg_dump`/`pg_restore` client tools are not on your
> `PATH`, set `PG_BIN` to the PostgreSQL `bin` folder, e.g.
> `C:/Program Files/PostgreSQL/17/bin`.

---

## 7. Frontend

```bash
cd ../frontend
pnpm install
```

---

## 8. First run & teacher account

Start the backend in one terminal and the frontend in another:

```bash
# terminal 1
cd backend
uv run uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend
pnpm dev      # http://localhost:3000
```

On first launch the app opens a one-time **bootstrap** window where you
create the single teacher account; afterwards, log in normally.

Health check: `curl http://localhost:8000/api/v1/health`
→ `{"status":"ok","database":"up", ...}`.

---

## 9. Automatic backups (optional but recommended)

Register a daily backup (Windows Task Scheduler or cron), from the repo
root:

```bash
python scripts/install_backup_schedule.py install --time 02:00 --keep 7
```

Check it with `... status`, show the job with `... print`, remove it with
`... remove`. See `docs/backups.md` for the full procedure.

---

## 10. Verify the install

```bash
cd backend && uv run pytest
cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint . && pnpm exec vitest run
```

Expected: backend **379 passed**, frontend type-check and lint clean,
unit tests **27 passed**. The Playwright suite (`pnpm exec playwright
test`, 7 tests) exercises the full workflow against the real stack.

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `password authentication failed` | Check `DATABASE_URL` in `.env`; PostgreSQL running. |
| `type "vector" does not exist` | Run `CREATE EXTENSION vector;` on the DB. |
| `pg_dump`/`pg_restore` not found | Set `PG_BIN` to the PostgreSQL `bin` directory. |
| Search returns nothing | Broaden filters; the corpus is sense-level, so very specific phrases match fewer senses. |
| Semantic search slowest on first query | Embedding model loads on first use (~260 ms/query on CPU); repeats are cached. |
| Backup task did not run | Open Task Scheduler (Windows) or `crontab -l` (Unix); confirm the interpreter path and `PG_BIN` are valid in the scheduled context. |
| `Cannot find path .env.example` | You ran the `cp` inside `backend/`. It lives at the **repo root**. |
| `ensurepip`/`uv sync` fails | Install Python 3.12+ or run `uv self update`; on Windows use the official installer. |

---

## 12. Quick day-to-day demo flow

1. **Login** (`/login`) — teacher account.
2. **Dashboard** (`/dashboard`) — who needs review next (overdue → due → name).
3. **Vocabulary** (`/vocabulary`) — type a topic phrase, switch `lexical` /
   `semantic` / `hybrid`, change sort, use the filter facets.
4. **Translation availability** (`translation_availability` filter):
   `missing` / `multiple` / `reliable` / `uncertain`.
5. **Copy** — select rows, use the 4 copy buttons (EN / EN+PL / EN+def /
   all).
6. **Sets** (`/sets`) — create a set, edit, remove items, **Assign set** to a
   student.
7. **Review** (`/students/<id>/review`) — HARD/MEDIUM/EASY, FSRS next due,
   URL params `set=` / `difficult=yes` / `states=` / `search=`.
8. **Shortcuts** (`/settings/shortcuts`) — change keys, save.
9. **Backup scheduler** — Task Scheduler task `VocabPlatformBackup` (or
   `crontab -l`).

---

## 13. Where to read more

| Document | Contents |
|---|---|
| `README.md` | Quick start and repository overview |
| `documentation.md` | Project overview, features, setup, troubleshooting |
| `plan.md` | Phase-by-phase implementation plan |
| `docs/backups.md` | Backup / retention / restore / automatic scheduling |
| `decision.md` | Architecture decisions (local-only scope, D007 confidence threshold, etc.) |
