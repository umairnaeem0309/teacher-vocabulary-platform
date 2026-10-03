"""Phase 30 tests: automatic backup scheduling (§51).

Only the pure command/parsing helpers are exercised — installing a real
Task Scheduler job or cron entry would mutate the host and is not a unit
test. The generated commands are asserted to reference the real CLI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import install_backup_schedule as sched


def test_parse_time_accepts_hh_mm() -> None:
    assert sched.parse_time("02:00") == (2, 0)
    assert sched.parse_time("23:59") == (23, 59)


@pytest.mark.parametrize("bad", ["2", "24:00", "12:60", "noon", "aa:bb"])
def test_parse_time_rejects_invalid(bad: str) -> None:
    with pytest.raises(sched.ScheduleError):
        sched.parse_time(bad)


def test_build_run_command_targets_db_backup_cli() -> None:
    python = Path("/opt/venv/bin/python")
    command = sched.build_run_command(python, Path("/repo"), keep=14)
    assert "db_backup.py" in command
    assert "backup --keep 14" in command
    assert "backup.log" in command


def test_windows_command_sets_cwd_and_pythonpath() -> None:
    command = sched.build_windows_task_command(
        "python db_backup.py backup --keep 7", Path("/repo")
    )
    assert command.startswith("cmd /c cd /d")
    assert "set PYTHONPATH=" in command
    assert "backend" in command


def test_cron_line_schedule_and_environment() -> None:
    line = sched.build_cron_line(
        "python db_backup.py backup --keep 7", minute=30, hour=3, repo_root=Path("/repo")
    )
    assert line.startswith("30 3 * * *")
    assert "db_backup.py" in line
    assert "PYTHONPATH" in line


def test_resolve_python_prefers_existing_interpreter(tmp_path: Path) -> None:
    # No venv under tmp_path -> falls back to the running interpreter.
    resolved = sched.resolve_python(tmp_path)
    assert resolved.is_file()
    # A fake POSIX venv interpreter is preferred when present.
    venv_python = tmp_path / "backend" / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!fake\n", encoding="utf-8")
    assert sched.resolve_python(tmp_path) == venv_python


def test_defaults() -> None:
    assert sched.DEFAULT_TIME == "02:00"
    assert sched.DEFAULT_KEEP == 7
    assert sched.DEFAULT_TASK_NAME == "VocabPlatformBackup"
