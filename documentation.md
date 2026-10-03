# Setup — Run from the GitHub Zip (Client Deliverable)

This is the one-page runbook for the client: download the GitHub zip,
install everything you need, restore the database dump, and run the demo.

> The GitHub zip contains **no data** and **no `node_modules`/`.venv`** —
> those are installed on first run. The only "extra file" you need is the
> database dump (`data/backups/*.dump`, ~231 MiB), which is a separate
> download from where you get the source.

---

## 0. What the client actually gets

| Item | Where from | Size | Purpose |
|---|---|---|---|
| `vocab-platform.zip` | GitHub repo archive | ~50–80 MB | Source, docs, migrations, configs, scripts |
| `vocab_platform_<ts>.dump` | Backups folder (local handoff) | ~231 MiB | Full database (41,690 senses, embeddings, review state) |

Nothing else is needed to run the demo. `data/raw` (2.7 GB) is used only
to rebuild the database and is never committed.

---

## 1. Machine prerequisites (install these once per machine)

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
PYTHONPATH=.. uv run uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend
pnpm dev      # http://localhost:3000
```

> If the backend fails with `ModuleNotFoundError: No module named 'pipeline'`,
> the repo root must be on `PYTHONPATH` at runtime. Run instead:

```bash
cd backend
PYTHONPATH=.. uv run uvicorn app.main:app --reload --port 8000
```

> If that still fails, set `PYTHONPATH` explicitly to the project root:

```bash
cd backend
$env:PYTHONPATH = ".."
uv run uvicorn app.main:app --reload --port 8000
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
| `type "vector" does not exist` | Run `CREATE EXTENSION vector;` on the DB; confirm the `vector` extension files are in `share` and on `search_path`. |
| `pg_dump`/`pg_restore` not found | Set `PG_BIN` to the PostgreSQL `bin` directory. |
| Search returns nothing | Broaden filters; the corpus is sense-level, so a very specific phrase may match fewer senses. |
| Semantic search slowest on first query | The embedding model loads on first use (~260 ms/query on CPU); repeats are cached. |
| Backup task did not run | Open Task Scheduler (Windows) or `crontab -l` (Unix); confirm the interpreter path and `PG_BIN` are valid in the scheduled context. |
| `Cannot find path .env.example` | You ran the `cp` inside `backend/`. It lives at the **repo root**. |
| `uv: command not found` | Add `uv`'s bin dir to `PATH` (Windows: `%USERPROFILE%\.local\bin`). |
| `node: command not found` | Node was not added to `PATH`; restart the terminal. |
| `pnpm: command not found` | Run `npm install -g pnpm` (Node + npm on `PATH`). |
| `createdb: not found` | The PostgreSQL client tools are not on `PATH`; set `PG_BIN` or add the `bin` folder to `PATH`. |
| `extension vector not available` | `CREATE EXTENSION vector SCHEMA public;` or check `shared_preload_libraries`/`pgvector` build. |
| `pip` / `ensurepip` errors on `uv sync` | Install Python 3.12+; on Windows use the official installer with "Add Python to PATH" checked. |

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
