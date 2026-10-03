"""Register an automatic daily database backup (Phase 30, §51).

§51 requires the vocabulary database to be backed up **automatically**,
not only on demand. This script installs (or removes) a daily scheduled
job that runs ``scripts/db_backup.py backup`` with the project's retention
setting:

- **Windows** — a Task Scheduler task named ``VocabPlatformBackup``
  created with ``schtasks``.
- **Linux/macOS** — a line in the current user's crontab.

The job is deliberately thin: all backup logic stays in
``pipeline/storage/backup.py`` (retention, naming, ``PGPASSWORD``), so the
schedule and the manual procedure can never drift apart.

Usage (from the repository root):

    python scripts/install_backup_schedule.py install           # daily 02:00
    python scripts/install_backup_schedule.py install --time 23:30
    python scripts/install_backup_schedule.py install --keep 14
    python scripts/install_backup_schedule.py status
    python scripts/install_backup_schedule.py remove
    python scripts/install_backup_schedule.py print             # show the job

Nothing here talks to the database; ``install``/``remove`` only edit the
operating system's schedule.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASK_NAME = "VocabPlatformBackup"
DEFAULT_TIME = "02:00"
DEFAULT_KEEP = 7
LOG_RELATIVE = Path("data") / "backups" / "backup.log"


class ScheduleError(RuntimeError):
    """Raised when the scheduled job cannot be registered or removed."""


def resolve_python(repo_root: Path = REPO_ROOT) -> Path:
    """Return the backend virtualenv interpreter, falling back to ``sys.executable``.

    A scheduled task must not depend on an activated shell; it needs an
    absolute interpreter path. The project keeps its dependencies in
    ``backend/.venv``, so that interpreter is preferred.
    """
    for candidate in (
        repo_root / "backend" / ".venv" / "Scripts" / "python.exe",  # Windows
        repo_root / "backend" / ".venv" / "bin" / "python",  # POSIX
    ):
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def _quote(value: str) -> str:
    return f'"{value}"'


def build_run_command(
    python: Path,
    repo_root: Path = REPO_ROOT,
    keep: int = DEFAULT_KEEP,
    log: Path | None = None,
) -> str:
    """The shell command that performs one backup (portable, no activation).

    Log output is appended to ``data/backups/backup.log`` so an unattended
    failure is diagnosable after the fact.
    """
    script = repo_root / "scripts" / "db_backup.py"
    log_path = log if log is not None else repo_root / LOG_RELATIVE
    return (
        f"{_quote(str(python))} {_quote(str(script))} "
        f"backup --keep {int(keep)} >> {_quote(str(log_path))} 2>&1"
    )


def build_windows_task_command(
    run_command: str, repo_root: Path = REPO_ROOT
) -> str:
    """Wrap the backup command so Task Scheduler runs it with the right cwd.

    Task Scheduler has no working-directory field for ``/TR``; ``cmd /c cd``
    sets it, and ``PYTHONPATH`` lets ``app.core.settings`` import cleanly
    (matching the documented manual invocation).
    """
    backend = repo_root / "backend"
    return (
        f'cmd /c cd /d {_quote(str(repo_root))} && '
        f"set PYTHONPATH={repo_root}{os.pathsep}{backend} && "
        f"{run_command}"
    )


def build_cron_line(
    run_command: str,
    minute: int,
    hour: int,
    repo_root: Path = REPO_ROOT,
) -> str:
    """A crontab line running the backup daily at ``hour:minute``."""
    backend = repo_root / "backend"
    return (
        f"{minute} {hour} * * * cd {_quote(str(repo_root))} && "
        f"PYTHONPATH={_quote(str(repo_root) + os.pathsep + str(backend))} "
        f"{run_command}"
    )


def parse_time(value: str) -> tuple[int, int]:
    """Parse ``HH:MM`` (24-hour) into ``(hour, minute)``."""
    try:
        hour_str, minute_str = value.split(":", 1)
        hour, minute = int(hour_str), int(minute_str)
    except ValueError as exc:
        raise ScheduleError(f"invalid --time {value!r}; expected HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"invalid --time {value!r}; expected HH:MM")
    return hour, minute


def register_windows(task_name: str, time_text: str, command: str) -> None:
    """Create or replace a daily Task Scheduler task."""
    schtasks = shutil.which("schtasks")
    if schtasks is None:
        raise ScheduleError("schtasks not found; this host is not Windows")
    result = subprocess.run(  # noqa: S603 - fixed, non-interactive command
        [
            schtasks, "/Create", "/SC", "DAILY", "/ST", time_text,
            "/TN", task_name, "/TR", command, "/F",
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise ScheduleError(
            f"schtasks failed ({result.returncode}): {result.stderr.strip()}"
        )


def remove_windows(task_name: str) -> None:
    schtasks = shutil.which("schtasks")
    if schtasks is None:
        raise ScheduleError("schtasks not found; this host is not Windows")
    result = subprocess.run(  # noqa: S603
        [schtasks, "/Delete", "/TN", task_name, "/F"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise ScheduleError(
            f"schtasks failed ({result.returncode}): {result.stderr.strip()}"
        )


def install_cron(line: str) -> None:
    """Append the cron line if an equivalent one is not already present."""
    existing = _read_crontab()
    marker = "db_backup.py"
    if marker in existing:
        raise ScheduleError(
            "a backup cron entry already exists; run 'remove' first to replace it"
        )
    new_crontab = existing.rstrip("\n") + ("\n" if existing.strip() else "") + line + "\n"
    _write_crontab(new_crontab)


def remove_cron() -> None:
    kept = [ln for ln in _read_crontab().splitlines() if "db_backup.py" not in ln]
    _write_crontab("\n".join(kept) + ("\n" if kept else ""))


def _read_crontab() -> str:
    result = subprocess.run(  # noqa: S603
        ["crontab", "-l"], capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else ""


def _write_crontab(content: str) -> None:
    if shutil.which("crontab") is None:
        raise ScheduleError("crontab not found; schedule the job another way")
    result = subprocess.run(  # noqa: S603
        ["crontab", "-"], input=content, text=True, check=False
    )
    if result.returncode != 0:
        raise ScheduleError(f"crontab failed ({result.returncode})")


def _is_windows() -> bool:
    return os.name == "nt"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install/remove the automatic daily database backup (§51)."
    )
    parser.add_argument(
        "action", choices=["install", "remove", "status", "print"]
    )
    parser.add_argument("--time", default=DEFAULT_TIME, help="HH:MM (24h), default 02:00")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="dumps to keep")
    parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    args = parser.parse_args(argv)

    python = resolve_python()
    run_command = build_run_command(python, REPO_ROOT, args.keep)

    try:
        if args.action == "print":
            if _is_windows():
                print(build_windows_task_command(run_command))
            else:
                hour, minute = parse_time(args.time)
                print(build_cron_line(run_command, minute, hour))
            return 0

        if args.action == "install":
            if _is_windows():
                command = build_windows_task_command(run_command)
                register_windows(args.task_name, args.time, command)
                print(f"installed Windows task '{args.task_name}' at {args.time} daily")
            else:
                hour, minute = parse_time(args.time)
                line = build_cron_line(run_command, minute, hour)
                install_cron(line)
                print(f"installed cron entry at {hour:02d}:{minute:02d} daily")
            return 0

        if args.action == "status":
            if _is_windows():
                result = subprocess.run(  # noqa: S603
                    ["schtasks", "/Query", "/TN", args.task_name],
                    capture_output=True, text=True, check=False,
                )
                print(result.stdout.strip() or "(task not installed)")
                return 0 if result.returncode == 0 else 1
            present = "db_backup.py" in _read_crontab()
            print("backup cron entry present" if present else "(no cron entry)")
            return 0 if present else 1

        # remove
        if _is_windows():
            remove_windows(args.task_name)
            print(f"removed Windows task '{args.task_name}'")
        else:
            remove_cron()
            print("removed backup cron entry")
        return 0
    except ScheduleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
