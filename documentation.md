# Setup — Run from the GitHub Zip (Client Deliverable)

This is the one-page runbook for the client: download the GitHub zip,
install everything you need, restore the database dump, and run the demo.

> The GitHub zip contains **no data** and **no `node_modules`/`.venv`** —
> those are installed on first run. Two things come from **outside** the
> zip: the **database dump** (`data/backups/*.dump`, ~386 MiB, a separate
> download) and the **embedding model** (BGE-M3 — a few GB, auto-downloaded
> on the first run, or supplied as a `data/models/` folder for offline use).

---

## 0. What the client actually gets

| Item | Where from | Size | Purpose |
|---|---|---|---|
| `vocab-platform.zip` | GitHub repo archive | ~50–80 MB | Source, migrations, configs, scripts |
| `vocab_platform_<ts>.dump` | Backups folder (local handoff) | ~386 MiB | Full database (71,149 senses, embeddings, review state) |
| BGE-M3 embedding model | Auto-downloaded on first run, **or** handed over as `data/models/` | ~2.3 GB (download) · ~7.6 GB (as a folder) | Encoder for `semantic` / `hybrid` search |

The zip carries **no data and no dev docs**: `data/`, `docs/`, and the
constitution / plan files (`master.md`, `decision.md`, `current-state.md`,
`architecture.md`, `plan.md`, `master_prompt.md`, `requiremnts.txt`) are
Git-ignored and therefore **not** in the archive. Two things are supplied
outside the zip:

1. **The database dump** — a separate ~386 MiB download; drop it in
   `data/backups/` (§6).
2. **The embedding model (BAAI/bge-m3)** — required for `semantic`/`hybrid`
   search. On the first run it is downloaded automatically (a few GB,
   **internet needed once**) into `data/models/`. To run fully offline,
   place a pre-downloaded `data/models/` folder next to the source
   (the cache here is ~7.6 GB — it holds both weight formats).

`data/raw` (2.7 GB) is used only to rebuild the database and is never
shipped.

---

## 1. Machine prerequisites (install these once per machine)

**Hardware:** a 64-bit machine with **8 GB RAM and ~10 GB free disk**
at minimum. `semantic`/`hybrid` search holds the BGE-M3 model in memory
(~3.3 GB), so 8 GB works but should not also be running other heavy
applications; 4 GB machines should stick to `mode=lexical`.

Open PowerShell **as Administrator** and run the relevant commands.

### Windows 10/11

```powershell
# 1) Node.js 22+ (https://nodejs.org/) — check with: node -v
# 2) pnpm (https://pnpm.io/installation#using-chocolatey)
winget install pnpm

# 3) Python 3.12+ (https://www.python.org/downloads/) — check with: python --version
#    During install, tick "Add Python to PATH".

# 4) uv (https://docs.astral.sh/uv/getting-started/installation/)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 5) PostgreSQL 17 (https://www.postgresql.org/download/windows/)
#    During install: set superuser password to postgres / keep port 5432.
# 6) pgvector (https://github.com/pgvector/pgvector) — see "Enable vector" below.

# 7) Git (https://git-scm.com/download/win) — check with: git --version
```

#### Enable the `vector` extension for PostgreSQL 17

```powershell
# 1) Unzip pgvector into PostgreSQL's share dir (replace the version/number
#    with what you installed, e.g. C:/Program Files/PostgreSQL/17).
#    Default URL: https://github.com/pgvector/pgvector/archive/refs/tags/v0.7.2.zip
Expand-Archive -Path "C:/pgvector-0.7.2.zip" -DestinationPath "C:/temp/pgvector"
Copy-Item "C:/temp/pgvector/pgvector--0.7.2--0.7.2.sql" \
  "C:/Program Files/PostgreSQL/17/share"
Copy-Item "C:/temp/pgvector/pgvector.control" \
  "C:/Program Files/PostgreSQL/17/share"

# 2) Open pgAdmin → select the `vocab_platform` database →
#    Query tool → run:
CREATE EXTENSION vector;
#    (If you get "extension is not available", also run:
#    CREATE EXTENSION vector SCHEMA public;)
```

### Windows (older than PowerShell 5.1) / manual notes

- If `winget` is not available, install it from
  <https://github.com/microsoft/winget-cli>, or use the Node.js, Python,
  and PostgreSQL *standalone installers* instead (tick "Add to PATH").
- The `uv` installer uses PowerShell; if blocked by execution policy, run
  `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
  once, then retry.

### Mac / Linux

```bash
# 1) Node.js 22+ (https://nodejs.org/)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -   # Debian/Ubuntu
sudo apt-get install -y nodejs

# 2) pnpm
npm install -g pnpm

# 3) Python 3.12+ (usually preinstalled on macOS; on Ubuntu: sudo apt install python3.12)
python3 --version

# 4) uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 5) PostgreSQL 17 + pgvector
sudo apt-get install -y postgresql-17 postgresql-17-pgvector   # Debian/Ubuntu
#    or: brew install postgresql@17 pgvector                   # macOS

