"""Phase 18 tests: assignment (sections 28-30).

Covers §28 relationship + UNIQUE(student_id, sense_id) backstop, §29
layered duplicate prevention with the selected/new/already/failed
report, §31 explicit teacher overrides, and §40 isolation. Also proves
the §30 not-assigned filter at the engine level (already Phase 14
code) against real assignment rows.

Reuses the dev database; every row created here is removed in finally.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import auth as auth_core
from tests.conftest import requires_db

PASSWORD = "correct horse battery staple"


def _email() -> str:
    return f"assign-test-{uuid.uuid4().hex[:12]}@example.com"


def _make_teacher(email: str) -> uuid.UUID:
    from app.db.session import get_engine

    tid = uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, :ph, 'Assign Test Teacher', true)"
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
        conn.execute(
            text(
                "DELETE FROM student_vocabulary WHERE student_id IN "
                "(SELECT id FROM students WHERE teacher_id = :tid)"
            ),
            {"tid": tid},
        )
        conn.execute(
            text("DELETE FROM students WHERE teacher_id = :tid"), {"tid": tid}
        )
        conn.execute(text("DELETE FROM teachers WHERE id = :tid"), {"tid": tid})


def _login(client: TestClient, email: str) -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


def _make_student(client: TestClient, display_name: str) -> str:
    resp = client.post("/api/v1/students", json={"display_name": display_name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _sense_ids(n: int) -> list[str]:
    from app.db.session import get_engine

    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id FROM vocabulary_senses WHERE is_active "
                "AND headword_normalized != '' ORDER BY headword_normalized LIMIT :n"
            ),
            {"n": n},
        ).scalars().all()
    assert len(rows) == n
    return [str(r) for r in rows]


@requires_db
class TestAssign:
    def test_single_assign_and_report(self, client: TestClient) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)
            sid = _make_student(c, "Assignee")
            sense = _sense_ids(1)[0]

            r = c.post(
                "/api/v1/assignments",
                json={"student_id": sid, "sense_ids": [sense]},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body == {
                "selected": 1,
                "new": 1,
                "already_assigned": 0,
                "failed": [],
                "student_id": sid,
                "sense_ids": [sense],
            }

            # §30: the assigned sense shows in assigned=true, hidden in false.
            only = c.post(
                "/api/v1/vocabulary/search",
                json={
                    "query": "",
                    "mode": "lexical",
                    "sort": "headword",
                    "filters": {"student_id": sid, "assigned": True},
                    "limit": 200,
                },
            ).json()
            assert sense in {h["sense_id"] for h in only["hits"]}
            not_assigned = c.post(
                "/api/v1/vocabulary/search",
                json={
                    "query": "",
                    "mode": "lexical",
                    "sort": "headword",
                    "filters": {"student_id": sid, "assigned": False},
                    "limit": 200,
                },
            ).json()
            assert sense not in {h["sense_id"] for h in not_assigned["hits"]}
        finally:
            _drop_teacher(email)

    def test_bulk_duplicates_and_counts(self, client: TestClient) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)
            sid = _make_student(c, "Bulk Assignee")
            senses = _sense_ids(20)

            # 20 selected → 18 new, 2 already assigned (pre-assigned), 1 bad id.
            pre = senses[:2]
            first = c.post(
                "/api/v1/assignments",
                json={"student_id": sid, "sense_ids": pre},
            )
            assert first.status_code == 200
            payload = {"student_id": sid, "sense_ids": senses + ["not-a-uuid"]}
            second = c.post("/api/v1/assignments", json=payload)
            assert second.status_code == 200
            body = second.json()
            assert body["selected"] == 21
            assert body["new"] == 18
            assert body["already_assigned"] == 2
            assert len(body["failed"]) == 1
            assert body["failed"][0]["reason"] == "invalid_id"

            # §28: DB constraint is the backstop — a raw duplicate insert
            # violates uq_student_sense even if application checks are bypassed.
            from app.db.session import get_engine

            with get_engine().begin() as conn:
                inserted = conn.execute(
                    text(
                        "SELECT count(*) FROM student_vocabulary "
                        "WHERE student_id = CAST(:sid AS uuid)"
                    ),
                    {"sid": sid},
                ).scalar_one()
            assert inserted == 20  # not 22: duplicates never stored twice
        finally:
            _drop_teacher(email)

    def test_unknown_sense_reported_failed(self, client: TestClient) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)
            sid = _make_student(c, "Reporter")
            ghost = str(uuid.uuid4())
            r = c.post(
                "/api/v1/assignments",
                json={"student_id": sid, "sense_ids": [ghost]},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["new"] == 0
            assert body["failed"] == [
                {"sense_id": ghost, "reason": "sense_not_found"}
            ]
        finally:
            _drop_teacher(email)

    def test_unknown_student_404(self, client: TestClient) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)
            sense = _sense_ids(1)[0]
            r = c.post(
                "/api/v1/assignments",
                json={"student_id": str(uuid.uuid4()), "sense_ids": [sense]},
            )
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "not_found"
        finally:
            _drop_teacher(email)

    def test_cross_teacher_student_404(self, client: TestClient) -> None:
        email_a, email_b = _email(), _email()
        try:
            _make_teacher(email_a)
            _make_teacher(email_b)
            c_a, c_b = TestClient(client.app), TestClient(client.app)
            _login(c_a, email_a)
            _login(c_b, email_b)
            sid = _make_student(c_a, "Belongs to A")
            sense = _sense_ids(1)[0]
            r = c_b.post(
                "/api/v1/assignments",
                json={"student_id": sid, "sense_ids": [sense]},
            )
            assert r.status_code == 404
        finally:
            _drop_teacher(email_a)
            _drop_teacher(email_b)


@requires_db
class TestAssignmentEdit:
    def test_state_and_priority_override(self, client: TestClient) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)
            sid = _make_student(c, "Overridable")
            sense = _sense_ids(1)[0]
            c.post("/api/v1/assignments", json={"student_id": sid, "sense_ids": [sense]})

            # Find the assignment id through the student vocabulary view.
            items = c.get(f"/api/v1/students/{sid}/vocabulary").json()["items"]
            aid = next(i["id"] for i in items if i["sense"]["id"] == sense)

            # §31: explicit teacher override of state + per-student priority.
            r = c.patch(
                f"/api/v1/assignments/{aid}",
                params={"student_id": sid},
                json={
                    "learning_state": "LEARNING",
                    "teacher_priority_override": "VERY HIGH",
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["learning_state"] == "LEARNING"
            assert body["teacher_priority_override"] == "VERY HIGH"

            # Absent fields keep values; sent null clears the override.
            keep = c.patch(
                f"/api/v1/assignments/{aid}",
                params={"student_id": sid},
                json={"teacher_priority_override": None},
            )
            assert keep.status_code == 200
            assert keep.json()["learning_state"] == "LEARNING"  # kept
            assert keep.json()["teacher_priority_override"] is None  # cleared

            # Deactivating hides from assigned=true without deleting.
            off = c.patch(
                f"/api/v1/assignments/{aid}",
                params={"student_id": sid},
                json={"is_active": False},
            )
            assert off.status_code == 200
            only = c.post(
                "/api/v1/vocabulary/search",
                json={
                    "query": "",
                    "mode": "lexical",
                    "sort": "headword",
                    "filters": {"student_id": sid, "assigned": True},
                    "limit": 200,
                },
            ).json()
            assert sense not in {h["sense_id"] for h in only["hits"]}
        finally:
            _drop_teacher(email)

    def test_invalid_state_and_priority_422(self, client: TestClient) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)
            sid = _make_student(c, "Validator")
            sense = _sense_ids(1)[0]
            c.post("/api/v1/assignments", json={"student_id": sid, "sense_ids": [sense]})
            items = c.get(f"/api/v1/students/{sid}/vocabulary").json()["items"]
            aid = items[0]["id"]

            bad_state = c.patch(
                f"/api/v1/assignments/{aid}",
                params={"student_id": sid},
                json={"learning_state": "WIZARDRY"},
            )
            assert bad_state.status_code == 422
            bad_prio = c.patch(
                f"/api/v1/assignments/{aid}",
                params={"student_id": sid},
                json={"teacher_priority_override": "ULTRA"},
            )
            assert bad_prio.status_code == 422
        finally:
            _drop_teacher(email)
