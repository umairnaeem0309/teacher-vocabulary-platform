"""Local PostgreSQL backup CLI (Phase 26, §64/§102; local-only per D026).

Thin command-line wrapper around ``pipeline.storage.backup``:

    cd backend
    PYTHONPATH=.. uv run python ../scripts/db_backup.py backup [--keep 7]
    PYTHONPATH=.. uv run python ../scripts/db_backup.py list
    PYTHONPATH=.. uv run python ../scripts/db_backup.py restore <dump> --target-db <name>
    PYTHONPATH=.. uv run python ../scripts/db_backup.py verify [<dump>] [--fresh]

``verify`` performs the real restoration test: it restores the dump into a
disposable scratch database, compares every table's row count and the
Alembic revision against the live database, drops the scratch database, and
writes ``data/construction/phase26_restore_report.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.storage import backup as bk  # noqa: E402


def _cmd_backup(args: argparse.Namespace) -> int:
    path = bk.backup_database(keep=args.keep)
    print(f"backup written: {path} ({path.stat().st_size:,} bytes)")
    for stale in bk.prune_backups(keep=args.keep):
        print(f"pruned: {stale.name}")
    return 0


def _cmd_list(_: argparse.Namespace) -> int:
    backups = bk.list_backups()
    if not backups:
        print("no backups yet")
        return 0
    for path in backups:
        print(f"{path.stat().st_mtime:.0f}  {path.stat().st_size:>12,} B  {path.name}")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    dump = Path(args.dump)
    if not dump.is_file():
        raise bk.BackupError(f"no such dump: {dump}")
    bk.restore_database(
        dump,
        target_db=args.target_db,
        create=not args.no_create,
        clean=args.clean,
    )
    print(f"restored {dump.name} into database '{args.target_db}'")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    if args.fresh:
        dump = bk.backup_database(keep=args.keep)
        print(f"fresh backup: {dump}")
    elif args.dump:
        dump = Path(args.dump)
    else:
        existing = bk.list_backups()
        if not existing:
            raise bk.BackupError("no backup to verify; run 'backup' first or pass --fresh")
        dump = existing[0]
    if not dump.is_file():
        raise bk.BackupError(f"no such dump: {dump}")

    report = bk.verify_restore(dump)
    report_path = bk.REPO_ROOT / "data" / "construction" / "phase26_restore_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"\nwrote {report_path}")
    print("RESTORE VERIFIED OK" if report["ok"] else "RESTORE MISMATCH — see report")
    return 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local PostgreSQL backup tools (Phase 26).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="dump the live database")
    p_backup.add_argument("--keep", type=int, default=bk.DEFAULT_KEEP)
    p_backup.set_defaults(func=_cmd_backup)

    p_list = sub.add_parser("list", help="list backups, newest first")
    p_list.set_defaults(func=_cmd_list)

    p_restore = sub.add_parser("restore", help="restore a dump into a database")
    p_restore.add_argument("dump")
    p_restore.add_argument("--target-db", required=True)
    p_restore.add_argument("--no-create", action="store_true")
    p_restore.add_argument("--clean", action="store_true")
    p_restore.set_defaults(func=_cmd_restore)

    p_verify = sub.add_parser("verify", help="real restoration test into a scratch DB")
    p_verify.add_argument("dump", nargs="?")
    p_verify.add_argument("--fresh", action="store_true", help="take a new backup first")
    p_verify.add_argument("--keep", type=int, default=bk.DEFAULT_KEEP)
    p_verify.set_defaults(func=_cmd_verify)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except bk.BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
