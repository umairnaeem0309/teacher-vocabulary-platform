# Local Development Environment

This document records how the development environment is actually set up on
the primary development machine. The project is local-only: the application
runs natively on this machine with a native PostgreSQL 17 install.

## Primary machine (Windows)

- **PostgreSQL 17.11** installed natively via `winget install
  PostgreSQL.PostgreSQL.17` (EDB build). Runs as Windows service
  `postgresql-x64-17`. Superuser `postgres` with a local development
  password configured during install.
- Database `vocab_platform` created (UTF8).
- **pnpm 12.6.0** enabled via `npm i -g pnpm` (corepack shims on this machine
  are broken — see troubleshooting below).
- **uv 0.10.9** manages the backend virtualenv (`backend/.venv`).
- Connection string used locally:
  `postgresql+psycopg://postgres:<password>@localhost:5432/vocab_platform`
  (stored only in `.env`, which is Git-ignored).

## Containers removed (2026-10-02, D026)

The original Docker/Compose scaffolding (`docker-compose.yml`,
`backend/Dockerfile`, `frontend/Dockerfile`) was deleted: the product scope is
a single local machine, Docker was never executable here (D002), and
`requiremnts.txt` never requires containers. See decision.md D026.

## pgvector on this machine (D004)

1. Open **StackBuilder** (Start Menu → PostgreSQL 17).
2. Select the PostgreSQL 17 installation → **Database Extensions**.
3. Choose **pgvector** → download and install.
4. Verification: `SELECT * FROM pg_available_extensions WHERE name = 'vector';`
   (must list the extension), then `CREATE EXTENSION vector;` in
   `vocab_platform`.

Fallback if StackBuilder does not offer pgvector: install VS 2022 Build
Tools (C++ workload) + PostgreSQL headers, clone pgvector, build with
`nmake /f Makefile.win`, then copy the DLL/SQL/control files into the PostgreSQL
17 installation. This fallback is a last resort — see D004.

## Readiness verification (Phase 28, D030)

The full §104 checklist runs as one gate:

```bash
cd backend
PYTHONPATH=.. uv run python ../scripts/phase28_readiness.py        # all 18 checks (~26 min)
PYTHONPATH=.. uv run python ../scripts/phase28_readiness.py --fast  # quick subset
PYTHONPATH=.. uv run python ../scripts/phase28_readiness.py --only tests.backend
```

Results merge into `data/construction/phase28_readiness_report.json`
(Git-ignored). Database checks use a disposable
`vocab_platform_readiness` database (created and dropped by the script);
the development database is never migrated down or bootstrapped
(D015/D030). Last full run: **18 passed / 0 failed / 0 skipped**
(2026-10-03).

## Troubleshooting

- **corepack `pnpm` fails with MODULE_NOT_FOUND** on this machine: corepack's
  shim cache is corrupted. Fix: `corepack disable` then `npm i -g pnpm`.
- **Python console prints UnicodeEncodeError on Polish text**: Windows
  console defaults to cp1252; use `PYTHONIOENCODING=utf-8` when scripting.
- **psql not on PATH**: it lives at
  `C:\Program Files\PostgreSQL\17\bin\psql.exe`.
- **Scripts fail with "password authentication failed" against a correct
  password**: never build a connection URL from `str(url)` — SQLAlchemy
  renders the password as `***`. Keep the `URL` object; use
  `url.render_as_string(hide_password=False)` only when a real string is
  needed (D030).
- **`mypy app` reports import-untyped on openpyxl after `uv sync`**: the
  `mypy-stubs` group used to be non-default and a sync pruned it. Fixed
  in `backend/pyproject.toml` via
  `tool.uv.default-groups = ["dev", "mypy-stubs"]` (Phase 28).
