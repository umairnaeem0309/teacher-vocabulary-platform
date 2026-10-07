"""Unattended babysitter for the Phase 12 embedding rebuild (emb-v1).

Why this exists: the full rebuild is a ~22-hour single-process CPU job
(this machine has 7.7 GB RAM — a second BGE-M3 instance would thrash the
page file, so parallel workers were evaluated and rejected). This watcher
keeps the run honest while unattended:

1. heartbeat every poll -> data/construction/embed_watch.log
   (timestamp, worker pids, sha-accurate pending count);
2. if the worker exits with pending senses left (crash/kill), restart it
   with the exact same resumable command (max 4 restarts; the counter
   resets whenever a run survives >= 45 min);
3. once every master sense is embedded, run ONE final
   ``--full --resume --reindex`` pass (skips all work, rebuilds HNSW
   fresh — D014: an index grown by incremental inserts has degraded
   recall), and only treat it as done when the appended log contains
   ``hnsw index rebuilt``;
4. verify counts (71,149 rows, one version, 0 pending), then take the
   handoff dump via scripts/db_backup.py backup.

Exit codes: 0 = dump written (DONE line in the log), 1 = gave up
(restart budget exhausted / watchdog), so callers can distinguish.

Run (from repo root, background):
    backend/.venv/Scripts/python.exe -u scripts/watch_embedding_run.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv

load_dotenv(REPO / ".env")

from pipeline.enrich.embeddings import (
    EMBEDDINGS_VERSION,
    embed_text,
    text_sha256,
)
from pipeline.storage.sqlite_store import ConstructionStore

DB_PATH = REPO / "data" / "construction" / "construction.sqlite"
WORKER_LOG = REPO / "data" / "construction" / "phase12_rebuild.log"
WATCH_LOG = REPO / "data" / "construction" / "embed_watch.log"
DONE_MARKER = REPO / "data" / "construction" / "embed_watch.done"
PID_PS1 = REPO / "data" / "construction" / "phase12_pids.ps1"
PY = REPO / "backend" / ".venv" / "Scripts" / "python.exe"
WORKER_ARGS = [
    str(PY),
    "-u",
    "scripts/phase12_embeddings_smoke.py",
    "--full",
    "--reindex",
    "--batch-size",
    "32",
    "--resume",
]
POLL_SECONDS = 300
SURVIVAL_RESET_SECONDS = 45 * 60
MAX_RESTARTS = 4
MAX_RUNTIME_HOURS = 40
TOTAL_SENSES = 71_149

PID_PS1_TEXT = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" |\n"
    "  Where-Object { $_.CommandLine -like '*phase12_embeddings_smoke*' } |\n"
    "  ForEach-Object { $_.ProcessId }\n"
)


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).astimezone():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with WATCH_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


_LOCK_FH = None  # held for the watcher's lifetime; OS releases it on any exit


def acquire_single_instance() -> bool:
    """Exclusive lock so two watchers can never run (double worker launch).

    Hold an opened file locked for the process lifetime — if a second
    watcher starts, its LK_NBLCK attempt fails and it exits immediately.
    """
    global _LOCK_FH
    import msvcrt

    _LOCK_FH = WATCH_LOG.parent.joinpath("embed_watch.lock").open("a+", encoding="utf-8")
    try:
        msvcrt.locking(_LOCK_FH.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        _LOCK_FH.close()
        _LOCK_FH = None
        return False
    _LOCK_FH.seek(0)
    _LOCK_FH.truncate()
    _LOCK_FH.write(f"holder pid={os.getpid()}\n")
    _LOCK_FH.flush()
    return True


def worker_pids() -> list[int]:
    # write the helper every call: a missing file would make PowerShell fail
    # and an empty result could be misread as "worker dead" -> double launch
    PID_PS1.write_text(PID_PS1_TEXT, encoding="utf-8")
    out = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PID_PS1)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(
            f"pid scan failed rc={out.returncode}: {(out.stderr or '')[-300:]}"
        )
    return [int(x) for x in out.stdout.split() if x.strip().isdigit()]


def launch_worker() -> None:
    fh = WORKER_LOG.open("a", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if env.get("DATABASE_URL") is None:
        raise RuntimeError("DATABASE_URL not set in environment (.env loaded?)")
    subprocess.Popen(
        WORKER_ARGS,
        cwd=str(REPO),
        stdout=fh,
        stderr=subprocess.STDOUT,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    fh.close()


def expected_shas() -> dict[str, str]:
    """sense_key -> text_sha256 of the CURRENT recipe (phase12's skip rule)."""
    store = ConstructionStore(DB_PATH)
    rows = store.conn.execute(
        "SELECT sense_key, headword_search, pos_canonical, gloss_search "
        "FROM master_senses ORDER BY sense_key"
    ).fetchall()
    out: dict[str, str] = {}
    for key, hw, pos, gloss in rows:
        examples = [
            r[0]
            for r in store.conn.execute(
                "SELECT text FROM sense_examples WHERE sense_key = ? "
                "ORDER BY position LIMIT 2",
                (key,),
            )
        ]
        out[str(key)] = text_sha256(
            embed_text(str(hw or ""), str(pos or ""), str(gloss or ""), examples)
        )
    store.close()
    return out


def pending_count(expected: dict[str, str]) -> int:
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        stored = {
            str(k): str(s)
            for k, s in conn.execute(
                text(
                    "SELECT vs.sense_key, se.text_sha256 FROM sense_embeddings se "
                    "JOIN vocabulary_senses vs ON vs.id = se.sense_id "
                    "WHERE se.embedding_version = :v"
                ),
                {"v": EMBEDDINGS_VERSION},
            )
        }
    engine.dispose()
    return sum(1 for k, sha in expected.items() if stored.get(k) != sha)


def counts() -> tuple[int, int, bool]:
    """(rows, distinct versions, hnsw index present)."""
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        rows, versions = conn.execute(
            text(
                "SELECT COUNT(*), COUNT(DISTINCT embedding_version) FROM sense_embeddings"
            )
        ).fetchone()
        hnsw = bool(
            conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE indexname = 'ix_sense_embeddings_hnsw'"
                )
            ).scalar()
        )
    engine.dispose()
    return int(rows), int(versions), hnsw


