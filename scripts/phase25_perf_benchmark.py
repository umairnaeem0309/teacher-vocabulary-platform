"""Phase 25 benchmark: realistic-volume latency for every hot path (§101).

Measures end-to-end HTTP latency against the full development database
(41,687 senses, embeddings loaded) for the paths section 101 names:

- vocabulary search (lexical / semantic / hybrid)
- large table payloads (workbench browse at 50 and 500 rows)
- vocabulary detail
- bulk assignment (new + already-assigned paths)
- student profile (`/students/{id}/vocabulary`)
- review queue (`/reviews/due`)
- dashboard rollup (`/dashboard`) and per-student dashboard

Everything runs through the real app with a temporary teacher + student,
removed afterwards. Numbers are written to
``data/construction/phase25_perf_report.json`` and printed.

    cd backend
    PYTHONPATH=.. PYTHONIOENCODING=utf-8 uv run python ../scripts/phase25_perf_benchmark.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Offline-safe: the embedding model is already cached under data/models.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core import auth as auth_core  # noqa: E402
from app.main import app  # noqa: E402

BASE = "/api/v1"
PASSWORD = "correct horse battery staple"
REPEATS = 5
ASSIGNED_SENSES = 500  # realistic mid-term student
BULK_NEW = 250

REPORT_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "construction" / "phase25_perf_report.json"
)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _email() -> str:
    return f"perf-{uuid.uuid4().hex[:12]}@example.com"


def _make_teacher(email: str) -> uuid.UUID:
    from app.db.session import get_engine

    tid = uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, :ph, 'Perf Teacher', true)"
            ),
            {"id": tid, "email": email, "ph": auth_core.hash_password(PASSWORD)},
        )
    return tid


def _drop_teacher(email: str) -> None:
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        tid = conn.execute(
            text("SELECT id FROM teachers WHERE email = :email"), {"email": email}
        ).scalar()
        if tid is None:
            return
        sv_ids = (
            conn.execute(
                text(
                    "SELECT id FROM student_vocabulary WHERE student_id IN "
                    "(SELECT id FROM students WHERE teacher_id = :tid)"
                ),
                {"tid": tid},
            )
            .scalars()
            .all()
        )
        if sv_ids:
            conn.execute(
                text("DELETE FROM review_events WHERE student_vocabulary_id = ANY(:ids)"),
                {"ids": sv_ids},
            )
            conn.execute(
                text("DELETE FROM student_fsrs_states WHERE student_vocabulary_id = ANY(:ids)"),
                {"ids": sv_ids},
            )
        conn.execute(
            text(
                "DELETE FROM student_vocabulary WHERE student_id IN "
                "(SELECT id FROM students WHERE teacher_id = :tid)"
            ),
            {"tid": tid},
        )
        conn.execute(text("DELETE FROM students WHERE teacher_id = :tid"), {"tid": tid})
        conn.execute(text("DELETE FROM teacher_sessions WHERE teacher_id = :tid"), {"tid": tid})
        conn.execute(text("DELETE FROM teachers WHERE id = :tid"), {"tid": tid})


def _pick_senses(count: int) -> list[str]:
    """Deterministic realistic slice: active, high-priority senses first."""
    from app.db.session import get_engine

    with get_engine().connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT id FROM vocabulary_senses WHERE is_active "
                    "ORDER BY priority_score DESC NULLS LAST, headword_normalized "
                    "LIMIT :n"
                ),
                {"n": count},
            )
            .scalars()
            .all()
        )
    return [str(r) for r in rows]


# --------------------------------------------------------------------------- #
# measurement
# --------------------------------------------------------------------------- #
def _time(client: TestClient, method: str, url: str, **kw) -> tuple[float, int, int]:
    """Return (p50 seconds, status, response bytes) over REPEATS calls."""
    call = getattr(client, method)
    latencies: list[float] = []
    status = 0
    size = 0
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        resp = call(url, **kw)
        latencies.append(time.perf_counter() - t0)
        status = resp.status_code
        size = len(resp.content)
        if status >= 400:
            break
    return statistics.median(latencies), status, size


def _row(label: str, seconds: float, status: int, size: int) -> dict:
    return {
        "metric": label,
        "p50_ms": round(seconds * 1000, 1),
        "status": status,
        "bytes": size,
    }


def main() -> int:
    email = _email()
    _make_teacher(email)
    results: list[dict] = []
    client = TestClient(app)
    student_id: str | None = None
    try:
        resp = client.post(f"{BASE}/auth/login", json={"email": email, "password": PASSWORD})
        assert resp.status_code == 200, resp.text

        resp = client.post(f"{BASE}/students", json={"display_name": "Perf Student"})
        assert resp.status_code == 201, resp.text
        student_id = resp.json()["id"]

        # --- search modes --------------------------------------------------- #
        searches = [
            ("search lexical (bank)", {"mode": "lexical", "query": "bank", "limit": 50}),
            ("search lexical (browse, no query)", {"mode": "lexical", "query": "", "limit": 50}),
            (
                "search semantic (things needed when traveling)",
                {"mode": "semantic", "query": "things needed when traveling", "limit": 50},
            ),
            ("search hybrid (vacation)", {"mode": "hybrid", "query": "vacation", "limit": 50}),
            (
                "search hybrid + filters (A2 HIGH)",
                {
                    "mode": "hybrid",
                    "query": "vacation",
                    "limit": 50,
                    "filters": {"cefr": ["A2"], "priority_levels": ["HIGH"]},
                },
            ),
        ]
        # Warm-up once per mode (loader, PG cache) so the first probe is not
        # penalised by one-off model loading.
        for _, payload in searches:
            client.post(f"{BASE}/vocabulary/search", json=payload)
        for label, payload in searches:
            s, status, size = _time(client, "post", f"{BASE}/vocabulary/search", json=payload)
            results.append(_row(label, s, status, size))

        # Semantic cold vs warm: repeated identical queries are the common
        # teacher pattern (same topic re-searched across students); the
        # query-embedding cache should make warm repeats much cheaper.
        warm_query = "things needed when traveling"
        s, status, size = _time(
            client, "post", f"{BASE}/vocabulary/search",
            json={"mode": "semantic", "query": warm_query, "limit": 50},
        )
        results.append(_row("search semantic (warm repeat)", s, status, size))

        cold_lat: list[float] = []
        cold_status = 0
        cold_size = 0
        for i in range(REPEATS):
            payload = {
                "mode": "semantic",
                "query": f"unique perf query {uuid.uuid4().hex[:8]} number {i}",
                "limit": 50,
            }
            t0 = time.perf_counter()
            resp = client.post(f"{BASE}/vocabulary/search", json=payload)
            cold_lat.append(time.perf_counter() - t0)
            cold_status, cold_size = resp.status_code, len(resp.content)
        results.append(
            _row(
                "search semantic (cold unique query)",
                statistics.median(cold_lat),
                cold_status,
                cold_size,
            )
        )

        # --- large table payloads ------------------------------------------ #
        for size_n in (50, 200, 500):
            s, status, size = _time(
                client,
                "get",
                f"{BASE}/vocabulary",
                params={"limit": size_n, "offset": 0, "sort": "priority"},
            )
            results.append(_row(f"browse table ({size_n} rows)", s, status, size))

        # --- one sense detail ---------------------------------------------- #
        sense_id = _pick_senses(1)[0]
        s, status, size = _time(client, "get", f"{BASE}/vocabulary/{sense_id}")
        results.append(_row("vocabulary detail (1 sense)", s, status, size))

        # --- bulk assignment ------------------------------------------------ #
        all_senses = _pick_senses(ASSIGNED_SENSES + BULK_NEW)
        seed, bulk = all_senses[:ASSIGNED_SENSES], all_senses[ASSIGNED_SENSES:]
        # seed a realistic assigned set for the profile/queue numbers
        client.post(
            f"{BASE}/assignments",
            json={"student_id": student_id, "sense_ids": seed},
        )
        s, status, size = _time(
            client,
            "post",
            f"{BASE}/assignments",
            json={"student_id": student_id, "sense_ids": bulk},
        )
        results.append(_row(f"bulk assignment ({BULK_NEW} new)", s, status, size))
        s, status, size = _time(
            client,
            "post",
            f"{BASE}/assignments",
            json={"student_id": student_id, "sense_ids": bulk},
        )
        results.append(_row(f"bulk assignment ({BULK_NEW} already)", s, status, size))

        # --- student profile / queue / dashboard ---------------------------- #
        s, status, size = _time(client, "get", f"{BASE}/students/{student_id}/vocabulary")
        results.append(
            _row(f"student profile vocabulary ({ASSIGNED_SENSES}+ rows)", s, status, size)
        )

        s, status, size = _time(client, "get", f"{BASE}/students/{student_id}/dashboard")
        results.append(_row("per-student dashboard", s, status, size))

        s, status, size = _time(
            client, "get", f"{BASE}/reviews/due", params={"student_id": student_id}
        )
        results.append(_row("review queue", s, status, size))

        s, status, size = _time(client, "get", f"{BASE}/dashboard")
        results.append(_row("dashboard rollup", s, status, size))

        s, status, size = _time(client, "get", f"{BASE}/students")
        results.append(_row("students list", s, status, size))

        report = {
            "assigned_senses": ASSIGNED_SENSES,
            "bulk_new": BULK_NEW,
            "repeats": REPEATS,
            "results": results,
        }
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        print(f"\nwrote {REPORT_PATH}")
        return 0
    finally:
        if student_id:
            _drop_teacher(email)


if __name__ == "__main__":
    raise SystemExit(main())
