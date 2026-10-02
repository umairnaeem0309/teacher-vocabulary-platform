"""Phase 26 tests: local backup/restore tooling (sections 51/64/102).

Fast unit coverage for the pure helpers (binary discovery, retention,
URL parsing) plus a REAL end-to-end test: build a tiny throwaway database,
``pg_dump`` it, restore it into a scratch database and verify per-table row
counts and the Alembic revision. The latter skips cleanly when the
PostgreSQL client tools are absent. The full-size restoration test is run
via ``scripts/db_backup.py verify --fresh`` and recorded in docs/backups.md.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from pipeline.storage import backup as bk
from sqlalchemy import create_engine, text

from tests.conftest import requires_db


def _pg_tools_available() -> bool:
    try:
        bk.find_pg_binary("pg_dump")
        bk.find_pg_binary("pg_restore")
        return True
    except bk.BackupError:
        return False


PG_TOOLS = _pg_tools_available()
requires_pg_tools = pytest.mark.skipif(
    not PG_TOOLS, reason="pg_dump/pg_restore not found (set PG_BIN)"
)


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def test_find_pg_binary_honors_pg_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "pg_dump"
    fake.write_text("")
    monkeypatch.setenv("PG_BIN", str(tmp_path))
    assert bk.find_pg_binary("pg_dump") == fake


def test_find_pg_binary_raises_for_missing_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PG_BIN", raising=False)
    with pytest.raises(bk.BackupError):
        bk.find_pg_binary("pg_dump_definitely_missing_xyz")


def test_prune_backups_keeps_newest_and_ignores_other_files(tmp_path: Path) -> None:
    note = tmp_path / "notes.txt"
    note.write_text("keep me")
    made = []
    for i in range(5):
        path = tmp_path / f"db_2026010{i}_000000.dump"
        path.write_text("x")
        os.utime(path, (1000 + i, 1000 + i))
        made.append(path)

    deleted = bk.prune_backups(out_dir=tmp_path, keep=2)

    remaining = {p.name for p in bk.list_backups(out_dir=tmp_path)}
    assert remaining == {"db_20260103_000000.dump", "db_20260104_000000.dump"}
    assert {p.name for p in deleted} == {
        "db_20260100_000000.dump",
        "db_20260101_000000.dump",
        "db_20260102_000000.dump",
    }
    assert note.exists(), "retention must never delete non-backup files"


def test_list_backups_is_newest_first(tmp_path: Path) -> None:
    for i in range(3):
        path = tmp_path / f"db_{i}.dump"
        path.write_text("x")
        os.utime(path, (2000 + i, 2000 + i))
    names = [p.name for p in bk.list_backups(out_dir=tmp_path)]
    assert names == ["db_2.dump", "db_1.dump", "db_0.dump"]


def test_prune_rejects_zero_keep(tmp_path: Path) -> None:
    with pytest.raises(bk.BackupError):
        bk.prune_backups(out_dir=tmp_path, keep=0)


def test_connection_params_parse_database_url() -> None:
    params = bk.connection_params("postgresql+psycopg://user:secret@dbhost:5555/mydb")
    assert (params.host, params.port, params.user, params.password, params.database) == (
        "dbhost",
        5555,
        "user",
        "secret",
        "mydb",
    )


# --------------------------------------------------------------------------- #
# real round-trip (tiny database)
# --------------------------------------------------------------------------- #
@requires_db
@requires_pg_tools
def test_real_backup_restore_roundtrip(tmp_path: Path) -> None:
    """pg_dump -> pg_restore -> compare, against a throwaway database."""
    params = bk.connection_params()
    source_db = f"vocab_bk_test_{uuid.uuid4().hex[:10]}"
    bk.create_database(params, source_db)
    try:
        engine = create_engine(bk.scratch_url(params, source_db), pool_pre_ping=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE widget (id int PRIMARY KEY, name text)"))
            conn.execute(text("INSERT INTO widget VALUES (1, 'a'), (2, 'b'), (3, 'c')"))
            conn.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
            conn.execute(text("INSERT INTO alembic_version VALUES ('deadbeef')"))
        engine.dispose()

        source_url = bk.scratch_url(params, source_db).render_as_string(hide_password=False)
        dump = bk.backup_database(database_url=source_url, out_dir=tmp_path, keep=5)
        assert dump.is_file() and dump.stat().st_size > 0

        report = bk.verify_restore(dump, database_url=source_url)

        assert report["ok"], report
        assert report["mismatches"] == {}
        assert report["tables_checked"] == 2
        assert report["source_rows"] == report["restored_rows"] == 4
        assert report["alembic_version_source"] == "deadbeef"
        assert report["alembic_version_restored"] == "deadbeef"
    finally:
        bk.drop_database(params, source_db)
