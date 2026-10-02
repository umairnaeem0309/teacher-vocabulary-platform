"""Local PostgreSQL backup, retention, restore and verification (Phase 26, §64/§102).

The project is local-only (D026), so backups are plain ``pg_dump``/
``pg_restore`` runs against the local PostgreSQL server — no cloud, no
scheduler, no external service. This module is the reusable core; the CLI
lives in ``scripts/db_backup.py``.

Design:

- **Backup**: custom-format ``pg_dump -Fc`` into ``data/backups/`` with a
  timestamped name, so a single file can be restored selectively or whole.
- **Retention**: keep the newest N dumps, delete older ones (never touches
  non-``.dump`` files).
- **Restore**: ``pg_restore`` into a target database (creating it when
  needed), ``--no-owner --no-privileges`` so it works across local roles.
- **Verify** (the real restoration test): restore the dump into a
  disposable scratch database on the same server, compare per-table row
  counts and the Alembic revision against the live database, then drop the
  scratch database. This is a genuine restore, not a documented theory.

All functions take explicit parameters and raise ``BackupError`` with
actionable messages; nothing here prompts interactively.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BACKUP_DIR = REPO_ROOT / "data" / "backups"
DEFAULT_KEEP = 7
SCRATCH_PREFIX = "vocab_restore_test_"
DUMP_SUFFIX = ".dump"


class BackupError(RuntimeError):
    """Raised when a backup/restore step cannot be performed."""


@dataclass(frozen=True)
class ConnectionParams:
    """Plain connection fields for the PostgreSQL command-line tools."""

    host: str
    port: int
    user: str
    password: str
    database: str

    def without_database(self) -> ConnectionParams:
        return ConnectionParams(self.host, self.port, self.user, self.password, "postgres")


# --------------------------------------------------------------------------- #
# discovery / configuration
# --------------------------------------------------------------------------- #
def find_pg_binary(name: str) -> Path:
    """Locate a PostgreSQL client binary (pg_dump / pg_restore / psql).

    Order: ``PG_BIN`` env var, then ``PATH``, then the standard Windows
    install locations. Raises with instructions when nothing is found.
    """
    candidates: list[Path] = []
    env_bin = os.environ.get("PG_BIN")
    if env_bin:
        candidates.append(Path(env_bin) / name)
        candidates.append(Path(env_bin) / f"{name}.exe")
    on_path = shutil.which(name)
    if on_path:
        candidates.append(Path(on_path))
    for base in (Path("C:/Program Files/PostgreSQL"), Path("/usr/lib/postgresql")):
        if base.is_dir():
            for version_dir in sorted(base.iterdir(), reverse=True):
                candidates.append(version_dir / "bin" / name)
                candidates.append(version_dir / "bin" / f"{name}.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise BackupError(
        f"{name} not found. Install PostgreSQL client tools, or set PG_BIN "
        f"to the directory containing {name} (e.g. "
        f"'C:/Program Files/PostgreSQL/17/bin')."
    )


def connection_params(database_url: str | None = None) -> ConnectionParams:
    """Resolve connection fields from an explicit URL or app settings."""
    if database_url is None:
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.settings import get_settings

        database_url = get_settings().database_url
    url = make_url(database_url)
    if url.database is None:
        raise BackupError("The database URL has no database name.")
    return ConnectionParams(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=url.username or "postgres",
        password=url.password or "",
        database=url.database,
    )


def _admin_engine(params: ConnectionParams):  # type: ignore[no-untyped-def]
    """Engine connected to the ``postgres`` maintenance DB (autocommit)."""
    url = URL.create(
        "postgresql+psycopg",
        username=params.user,
        password=params.password,
        host=params.host,
        port=params.port,
        database="postgres",
    )
    return create_engine(url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)


def create_database(params: ConnectionParams, name: str) -> None:
    """Create an empty database on the server (admin connection)."""
    with _admin_engine(params).connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))


def drop_database(params: ConnectionParams, name: str) -> None:
    """Drop a database, forcing connections closed."""
    with _admin_engine(params).connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def scratch_url(params: ConnectionParams, name: str) -> URL:
    """SQLAlchemy URL for a named database on the same server."""
    return URL.create(
        "postgresql+psycopg",
        username=params.user,
        password=params.password,
        host=params.host,
        port=params.port,
        database=name,
    )


# --------------------------------------------------------------------------- #
# backup / retention
# --------------------------------------------------------------------------- #
def _run(cmd: list[str], *, env: dict[str, str]) -> None:
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BackupError(
            f"command failed ({proc.returncode}): {' '.join(cmd[:2])}\n{proc.stderr.strip()}"
        )


def backup_database(
    *,
    out_dir: Path = DEFAULT_BACKUP_DIR,
    database_url: str | None = None,
    keep: int = DEFAULT_KEEP,
) -> Path:
    """Dump the live database to a timestamped custom-format file.

    Applies retention afterwards (newest ``keep`` retained). Returns the
    new dump path.
    """
    params = connection_params(database_url)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = out_dir / f"{params.database}_{stamp}{DUMP_SUFFIX}"
    pg_dump = find_pg_binary("pg_dump")
    env = dict(os.environ)
    if params.password:
        env["PGPASSWORD"] = params.password
    _run(
        [
            str(pg_dump),
            "--host", params.host,
            "--port", str(params.port),
            "--username", params.user,
            "--format=custom",
            "--file", str(target),
            params.database,
        ],
        env=env,
    )
    prune_backups(out_dir=out_dir, keep=keep)
    return target


def list_backups(*, out_dir: Path = DEFAULT_BACKUP_DIR) -> list[Path]:
    """Newest-first list of backup files."""
    if not out_dir.is_dir():
        return []
    return sorted(
        (p for p in out_dir.iterdir() if p.is_file() and p.suffix == DUMP_SUFFIX),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def prune_backups(*, out_dir: Path = DEFAULT_BACKUP_DIR, keep: int = DEFAULT_KEEP) -> list[Path]:
    """Delete every backup beyond the newest ``keep``; return the deleted paths."""
    if keep < 1:
        raise BackupError("Retention must keep at least one backup.")
    deleted: list[Path] = []
    for stale in list_backups(out_dir=out_dir)[keep:]:
        stale.unlink()
        deleted.append(stale)
    return deleted


# --------------------------------------------------------------------------- #
# restore / verification
# --------------------------------------------------------------------------- #
def restore_database(
    dump: Path,
    *,
    target_db: str,
    database_url: str | None = None,
    create: bool = True,
    clean: bool = False,
) -> None:
    """Restore ``dump`` into ``target_db`` (optionally creating the database)."""
    params = connection_params(database_url)
    if create:
        create_database(params, target_db)
    pg_restore = find_pg_binary("pg_restore")
    env = dict(os.environ)
    if params.password:
        env["PGPASSWORD"] = params.password
    cmd = [
        str(pg_restore),
        "--host", params.host,
        "--port", str(params.port),
        "--username", params.user,
        "--dbname", target_db,
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
    ]
    if clean:
        cmd += ["--clean", "--if-exists"]
    cmd.append(str(dump))
    _run(cmd, env=env)


def _table_names(params: ConnectionParams, database: str) -> list[str]:
    url = URL.create(
        "postgresql+psycopg",
        username=params.user,
        password=params.password,
        host=params.host,
        port=params.port,
        database=database,
    )
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name"
                )
            ).scalars().all()
            return [str(r) for r in rows]
    finally:
        engine.dispose()


def _row_counts(params: ConnectionParams, database: str) -> dict[str, int]:
    url = URL.create(
        "postgresql+psycopg",
        username=params.user,
        password=params.password,
        host=params.host,
        port=params.port,
        database=database,
    )
    engine = create_engine(url, pool_pre_ping=True)
    counts: dict[str, int] = {}
    try:
        with engine.connect() as conn:
            for table in _table_names(params, database):
                counts[table] = int(
                    conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() or 0
                )
    finally:
        engine.dispose()
    return counts


def verify_restore(
    dump: Path,
    *,
    database_url: str | None = None,
    keep_scratch: bool = False,
) -> dict[str, object]:
    """Real restoration test: restore ``dump`` to a scratch DB and compare.

    Compares every public table's row count and the ``alembic_version``
    revision between the live database and the restored copy, then drops
    the scratch database (unless ``keep_scratch``).
    """
    params = connection_params(database_url)
    scratch = f"{SCRATCH_PREFIX}{datetime.now().strftime('%Y%m%d%H%M%S')}"
    source_counts = _row_counts(params, params.database)
    source_version = _alembic_version(params, params.database)
    try:
        restore_database(dump, target_db=scratch, database_url=database_url, create=True)
        restored_counts = _row_counts(params, scratch)
        restored_version = _alembic_version(params, scratch)
    finally:
        if not keep_scratch:
            drop_database(params, scratch)

    mismatches = {
        table: {"source": source_counts.get(table), "restored": restored_counts.get(table)}
        for table in sorted(set(source_counts) | set(restored_counts))
        if source_counts.get(table) != restored_counts.get(table)
    }
    return {
        "dump": str(dump),
        "dump_bytes": dump.stat().st_size if dump.is_file() else 0,
        "scratch_database": scratch,
        "kept_scratch": keep_scratch,
        "tables_checked": len(source_counts),
        "source_rows": sum(source_counts.values()),
        "restored_rows": sum(restored_counts.values()),
        "alembic_version_source": source_version,
        "alembic_version_restored": restored_version,
        "mismatches": mismatches,
        "ok": not mismatches and source_version == restored_version,
    }


def _alembic_version(params: ConnectionParams, database: str) -> str | None:
    url = URL.create(
        "postgresql+psycopg",
        username=params.user,
        password=params.password,
        host=params.host,
        port=params.port,
        database=database,
    )
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            value = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            return None if value is None else str(value)
    except Exception:  # noqa: BLE001 - a missing table means "no revision"
        return None
    finally:
        engine.dispose()
