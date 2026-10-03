"""Phase 28 — local readiness verification (§104; local-only scope per D026).

Runs every §104 item against this machine and writes a machine-readable
result to ``data/construction/phase28_readiness_report.json``:

===========================  =================================================
check id                     §104 item
===========================  =================================================
env.example                 environment variables (.env.example coverage)
env.production_guard        production config fails fast on placeholder secrets
install.uv_fresh            clean install: fresh venv from uv.lock
install.uv_locked           lockfile has no drift (uv sync --frozen)
install.pnpm_frozen         frontend lockfile has no drift
install.pnpm_scratch        clean install: pnpm install in an empty dir
db.clean_migrate            clean database: createdb -> extension -> alembic
db.schema_objects           tables, vector extension/index, FTS, revision
app.first_run_smoke         bootstrap window, login, empty browse on clean DB
app.json_logs               structured JSON access logs with request_id
db.migration_reversible     alembic downgrade base -> upgrade head
build.backend               backend imports cleanly
build.frontend_clean        production build from an empty .next
prod.stack                  uvicorn (APP_ENV=production) + next start smoke
tests.backend               full pytest suite (dev database)
tests.frontend              tsc + eslint + vitest
tests.e2e                   Playwright acceptance suite (§59/§60/§61)
backup.restore_roundtrip    fresh pg_dump + real restore verification
docs.setup_documented       README documents the clean setup commands
===========================  =================================================

Usage (from ``backend/``):

    PYTHONPATH=.. uv run python ../scripts/phase28_readiness.py
    PYTHONPATH=.. uv run python ../scripts/phase28_readiness.py --fast
    PYTHONPATH=.. uv run python ../scripts/phase28_readiness.py --skip tests.e2e

``--fast`` skips the slow checks (scratch installs, clean build, production
stack, test suites, backup roundtrip). A clean scratch database
(``vocab_platform_readiness``) is created for the database/app/production
checks and dropped afterwards — the development database is never touched.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import URL

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
REPORT_PATH = REPO / "data" / "construction" / "phase28_readiness_report.json"

SCRATCH_DB = "vocab_platform_readiness"
READY_PORT = 8740
PROD_BACKEND_PORT = 8000
PROD_FRONTEND_PORT = 3000

BOOTSTRAP_EMAIL = "readiness@example.com"
BOOTSTRAP_PASSWORD = "Readiness-Local-Passw0rd!"

FAST_SKIP = {
    "install.uv_fresh",
    "install.pnpm_scratch",
    "build.frontend_clean",
    "prod.stack",
    "tests.backend",
    "tests.frontend",
    "tests.e2e",
    "backup.restore_roundtrip",
}

sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO))

from pipeline.storage import backup as bk  # noqa: E402


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
class CheckError(Exception):
    """A check failed; the message becomes the recorded detail."""


#: ANSI SGR escape sequences (tool output is colored even when piped).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _base_env(**extra: str) -> dict[str, str]:
    """Clean subprocess environment (no inherited app configuration)."""
    env = dict(os.environ)
    for key in (
        "DATABASE_URL",
        "APP_ENV",
        "SESSION_SECRET",
        "LOG_FORMAT",
        "LOG_LEVEL",
        "ALEMBIC_DATABASE_URL",
        "NEXT_PUBLIC_API_URL",
        "UV_PROJECT_ENVIRONMENT",
    ):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _pnpm_argv(cmd: list[str]) -> list[str]:
    """Windows resolves the pnpm.cmd shim only through cmd.exe.

    ``subprocess`` without a shell cannot execute ``.cmd`` files by bare
    name, so pnpm invocations are wrapped for CreateProcess.
    """
    if os.name == "nt" and Path(cmd[0]).name.lower().split(".")[0] == "pnpm":
        return ["cmd", "/c", *cmd]
    return cmd


def run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 900,
) -> str:
    """Run a command, raise CheckError with output tails on failure."""
    proc = subprocess.run(
        _pnpm_argv(cmd),
        cwd=str(cwd),
        env=env or _base_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        tail = "\n".join(
            _ANSI_RE.sub("", proc.stdout or "").splitlines()[-25:]
            + ["--- stderr ---"]
            + _ANSI_RE.sub("", proc.stderr or "").splitlines()[-25:]
        )
        raise CheckError(f"`{' '.join(cmd)}` exited {proc.returncode}:\n{tail}")
    # Tool output often carries ANSI colors even when piped (vitest does);
    # strip them so summary parsing and report details stay plain text.
    return _ANSI_RE.sub("", (proc.stdout or "")) + _ANSI_RE.sub("", (proc.stderr or ""))


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_healthy(url: str, timeout_s: float = 90) -> None:
    import httpx

    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=3)
            if resp.status_code == 200:
                return
        except Exception as exc:  # noqa: BLE001 — connection refused while booting
            last = exc
        time.sleep(0.5)
    raise CheckError(f"server at {url} not healthy after {timeout_s}s (last: {last})")


def alembic_head() -> str:
    out = run(["uv", "run", "alembic", "heads"], cwd=BACKEND, timeout=120)
    match = re.search(r"^([0-9a-f]+) \(head\)", out, re.MULTILINE)
    if not match:
        raise CheckError(f"could not parse alembic head from:\n{out}")
    return match.group(1)


# --------------------------------------------------------------------------- #
# checks — each returns [(id, title, ok, detail), ...]
# --------------------------------------------------------------------------- #
def check_env_example() -> list[tuple[str, str, bool, str]]:
    from app.core.settings import Settings

    example = REPO / ".env.example"
    if not example.is_file():
        raise CheckError(".env.example is missing")
    keys = {
        line.split("=", 1)[0].strip()
        for line in example.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    fields = {name.upper() for name in Settings.model_fields}
    known_frontend = {"NEXT_PUBLIC_API_URL"}

    critical = {
        "APP_ENV",
        "DATABASE_URL",
        "SESSION_SECRET",
        "LOG_FORMAT",
        "LOG_LEVEL",
        "CORS_ORIGINS",
        "ALLOWED_REQUEST_ORIGINS",
        "RATE_LIMIT_ENABLED",
        "UPLOAD_MAX_BYTES",
        "EMBEDDING_MODEL",
        "VECTOR_DIMENSION",
    }
    missing_critical = sorted(critical - keys)
    stale = sorted(keys - fields - known_frontend)
    if missing_critical or stale:
        raise CheckError(
            f"missing critical entries: {missing_critical or 'none'}; "
            f"entries with no matching setting: {stale or 'none'}"
        )
    return [
        (
            "env.example",
            "environment variables (.env.example coverage)",
            True,
            f"{len(keys)} entries; all critical settings documented, no stale keys",
        )
    ]


def check_env_production_guard() -> list[tuple[str, str, bool, str]]:
    script = "from app.core.settings import Settings; Settings(); print('settings ok')"

    def attempt(env: dict[str, str]) -> tuple[int, str]:
        proc = subprocess.run(
            ["uv", "run", "python", "-c", script],
            cwd=str(BACKEND),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    # 1. production + placeholder secret must fail fast (§66/§39).
    rc, out = attempt(_base_env(APP_ENV="production"))
    if rc == 0 or "SESSION_SECRET" not in out:
        raise CheckError(f"placeholder secret was not rejected (rc={rc}):\n{out[-800:]}")

    # 2. production + real secret must boot.
    rc, out = attempt(
        _base_env(
            APP_ENV="production",
            SESSION_SECRET=uuid.uuid4().hex + uuid.uuid4().hex,
        )
    )
    if rc != 0 or "settings ok" not in out:
        raise CheckError(f"production boot with a real secret failed (rc={rc}):\n{out[-800:]}")

    # 3. an unknown APP_ENV must be rejected too.
    rc, out = attempt(_base_env(APP_ENV="not-an-env"))
    if rc == 0 or "APP_ENV" not in out:
        raise CheckError(f"APP_ENV=not-an-env was accepted (rc={rc}):\n{out[-800:]}")

    return [
        (
            "env.production_guard",
            "production config fails fast on placeholder secrets",
            True,
            "placeholder secret rejected in production, real secret accepted, "
            "invalid APP_ENV rejected",
        )
    ]


def check_install_uv_fresh() -> list[tuple[str, str, bool, str]]:
    scratch = Path(tempfile.mkdtemp(prefix="p28_uv_")) / "venv"
    try:
        env = _base_env(UV_PROJECT_ENVIRONMENT=str(scratch))
        t0 = time.monotonic()
        run(["uv", "sync", "--frozen"], cwd=BACKEND, env=env, timeout=900)
        python = (
            scratch
            / ("Scripts" if os.name == "nt" else "bin")
            / ("python.exe" if os.name == "nt" else "python")
        )
        run(
            [str(python), "-c", "import fastapi, sqlalchemy, fsrs, pgvector"],
            cwd=BACKEND,
            env=env,
            timeout=300,
        )
        run(
            [str(python), "-c", "import app.main"],
            cwd=BACKEND,
            env=_base_env(PYTHONPATH=".."),
            timeout=300,
        )
        elapsed = time.monotonic() - t0
        return [
            (
                "install.uv_fresh",
                "clean install: fresh venv from uv.lock",
                True,
                f"fresh venv + deps + app import in {elapsed:.0f}s (uv cache warm)",
            )
        ]
    finally:
        shutil.rmtree(scratch.parent, ignore_errors=True)


def check_install_uv_locked() -> list[tuple[str, str, bool, str]]:
    out = run(["uv", "sync", "--frozen"], cwd=BACKEND, timeout=600)
    drift = [ln for ln in out.splitlines() if "Updated" in ln or "Resolved" in ln]
    return [
        (
            "install.uv_locked",
            "lockfile has no drift (uv sync --frozen)",
            True,
            "; ".join(drift[:3]) or "environment already matches uv.lock",
        )
    ]


def check_install_pnpm_frozen() -> list[tuple[str, str, bool, str]]:
    run(["pnpm", "install", "--frozen-lockfile"], cwd=FRONTEND, timeout=900)
    return [
        (
            "install.pnpm_frozen",
            "frontend lockfile has no drift",
            True,
            "pnpm install --frozen-lockfile succeeded",
        )
    ]


def check_install_pnpm_scratch() -> list[tuple[str, str, bool, str]]:
    scratch = Path(tempfile.mkdtemp(prefix="p28_pnpm_"))
    try:
        # The full install input set: manifest, lockfile and pnpm's project
        # config — pnpm-workspace.yaml carries the allowBuilds decisions
        # that pnpm 12 refuses to install without.
        for name in ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", ".npmrc"):
            source = FRONTEND / name
            if source.is_file():
                shutil.copy(source, scratch / name)
        t0 = time.monotonic()
        run(["pnpm", "install", "--frozen-lockfile"], cwd=scratch, timeout=900)
        run(["pnpm", "exec", "tsc", "--version"], cwd=scratch, timeout=300)
        elapsed = time.monotonic() - t0
        return [
            (
                "install.pnpm_scratch",
                "clean install: pnpm install in an empty dir",
                True,
                f"manifest+lockfile+config produced node_modules in {elapsed:.0f}s",
            )
        ]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _scratch_ready() -> tuple[bk.ConnectionParams, URL]:
    """(connection_params, SQLAlchemy URL) for the readiness database.

    Keep the URL as an *object*: ``str(URL)`` masks the password
    (``user:***@host``), and feeding that masked string to ``create_engine``
    sends a literal ``***`` — PostgreSQL then answers "password
    authentication failed" (the failure this Phase 28 run root-caused).
    """
    params = bk.connection_params()
    return params, bk.scratch_url(params, SCRATCH_DB)


def _url_for_env(url: URL) -> str:
    """Render a SQLAlchemy URL *with* its password for DATABASE_URL env vars."""
    return url.render_as_string(hide_password=False)


def check_db_clean_migrate() -> list[tuple[str, str, bool, str]]:
    from sqlalchemy import create_engine, text

    params, url = _scratch_ready()
    bk.drop_database(params, SCRATCH_DB)
    bk.create_database(params, SCRATCH_DB)

    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        engine.dispose()

    t0 = time.monotonic()
    run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=_base_env(ALEMBIC_DATABASE_URL=_url_for_env(url), PYTHONPATH=".."),
        timeout=600,
    )
    elapsed = time.monotonic() - t0
    return [
        (
            "db.clean_migrate",
            "clean database: createdb -> extension -> alembic",
            True,
            f"scratch '{SCRATCH_DB}' created, vector extension enabled, "
            f"alembic upgrade head in {elapsed:.0f}s (head {alembic_head()})",
        )
    ]


def check_db_schema_objects() -> list[tuple[str, str, bool, str]]:
    from sqlalchemy import create_engine, text

    _, url = _scratch_ready()
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            tables = conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            ).scalar()
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            has_vector = conn.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            hnsw = conn.execute(
                text(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE tablename = 'sense_embeddings' AND indexdef ILIKE '%hnsw%'"
                )
            ).scalar()
            tsvector_cols = conn.execute(
                text("SELECT count(*) FROM information_schema.columns WHERE data_type = 'tsvector'")
            ).scalar()
    finally:
        engine.dispose()

    head = alembic_head()
    problems = []
    if not tables or tables < 20:
        problems.append(f"only {tables} tables")
    if revision != head:
        problems.append(f"alembic revision {revision} != head {head}")
    if not has_vector:
        problems.append("vector extension missing")
    if not hnsw:
        problems.append("HNSW index on sense_embeddings missing")
    if not tsvector_cols:
        problems.append("tsvector search columns missing")
    if problems:
        raise CheckError("; ".join(problems))
    return [
        (
            "db.schema_objects",
            "tables, vector extension/index, FTS, revision",
            True,
            f"{tables} tables, revision {revision}, pgvector + HNSW, "
            f"{tsvector_cols} tsvector columns",
        )
    ]


def check_app_first_run() -> list[tuple[str, str, bool, str]]:
    import httpx

    if not port_free(READY_PORT):
        raise CheckError(f"port {READY_PORT} is busy")

    _, url = _scratch_ready()
    log_path = Path(tempfile.mkdtemp(prefix="p28_log_")) / "readiness-uvicorn.log"
    log_path.write_text("", encoding="utf-8")
    results: list[tuple[str, str, bool, str]] = []

    handle = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(READY_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND),
        env=_base_env(DATABASE_URL=_url_for_env(url), LOG_FORMAT="json", PYTHONPATH=".."),
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_healthy(f"http://127.0.0.1:{READY_PORT}/api/v1/health")

        with httpx.Client(base_url=f"http://127.0.0.1:{READY_PORT}", timeout=30) as client:
            health = client.get("/api/v1/health")
            assert health.status_code == 200, health.text
            body = health.json()
            assert body["status"] == "ok" and body["database"] == "up", body

            payload = {
                "email": BOOTSTRAP_EMAIL,
                "password": BOOTSTRAP_PASSWORD,
                "display_name": "Readiness Teacher",
            }
            first = client.post("/api/v1/auth/bootstrap", json=payload)
            assert first.status_code == 201, f"bootstrap: {first.status_code} {first.text}"

            second = client.post("/api/v1/auth/bootstrap", json=payload)
            assert second.status_code == 403, f"second bootstrap: {second.status_code}"
            assert second.json()["error"]["code"] == "bootstrap_closed", second.text

            login = client.post(
                "/api/v1/auth/login",
                json={"email": BOOTSTRAP_EMAIL, "password": BOOTSTRAP_PASSWORD},
            )
            assert login.status_code == 200, f"login: {login.status_code} {login.text}"

            session = client.get("/api/v1/auth/session")
            assert session.status_code == 200, session.text
            assert session.json()["teacher"]["email"] == BOOTSTRAP_EMAIL

            students = client.get("/api/v1/students")
            assert students.status_code == 200 and students.json()["total"] == 0, students.text

            browse = client.get("/api/v1/vocabulary", params={"limit": 5})
            assert browse.status_code == 200 and browse.json()["total"] == 0, browse.text

            search = client.post(
                "/api/v1/vocabulary/search",
                json={"query": "hello", "mode": "lexical", "limit": 5},
            )
            assert search.status_code == 200 and search.json()["total"] == 0, search.text

        results.append(
            (
                "app.first_run_smoke",
                "bootstrap window, login, empty browse on clean DB",
                True,
                "health ok; first bootstrap 201, second 403 bootstrap_closed; "
                "login/session/students ok; empty browse + lexical search return 0 "
                "(semantic requires construction-time embeddings — documented)",
            )
        )
    except AssertionError as exc:
        results.append(
            ("app.first_run_smoke", "bootstrap/login smoke on clean DB", False, str(exc))
        )
    finally:
        _kill_tree(proc)
        handle.close()

    # Structured logging (§56) — same run, captured from the same process.
    lines = [
        ln
        for ln in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.startswith("{")
    ]
    log_path.unlink(missing_ok=True)
    shutil.rmtree(log_path.parent, ignore_errors=True)
    parsed = []
    for ln in lines:
        try:
            parsed.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    access = [
        p
        for p in parsed
        if "route" in p and "status" in p and "request_id" in p and "duration_ms" in p
    ]
    if not access:
        results.append(
            (
                "app.json_logs",
                "structured JSON access logs with request_id",
                False,
                f"no JSON access-log lines found ({len(parsed)} JSON lines total)",
            )
        )
    else:
        sample = access[0]
        results.append(
            (
                "app.json_logs",
                "structured JSON access logs with request_id",
                True,
                f"{len(access)} JSON access lines with request_id/route/status/"
                f"duration_ms (e.g. {sample['method']} {sample['route']} -> "
                f"{sample['status']} {sample['duration_ms']}ms)",
            )
        )
    return results


def check_db_migration_reversible() -> list[tuple[str, str, bool, str]]:
    _, url = _scratch_ready()
    env = _base_env(ALEMBIC_DATABASE_URL=_url_for_env(url), PYTHONPATH="..")
    run(["uv", "run", "alembic", "downgrade", "base"], cwd=BACKEND, env=env, timeout=600)

    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            remaining = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' "
                    "AND table_name <> 'alembic_version'"
                )
            ).scalar()
    finally:
        engine.dispose()
    if remaining:
        raise CheckError(f"downgrade base left {remaining} application tables")

    run(["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, timeout=600)
    return [
        (
            "db.migration_reversible",
            "alembic downgrade base -> upgrade head",
            True,
            "full downgrade removes every application table (alembic_version "
            f"bookkeeping remains); re-upgrade restores head {alembic_head()}",
        )
    ]


def check_build_backend() -> list[tuple[str, str, bool, str]]:
    run(
        ["uv", "run", "python", "-c", "import app.main; import pipeline.search.engine"],
        cwd=BACKEND,
        env=_base_env(PYTHONPATH=".."),
        timeout=300,
    )
    return [
        ("build.backend", "backend imports cleanly", True, "app.main + search engine import"),
    ]


def check_build_frontend_clean() -> list[tuple[str, str, bool, str]]:
    shutil.rmtree(FRONTEND / ".next", ignore_errors=True)
    t0 = time.monotonic()
    out = run(["pnpm", "build"], cwd=FRONTEND, timeout=900)
    elapsed = time.monotonic() - t0
    if "Compiled successfully" not in out and "Generating static pages" not in out:
        raise CheckError(f"unexpected build output:\n{out[-2000:]}")
    return [
        (
            "build.frontend_clean",
            "production build from an empty .next",
            True,
            f"next build from scratch in {elapsed:.0f}s (API base baked: "
            "http://localhost:8000 default, matching README)",
        )
    ]


def check_prod_stack() -> list[tuple[str, str, bool, str]]:
    import httpx

    for port in (PROD_BACKEND_PORT, PROD_FRONTEND_PORT):
        if not port_free(port):
            raise CheckError(f"port {port} is busy; free it and rerun")

    _, url = _scratch_ready()
    backend_log = Path(tempfile.mkdtemp(prefix="p28_prod_")) / "prod-uvicorn.log"
    backend_log.write_text("", encoding="utf-8")
    handle = backend_log.open("a", encoding="utf-8")

    backend = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PROD_BACKEND_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND),
        env=_base_env(
            APP_ENV="production",
            SESSION_SECRET=uuid.uuid4().hex + uuid.uuid4().hex,
            LOG_FORMAT="json",
            DATABASE_URL=_url_for_env(url),
            PYTHONPATH="..",
        ),
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    frontend = None
    try:
        _wait_healthy(f"http://127.0.0.1:{PROD_BACKEND_PORT}/api/v1/health")

        frontend = subprocess.Popen(
            _pnpm_argv(["pnpm", "exec", "next", "start", "-p", str(PROD_FRONTEND_PORT)]),
            cwd=str(FRONTEND),
            env=_base_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _wait_healthy(f"http://127.0.0.1:{PROD_FRONTEND_PORT}/", timeout_s=90)

        with httpx.Client(timeout=30, follow_redirects=False) as client:
            page = client.get(f"http://127.0.0.1:{PROD_FRONTEND_PORT}/login")
            assert page.status_code == 200, f"login page: {page.status_code}"
            assert "text/html" in page.headers.get("content-type", ""), page.headers

            health = client.get(f"http://127.0.0.1:{PROD_BACKEND_PORT}/api/v1/health")
            assert health.status_code == 200, health.text
            body = health.json()
            assert body["environment"] == "production", body
            assert health.headers.get("X-Content-Type-Options") == "nosniff"

            closed = client.post(
                f"http://127.0.0.1:{PROD_BACKEND_PORT}/api/v1/auth/bootstrap",
                json={
                    "email": BOOTSTRAP_EMAIL,
                    "password": BOOTSTRAP_PASSWORD,
                    "display_name": "Readiness Teacher",
                },
            )
            assert closed.status_code == 403, (
                f"production bootstrap on a teacher-less database: {closed.status_code}"
            )

        return [
            (
                "prod.stack",
                "uvicorn (APP_ENV=production) + next start smoke",
                True,
                "production uvicorn (real secret, JSON logs, secure headers) + "
                "next start serve the login page; bootstrap correctly closed "
                "by the existing teacher (§91)",
            )
        ]
    except AssertionError as exc:
        return [("prod.stack", "production stack smoke", False, str(exc))]
    finally:
        _kill_tree(frontend) if frontend is not None else None
        _kill_tree(backend)
        handle.close()
        shutil.rmtree(backend_log.parent, ignore_errors=True)


def check_tests_backend() -> list[tuple[str, str, bool, str]]:
    out = run(
        ["uv", "run", "python", "-m", "pytest", "tests/", "-p", "no:cacheprovider", "--no-header"],
        cwd=BACKEND,
        env=_base_env(PYTHONPATH=".."),
        timeout=1200,
    )
    counts = re.findall(r"(\d+) passed", out)
    if not counts:
        raise CheckError(f"no pytest summary found:\n{out[-2000:]}")
    return [
        (
            "tests.backend",
            "full pytest suite (dev database)",
            True,
            f"{counts[-1]} passed",
        )
    ]


def check_tests_frontend() -> list[tuple[str, str, bool, str]]:
    run(["pnpm", "exec", "tsc", "--noEmit"], cwd=FRONTEND, timeout=600)
    run(["pnpm", "exec", "eslint", "."], cwd=FRONTEND, timeout=600)
    out = run(["pnpm", "exec", "vitest", "run"], cwd=FRONTEND, timeout=600)
    counts = re.findall(r"Tests\s+(\d+) passed", out)
    if not counts:
        raise CheckError(f"no vitest summary found:\n{out[-2000:]}")
    return [
        (
            "tests.frontend",
            "tsc + eslint + vitest",
            True,
            f"tsc clean, eslint clean, vitest {counts[-1]} passed",
        )
    ]


def check_tests_e2e() -> list[tuple[str, str, bool, str]]:
    out = run(["pnpm", "exec", "playwright", "test"], cwd=FRONTEND, timeout=1500)
    counts = re.findall(r"(\d+) passed", out)
    if not counts:
        raise CheckError(f"no playwright summary found:\n{out[-2000:]}")
    return [
        (
            "tests.e2e",
            "Playwright acceptance suite (§59/§60/§61)",
            True,
            f"{counts[-1]} passed (suite owns :3000/:8737 for the run)",
        )
    ]


def check_backup_roundtrip() -> list[tuple[str, str, bool, str]]:
    t0 = time.monotonic()
    dump = bk.backup_database()
    backup_s = time.monotonic() - t0
    t1 = time.monotonic()
    report = bk.verify_restore(dump)
    restore_s = time.monotonic() - t1
    if not report.get("ok"):
        raise CheckError(f"restore verification failed: {report}")
    return [
        (
            "backup.restore_roundtrip",
            "fresh pg_dump + real restore verification",
            True,
            f"{report['dump_bytes']:,} B dump ({backup_s:.0f}s) restored and "
            f"verified ({restore_s:.0f}s): {report['tables_checked']} tables, "
            f"{report['source_rows']:,} rows, revision "
            f"{report['alembic_version_restored']}",
        )
    ]


def check_docs_setup_documented() -> list[tuple[str, str, bool, str]]:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    required = {
        "copy .env.example": ".env.example" in readme,
        "createdb": "createdb" in readme,
        "CREATE EXTENSION vector": "CREATE EXTENSION vector" in readme,
        "alembic upgrade head": "alembic upgrade head" in readme,
        "uv sync": "uv sync" in readme,
        "pnpm dev/install": ("pnpm dev" in readme) or ("pnpm install" in readme),
        "health check URL": "/api/v1/health" in readme,
        "playwright test": "playwright test" in readme,
        "pytest": "uv run pytest" in readme,
        "readiness script": "phase28_readiness.py" in readme,
    }
    for doc in ("docs/environment.md", "docs/backups.md", "docs/e2e.md"):
        required[f"{doc} exists"] = (REPO / doc).is_file()
    missing = [name for name, present in required.items() if not present]
    if missing:
        raise CheckError(f"README/docs missing: {missing}")
    return [
        (
            "docs.setup_documented",
            "README documents the clean setup commands",
            True,
            f"{len(required)} documented commands/artifacts verified",
        )
    ]


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
CheckFn = Callable[[], list[tuple[str, str, bool, str]]]

CHECKS: list[tuple[str, str, CheckFn]] = [
    ("env.example", "environment variables (.env.example coverage)", check_env_example),
    ("env.production_guard", "production config fails fast on secrets", check_env_production_guard),
    ("install.uv_fresh", "clean install: fresh venv from uv.lock", check_install_uv_fresh),
    ("install.uv_locked", "lockfile has no drift (uv sync --frozen)", check_install_uv_locked),
    ("install.pnpm_frozen", "frontend lockfile has no drift", check_install_pnpm_frozen),
    ("install.pnpm_scratch", "clean install: pnpm in an empty dir", check_install_pnpm_scratch),
    (
        "db.clean_migrate",
        "clean database: createdb -> extension -> alembic",
        check_db_clean_migrate,
    ),
    ("db.schema_objects", "tables, vector extension/index, FTS, revision", check_db_schema_objects),
    ("app.first_run_smoke", "bootstrap/login/empty browse on clean DB", check_app_first_run),
    ("build.backend", "backend imports cleanly", check_build_backend),
    ("build.frontend_clean", "production build from an empty .next", check_build_frontend_clean),
    ("prod.stack", "production uvicorn + next start smoke", check_prod_stack),
    ("tests.backend", "full pytest suite (dev database)", check_tests_backend),
    ("tests.frontend", "tsc + eslint + vitest", check_tests_frontend),
    ("tests.e2e", "Playwright acceptance suite (§59/§60/§61)", check_tests_e2e),
    # Reversible cycle runs after everything else that needs the scratch DB:
    # downgrade base wipes the schema those checks bootstrap against.
    (
        "db.migration_reversible",
        "alembic downgrade base -> upgrade head",
        check_db_migration_reversible,
    ),
    (
        "backup.restore_roundtrip",
        "fresh pg_dump + real restore verification",
        check_backup_roundtrip,
    ),
    ("docs.setup_documented", "README documents the clean setup", check_docs_setup_documented),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 28 local readiness gate (§104).")
    parser.add_argument("--fast", action="store_true", help="skip the slow checks")
    parser.add_argument("--skip", default="", help="comma-separated check ids to skip")
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated check ids to run (everything else skipped)",
    )
    parser.add_argument("--report", default=str(REPORT_PATH))
    args = parser.parse_args(argv)

    skipped_ids: set[str] = set(filter(None, args.skip.split(",")))
    only_ids: set[str] = set(filter(None, args.only.split(",")))
    if only_ids:
        unknown = only_ids - {cid for cid, _, _ in CHECKS}
        if unknown:
            parser.error(f"unknown check ids in --only: {sorted(unknown)}")
        skipped_ids |= {cid for cid, _, _ in CHECKS if cid not in only_ids}
    if args.fast:
        skipped_ids |= FAST_SKIP

    scratch_dependents = {
        "db.schema_objects",
        "app.first_run_smoke",
        "db.migration_reversible",
        "prod.stack",
    }

    started = datetime.now(UTC)
    t_start = time.monotonic()
    results: list[dict[str, Any]] = []
    scratch_ok = False
    frontend_build_ok = False

    def add(cid: str, title: str, ok: bool, details: str, duration: float) -> None:
        results.append(
            {
                "id": cid,
                "title": title,
                "status": "passed" if ok else "failed",
                "duration_s": round(duration, 1),
                "details": details,
            }
        )
        flag = "PASS" if ok else "FAIL"
        print(f"  {flag}  {cid:<28} {duration:>6.1f}s  {title}")
        if not ok:
            print(f"        {details[:1500]}")

    def skip(cid: str, title: str, reason: str) -> None:
        results.append(
            {"id": cid, "title": title, "status": "skipped", "duration_s": 0.0, "details": reason}
        )
        print(f"  SKIP  {cid:<28}        {reason}")

    for cid, title, func in CHECKS:
        if cid in skipped_ids:
            skip(cid, title, "skipped by flag")
            continue
        if cid in scratch_dependents and not scratch_ok:
            skip(cid, title, "depends on db.clean_migrate (not passed)")
            continue
        if cid == "prod.stack" and not frontend_build_ok:
            skip(cid, title, "depends on build.frontend_clean (not passed)")
            continue

        print(f"  ....  {cid:<28} {title}")
        t0 = time.monotonic()
        try:
            produced = func()
            duration = time.monotonic() - t0
            for pid, ptitle, ok, details in produced:
                add(pid, ptitle, ok, details, duration if pid == cid else 0.0)
                if pid == "db.clean_migrate":
                    scratch_ok = ok
                if pid == "build.frontend_clean":
                    frontend_build_ok = ok
        except Exception as exc:  # noqa: BLE001 — every check reports its own failure
            duration = time.monotonic() - t0
            detail = str(exc) or traceback.format_exc(limit=6)
            add(cid, title, False, detail, duration)

    # Drop the scratch database unless a db check failed (kept for debugging).
    db_failed = any(r["id"].startswith("db.") and r["status"] == "failed" for r in results)
    if not db_failed:
        try:
            params = bk.connection_params()
            bk.drop_database(params, SCRATCH_DB)
            print(f"  ....  scratch database '{SCRATCH_DB}' dropped")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN  could not drop scratch database: {exc}")
    else:
        print(f"  WARN  keeping '{SCRATCH_DB}' for debugging (a db.* check failed)")

    finished = datetime.now(UTC)

    # Merge with any prior report so the gate can run in time-boxed
    # invocations (--only / --skip): results upsert by check id and a
    # "skipped" entry never overwrites a real previous result.
    report_path = Path(args.report)
    prior: dict[str, Any] | None = None
    if report_path.is_file():
        try:
            prior = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prior = None

    merged: dict[str, dict[str, Any]] = {
        c["id"]: c for c in (prior or {}).get("checks", []) if isinstance(c, dict)
    }
    for entry in results:
        old = merged.get(entry["id"])
        if old is not None and entry["status"] == "skipped" and old["status"] != "skipped":
            continue  # keep the real previous result
        merged[entry["id"]] = entry
    final_checks = [merged[cid] for cid, _, _ in CHECKS if cid in merged]

    passed = sum(1 for r in final_checks if r["status"] == "passed")
    failed = sum(1 for r in final_checks if r["status"] == "failed")
    skipped = sum(1 for r in final_checks if r["status"] == "skipped")

    report = {
        "phase": 28,
        "title": "local readiness (§104, local-only per D026)",
        "started_at": (prior or {}).get("started_at", started.isoformat()),
        "finished_at": finished.isoformat(),
        "duration_s": round(time.monotonic() - t_start, 1),
        "invocations_merged": (int((prior or {}).get("invocations_merged", 0)) + 1 if prior else 1),
        "machine": {"system": platform.platform(), "python": platform.python_version()},
        "checks": final_checks,
        "summary": {"passed": passed, "failed": failed, "skipped": skipped, "ok": failed == 0},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"\nthis run: {sum(1 for r in results if r['status'] == 'passed')} passed, "
        f"{sum(1 for r in results if r['status'] == 'failed')} failed, "
        f"{sum(1 for r in results if r['status'] == 'skipped')} skipped "
        f"in {report['duration_s']}s"
    )
    print(
        f"merged report: {passed} passed, {failed} failed, {skipped} skipped "
        f"({report['invocations_merged']} invocation(s))"
    )
    print(f"report: {report_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