# 6) Git
sudo apt-get install -y git          # Debian/Ubuntu
brew install git                     # macOS
```

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

Create `.env` at the **repo root**. The `scripts/*` utilities read it from
there directly; the backend resolves `.env` relative to its own working
directory, so start it with `--env-file ../.env` (the commands in §8
already do). One root `.env` then configures everything.

Edit `.env` **only if** your PostgreSQL user, password, or port differ
from the defaults (`postgres` / `postgres` @ `localhost:5432`).

---

## 4. Database (create + vector extension)

### Windows: add PostgreSQL `bin` to `PATH` first
The PostgreSQL client tools (`createdb`, `psql`, `pg_dump`, `pg_restore`)
are **not** on the system `PATH` by default. Open **PowerShell as
Administrator** once, then run:

```powershell
# 1) Find what you installed (usually C:\Program Files\PostgreSQL\17)
Get-ChildItem 'C:\Program Files\PostgreSQL' -Directory

# 2) Add it to this session's PATH
$env:PG_BIN = "C:\Program Files\PostgreSQL\<VERSION>\bin"
$env:Path += ";" + $env:PG_BIN

# 3) Verify
createdb --version
psql --version
```

> Optional but cleaner: permanently add the same `bin` folder to your
> system `PATH` (Settings → System → About → Advanced system settings →
> Environment Variables → Path → Edit → New). Then start a **new** terminal
> and run the three commands in §4 without `PG_BIN`.

```bash
createdb -U postgres vocab_platform
psql -U postgres -d vocab_platform -c "CREATE EXTENSION vector;"
```

> If `psql` is not on your `PATH`, start it from the PostgreSQL `bin`
> folder, e.g. `C:/Program Files/PostgreSQL/17/bin/psql`.

---

## 5. Backend (install + migrate)

```bash
cd backend
uv sync
uv run alembic upgrade head
```

Run `alembic upgrade head` again after restoring a dump that predates the
current schema (§6) — the dump restores data, not the migration stamp.

---

## 6. Load the vocabulary data (from the dump, not `data/raw`)

The dump is **not** inside the GitHub zip. Put the supplied
`vocab_platform_<ts>.dump` under `data/backups/` (create the folder), then
restore it (still in `backend/`; the `..` paths are relative to it):

```bash
uv run python ../scripts/db_backup.py restore \
  ../data/backups/vocab_platform_YYYYmmdd_HHMMSS.dump \
  --target-db vocab_platform --clean
```

- `--clean` drops existing objects first; the target database is created
  if it does not exist yet.
- `--no-owner --no-privileges` are always used, so a dump restores across
  local roles.
- The `vector` extension is recreated by the dump itself.
- `db_backup.py` puts the repo root on `sys.path` itself, so no
  `PYTHONPATH` is needed here.
- The dump contains the built corpus + review data (~71,149 senses,
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
PYTHONPATH=.. uv run uvicorn app.main:app --reload --port 8000 --env-file ../.env

# terminal 2
cd frontend
pnpm dev      # http://localhost:3000
```

> If the backend fails with `ModuleNotFoundError: No module named 'pipeline'`,
> the repo root must be on `PYTHONPATH` at runtime. Set it explicitly:

```bash
cd backend
$env:PYTHONPATH = ".."
uv run uvicorn app.main:app --reload --port 8000 --env-file ../.env
```

On first launch there is no account yet. Open `http://localhost:3000` — it
forwards straight to `/login`. Click **Create the first teacher account**,
fill in display name, email and password (min. 10 characters); the form
calls `POST /api/v1/auth/bootstrap`, a window the backend keeps open **only
until the first teacher exists** (afterwards it answers `403
bootstrap_closed` and the form falls back to sign-in). Thereafter sign in
normally at `/login`.

> **Restored a `data/backups/*.dump`?** The dump already contains the
> teacher account it was created with (for the handoff dump that
> accompanies this project that account is `test@gmail.com`), so the create
> window is closed and `POST /api/v1/auth/bootstrap` answers
> `403 bootstrap_closed`. Sign in with that account if you know its
> password.
>
> **Prefer your own account (or don't know the password)?** Reopen the
> create window by deleting the existing teacher(s). This also removes
> teacher-owned rows — students, sets, review history — and leaves the
> vocabulary corpus untouched. Run this in pgAdmin's query tool (or via
> `psql`) against `vocab_platform`:
>
> ```sql
> BEGIN;
> DELETE FROM review_events
>  WHERE teacher_id IN (SELECT id FROM teachers)
>     OR student_id IN (SELECT id FROM students WHERE teacher_id IN (SELECT id FROM teachers));
> DELETE FROM student_fsrs_states
>  WHERE student_vocabulary_id IN (
>    SELECT sv.id FROM student_vocabulary sv
>    JOIN students s ON s.id = sv.student_id
>    WHERE s.teacher_id IN (SELECT id FROM teachers));
> DELETE FROM teacher_priority_overrides
>  WHERE student_id IN (SELECT id FROM students WHERE teacher_id IN (SELECT id FROM teachers));
> DELETE FROM student_vocabulary
>  WHERE student_id IN (SELECT id FROM students WHERE teacher_id IN (SELECT id FROM teachers));
> DELETE FROM students WHERE teacher_id IN (SELECT id FROM teachers);
> DELETE FROM vocabulary_set_items
>  WHERE set_id IN (SELECT id FROM vocabulary_sets WHERE teacher_id IN (SELECT id FROM teachers));
> DELETE FROM vocabulary_sets WHERE teacher_id IN (SELECT id FROM teachers);
> DELETE FROM teacher_sessions WHERE teacher_id IN (SELECT id FROM teachers);
> DELETE FROM teachers;
> COMMIT;
> SELECT count(*) AS teachers_remaining FROM teachers;  -- must be 0
> ```
>
> Then refresh `/login` and use **Create the first teacher account**.
> Recover anything you miss by restoring the dump again (§6).
>
> (The development helper `scripts/reset_teachers.sql` performs these same
> deletions, but it is Git-ignored and therefore **not** in the zip.)

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
`... remove`. Backups are written to `data/backups/` (the newest `--keep`
are retained) and those files are exactly what §6 restores from.

---

## 10. Verify the install

```bash
cd backend && uv run pytest
cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint . && pnpm exec vitest run
```

Expected: backend **381 passed**, frontend type-check and lint clean,
unit tests **28 passed**. The Playwright suite (`pnpm exec playwright
test`, 9 tests) exercises the full workflow against the real stack —
including a navigation/endpoint sweep (`e2e/navigation.spec.ts`) that
walks every sidebar route and calls every read endpoint the UI uses.

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `404` on auth calls | Every API path is versioned — use `POST /api/v1/auth/bootstrap`, `POST /api/v1/auth/login`, `GET /api/v1/auth/session`. |
| Sign-in fails right after a dump restore | The dump already contains a teacher, so bootstrap is closed (`403 bootstrap_closed`) and only that account can sign in — see §8. |
| CORS / "failed to fetch" from the browser | Open the app at `http://localhost:3000` (not `127.0.0.1`) and confirm `CORS_ORIGINS` and `ALLOWED_REQUEST_ORIGINS` in `.env` list that origin. |
| Login page shows the connection error | The backend is not running — start it on port 8000 and re-check `/api/v1/health`. |
| `password authentication failed` | Check `DATABASE_URL` in `.env`; PostgreSQL running. |
| `type "vector" does not exist` | Run `CREATE EXTENSION vector;` on the DB; confirm the `vector` extension files are in `share` and on `search_path`. |
| `pg_dump`/`pg_restore` not found | Set `PG_BIN` to the PostgreSQL `bin` directory. |
| Search returns nothing | Broaden filters; the corpus is sense-level, so a very specific phrase may match fewer senses. |
| Semantic search is slow on the very first run | The BGE-M3 model (a few GB) loads in the background at startup (`EMBEDDING_WARMUP=true`). A fresh install also **downloads** it from Hugging Face on that first run — allow a few minutes and an internet connection, or supply a pre-populated `data/models/`. Later starts load from the local cache with no network calls. |
| `semantic`/`hybrid` search fails or hangs with no internet | The model cache is missing. Copy a `data/models/` folder into the repo, or use `mode=lexical`, which needs no model. |
| Edited `.env` at the repo root but the backend ignores it | Start uvicorn with `--env-file ../.env` (see §8). The backend reads `.env` relative to its working directory, not the repo root; the `scripts/*` tools do read the root `.env`. |
| `docs/…`, `master.md`, `decision.md` not found | Those are Git-ignored development notes and are **not** shipped in the zip. The client-facing docs are this file and `README.md`. |
| Backup task did not run | Open Task Scheduler (Windows) or `crontab -l` (Unix); confirm the interpreter path and `PG_BIN` are valid in the scheduled context. |
| `Cannot find path .env.example` | You ran the `cp` inside `backend/`. It lives at the **repo root**. |
| `uv: command not found` | Add `uv`'s bin dir to `PATH` (Windows: `%USERPROFILE%\.local\bin`). |
| `node: command not found` | Node was not added to `PATH`; restart the terminal. |
| `pnpm: command not found` | Run `npm install -g pnpm`, or `corepack enable` (pnpm is pinned via `packageManager` in `frontend/package.json`); open a **new** terminal afterwards. Fallback: `npx pnpm@12.6.0 dev`. Never use `npm install` in `frontend/` — it ignores `pnpm-lock.yaml`. |
| `createdb: not found` | The PostgreSQL client tools are not on `PATH`; set `PG_BIN` or add the `bin` folder to `PATH`. |
| `extension vector not available` | `CREATE EXTENSION vector SCHEMA public;` or check `shared_preload_libraries`/`pgvector` build. |
| `pip` / `ensurepip` errors on `uv sync` | Install Python 3.12+; on Windows use the official installer with "Add Python to PATH" checked. |

---

## 12. Quick day-to-day demo flow

1. **Login** (`/login`) — teacher account; sign-in lands on the **Dashboard**.
2. **Dashboard** (`/dashboard`) — KPI totals, who needs review next (overdue →
   due → name), quick links to every area, and a live API/database status card.
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
