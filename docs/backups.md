# Backups & Restoration (Phase 26, §51/§64/§102)

Local-only scope (D026): the application runs on one machine with a native
PostgreSQL 17 install. Backups are plain `pg_dump` / `pg_restore` runs
against that local server — no cloud, no external service.

Tooling:

- `pipeline/storage/backup.py` — reusable core (backup, retention, restore,
  verify).
- `scripts/db_backup.py` — CLI wrapper.
- `scripts/install_backup_schedule.py` — registers the **automatic daily
  backup** required by §51 (Windows Task Scheduler or cron).

Backups are written to `data/backups/` (`data/backups/` is Git-ignored —
dumps contain the full live database).

## Backup procedure

```bash
cd backend
PYTHONPATH=.. uv run python ../scripts/db_backup.py backup --keep 7
```

- Uses `pg_dump --format=custom`, so one file restores selectively or whole.
- Filename: `vocab_platform_YYYYmmdd_HHMMSS.dump`.
- Connection fields come from `DATABASE_URL` (app settings); the password is
  passed via `PGPASSWORD` for that child process only.
- If the PostgreSQL client tools are not on `PATH`, set `PG_BIN` (e.g.
  `C:/Program Files/PostgreSQL/17/bin`).

List backups newest-first:

```bash
PYTHONPATH=.. uv run python ../scripts/db_backup.py list
```

## Retention procedure

The `backup` command prunes automatically: it keeps the newest **7** dumps
(`--keep`) and deletes older `.dump` files. Non-`.dump` files are never
touched. To change the count, pass a different `--keep` (minimum 1).

## Restore procedure

Restore a dump into a database (created if needed):

```bash
PYTHONPATH=.. uv run python ../scripts/db_backup.py restore \
  ../data/backups/vocab_platform_YYYYmmdd_HHMMSS.dump --target-db vocab_platform
```

- `--no-create` restores into an existing database instead of creating one.
- `--clean` drops existing objects first (`pg_restore --clean --if-exists`).
- `--no-owner --no-privileges` are always used so a dump restores across
  local roles.
- The `vector` extension is recreated by the dump (the extension files are
  installed on the server); no extra step is needed.
- **Caution:** restoring over the live `vocab_platform` replaces its current
  state. Prefer restoring into a scratch name first, then switching.

Minimal disaster-recovery sequence: stop the backend, `restore --target-db
vocab_platform --clean`, apply any newer migrations (`alembic upgrade head`),
restart the backend, confirm `/api/v1/health`.

## Verification (the real restoration test)

`verify` restores the dump into a disposable scratch database on the same
server, compares every public table's row count and the Alembic revision
against the live database, then drops the scratch database:

```bash
PYTHONPATH=.. uv run python ../scripts/db_backup.py verify --fresh --keep 7
```

### Recorded result — 2026-10-02

```text
dump                vocab_platform_20261002_215303.dump
dump size           241,842,655 bytes (~231 MiB)
tables checked      27
source rows         625,084
restored rows       625,084
mismatches          {} (none)
alembic revision    b8e5d1f2a3c4 (source) == b8e5d1f2a3c4 (restored)
scratch database    vocab_restore_test_20261002215423 (dropped after)
result              RESTORE VERIFIED OK
report              data/construction/phase26_restore_report.json
```

This is a genuine restore of the full live database (schema, all 41,687
senses, embeddings, and learning data), not a documented theory.

Automated coverage: `backend/tests/test_backup_tools.py` (7 tests) covers
binary discovery, retention, URL parsing, and a **real** end-to-end
`pg_dump` → `pg_restore` → compare round-trip on a throwaway database. The
full-size run above is the phase-level proof and is re-runnable at any time.

## Automatic backups (§51)

§51 requires the database to be backed up **automatically**. Register a
daily job once (from the repository root):

```bash
python scripts/install_backup_schedule.py install --time 02:00 --keep 7
```

- **Windows:** creates/replaces the Task Scheduler task
  `VocabPlatformBackup` (daily, runs the backend virtualenv interpreter
  with the correct working directory and `PYTHONPATH`).
- **Linux/macOS:** appends a `crontab` line for the current user.
- Both run the exact same `db_backup.py backup --keep 7` command used
  manually, appending to `data/backups/backup.log` so unattended failures
  are diagnosable.

```bash
python scripts/install_backup_schedule.py status   # is it registered?
python scripts/install_backup_schedule.py print    # show the job, no changes
python scripts/install_backup_schedule.py remove   # unregister
```

If the PostgreSQL client tools are not on the scheduler's `PATH`, set
`PG_BIN` in the machine environment (the task inherits it).

## Operational notes

- **Off-site copy:** backups live on the same machine by default. For
  disaster recovery, copy `data/backups/*.dump` to separate storage. This is
  a manual step under the local-only scope.
- **Before risky operations** (bulk imports, migrations), take a backup
  first: `db_backup.py backup`.
- Do not commit dumps: `data/backups/` is Git-ignored.

## Deliverables (BRD §56)

```text
automatic backup      scripts/install_backup_schedule.py install (§51)
backup procedure      this document + scripts/db_backup.py backup
retention procedure   --keep N (default 7), prune_backups()
restore procedure     scripts/db_backup.py restore
restore documentation this document, incl. the recorded real test
```