def run_backup() -> str:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [str(PY), "scripts/db_backup.py", "backup"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=900,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"db_backup failed ({proc.returncode}): {out[-800:]}")
    return out.strip()


def main() -> int:
    WATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    if DONE_MARKER.exists():
        # scheduled-task trigger after a completed run: nothing to do
        print("done marker present — pipeline already complete", flush=True)
        return 0
    if not acquire_single_instance():
        log("another watcher already holds the lock — exiting")
        return 0
    started = time.time()
    restarts = 0
    run_seen_at: float | None = None
    stage2_started_at: float | None = None
    stage2_log_offset = 0
    stage2_attempts = 0

    log("watcher start: loading expected shas ...")
    expected = expected_shas()
    log(f"expected senses: {len(expected)}")

    while True:
        if time.time() - started > MAX_RUNTIME_HOURS * 3600:
            log("WATCHDOG: max runtime exceeded — giving up")
            return 1

        try:
            pids = worker_pids()
        except Exception as exc:  # noqa: BLE001 - transient scan failure: retry
            log(f"pid scan failed (will retry): {exc}")
            time.sleep(POLL_SECONDS)
            continue
        if pids:
            if run_seen_at is None:
                run_seen_at = time.time()
            elif restarts and time.time() - run_seen_at > SURVIVAL_RESET_SECONDS:
                # a long-lived healthy run frees the restart budget again
                restarts = 0
                log("run survived >=45min; restart budget reset")
            if stage2_started_at is None:
                pending = pending_count(expected)
                log(f"heartbeat: worker pids={pids} pending={pending} "
                    f"restarts_used={restarts}")
            else:
                log(f"heartbeat: final reindex pass running pids={pids}")
            time.sleep(POLL_SECONDS)
            continue

        # ---- worker is gone -------------------------------------------
        run_seen_at = None
        pending = pending_count(expected)

        if stage2_started_at is None:
            if pending > 0:
                if restarts >= MAX_RESTARTS:
                    log(f"FAILURE: worker gone with pending={pending} and restart "
                        f"budget exhausted ({restarts}/{MAX_RESTARTS}) — manual "
                        "intervention: relaunch phase12 with --resume")
                    return 1
                restarts += 1
                log(f"worker exited with pending={pending}; restart "
                    f"{restarts}/{MAX_RESTARTS} (--resume)")
                launch_worker()
                time.sleep(60)
                continue

            # all senses embedded -> stage 2: one final --reindex pass
            stage2_started_at = time.time()
            stage2_attempts += 1
            stage2_log_offset = WORKER_LOG.stat().st_size if WORKER_LOG.exists() else 0
            log(f"all {len(expected)} senses embedded — launching final "
                f"resume+reindex pass (attempt {stage2_attempts})")
            launch_worker()
            time.sleep(60)
            continue

        # ---- stage 2: final pass finished? ----------------------------
        appended = ""
        if WORKER_LOG.exists() and WORKER_LOG.stat().st_size > stage2_log_offset:
            with WORKER_LOG.open("rb") as fh:
                fh.seek(stage2_log_offset)
                appended = fh.read().decode("utf-8", errors="replace")

        if "hnsw index rebuilt" not in appended:
            if stage2_attempts >= 3:
                log("FAILURE: final reindex pass did not report "
                    f"'hnsw index rebuilt' after {stage2_attempts} attempts; "
                    f"appended tail: {appended[-500:]!r}")
                return 1
            stage2_attempts += 1
            stage2_log_offset = WORKER_LOG.stat().st_size
            log(f"final pass ended without reindex marker; retry "
                f"{stage2_attempts} (tail: {appended[-200:]!r})")
            launch_worker()
            time.sleep(60)
            continue

        # ---- stage 3: verify + dump ------------------------------------
        pending = pending_count(expected)
        rows, versions, hnsw = counts()
        log(f"verify: pending={pending} rows={rows} versions={versions} hnsw={hnsw}")
        if pending or rows != TOTAL_SENSES or versions != 1 or not hnsw:
            log("FAILURE: post-embed verification failed — not taking the dump")
            return 1

        try:
            out = run_backup()
        except Exception as exc:  # noqa: BLE001 - report and fail loudly
            log(f"FAILURE: backup error: {exc}")
            return 1
        log(f"BACKUP OK: {out}")
        log(f"DONE: embeddings complete ({rows} rows, emb-v1, HNSW rebuilt), "
            "handoff dump written — update current-state.md/plan.md Phase 31")
        DONE_MARKER.write_text(
            f"{datetime.now(timezone.utc).astimezone():%Y-%m-%d %H:%M:%S}\n"
            f"rows={rows}\ndump={out.splitlines()[-1] if out else ''}\n",
            encoding="utf-8",
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
