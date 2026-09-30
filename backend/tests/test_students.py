"""Phase 17 tests: student management (sections 27/39/40).

Covers the §27 checklist (create, edit, deactivate, reactivate, delete,
profile, assigned-vocabulary view) plus §40: every endpoint requires an
authenticated teacher, and a teacher can never see or mutate another
teacher's students (foreign ids 404, indistinguishable from unknown).

DB-dependent tests run against the dev database with unique per-run
names and full cleanup in finally blocks.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import auth as auth_core
from tests.conftest import requires_db


def _email() -> str:
    return f"students-test-{uuid.uuid4().hex[:12]}@example.com"


def _make_teacher(email: str, password: str = "correct horse battery staple") -> uuid.UUID:
    from app.db.session import get_engine

    tid = uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, :ph, 'Students Test Teacher', true)"
            ),
            {"id": tid, "email": email, "ph": auth_core.hash_password(password)},
        )
    return tid


def _drop_teacher(email: str) -> None:
    """Remove the teacher and everything they own (test rows only)."""
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        tid = conn.execute(
            text("SELECT id FROM teachers WHERE email = :email"), {"email": email}
        ).scalar()
        if tid is None:
            return
        sv_ids = conn.execute(
            text("SELECT id FROM student_vocabulary WHERE student_id IN "
                 "(SELECT id FROM students WHERE teacher_id = :tid)"),
            {"tid": tid},
        ).scalars().all()
        if sv_ids:
            conn.execute(
                text("DELETE FROM student_fsrs_states WHERE student_vocabulary_id = ANY(:ids)"),
                {"ids": sv_ids},
            )
            conn.execute(
                text("DELETE FROM review_events WHERE student_vocabulary_id = ANY(:ids)"),
                {"ids": sv_ids},
            )
        conn.execute(
            text("DELETE FROM student_vocabulary WHERE student_id IN "
                 "(SELECT id FROM students WHERE teacher_id = :tid)"),
            {"tid": tid},
        )
        conn.execute(
            text("DELETE FROM students WHERE teacher_id = :tid"), {"tid": tid}
        )
        conn.execute(
            text("DELETE FROM teachers WHERE id = :tid"), {"tid": tid}
        )


def _login(client: TestClient, email: str, password: str = "correct horse battery staple") -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text


@requires_db
class TestAuthAndIsolation:
    """§40: authenticated teacher + authorized resource on every endpoint."""

    def test_all_endpoints_require_auth(self, client: TestClient) -> None:
        sid = str(uuid.uuid4())
        assert client.get("/api/v1/students").status_code == 401
        assert client.post("/api/v1/students", json={}).status_code in (401, 422)
        assert client.get(f"/api/v1/students/{sid}").status_code == 401
        assert client.patch(f"/api/v1/students/{sid}", json={}).status_code in (401, 422)
        assert client.patch(f"/api/v1/students/{sid}/status", json={}).status_code in (401, 422)
        assert client.get(f"/api/v1/students/{sid}/vocabulary").status_code == 401

    def test_foreign_student_is_404(self, client: TestClient) -> None:
        email_a, email_b = _email(), _email()
        try:
            _make_teacher(email_a)
            _make_teacher(email_b)
            c_a, c_b = TestClient(client.app), TestClient(client.app)
            _login(c_a, email_a)
            _login(c_b, email_b)

            created = c_a.post(
                "/api/v1/students", json={"display_name": "Alice A"}
            )
            assert created.status_code == 201, created.text
            sid = created.json()["id"]

            # Teacher B cannot see, edit, deactivate, or list teacher A's student.
            assert c_b.get(f"/api/v1/students/{sid}").status_code == 404
            assert c_b.patch(
                f"/api/v1/students/{sid}", json={"display_name": "Hacked"}
            ).status_code == 404
            assert c_b.patch(
                f"/api/v1/students/{sid}/status", json={"status": "INACTIVE"}
            ).status_code == 404
            assert c_b.get(f"/api/v1/students/{sid}/vocabulary").status_code == 404
            assert all(
                s["id"] != sid for s in c_b.get("/api/v1/students").json()["students"]
            )
        finally:
            _drop_teacher(email_a)
            _drop_teacher(email_b)


@requires_db
class TestLifecycle:
    """§27 checklist: create/edit/deactivate/reactivate/delete/profile."""

    def _client_with_teacher(self, client: TestClient) -> tuple[str, str]:
        email = _email()
        _make_teacher(email)
        c = TestClient(client.app)
        _login(c, email)
        return email, c

    def test_create_edit_deactivate_reactivate_delete(self, client: TestClient) -> None:
        email, c = self._client_with_teacher(client)
        try:
            # CREATE
            created = c.post(
                "/api/v1/students",
                json={
                    "display_name": "  Bruce Banner  ",
                    "email": "Bruce@Example.com ",
                    "notes": "Likes physics.",
                },
            )
            assert created.status_code == 201, created.text
            student = created.json()
            assert student["display_name"] == "Bruce Banner"  # trimmed
            assert student["email"] == "bruce@example.com"  # normalized
            assert student["status"] == "ACTIVE"
            assert student["assigned_count"] == 0
            sid = student["id"]

            # Duplicate email (same teacher) → 409
            dup = c.post(
                "/api/v1/students",
                json={"display_name": "Other", "email": "BRUCE@example.com"},
            )
            assert dup.status_code == 409
            assert dup.json()["error"]["code"] == "conflict"

            # EDIT (PATCH semantics: absent fields keep values)
            edited = c.patch(
                f"/api/v1/students/{sid}",
                json={"display_name": "Professor Hulk", "notes": None},
            )
            assert edited.status_code == 200, edited.text
            body = edited.json()
            assert body["display_name"] == "Professor Hulk"
            assert body["email"] == "bruce@example.com"  # unchanged
            assert body["notes"] is None  # explicitly cleared

            # DEACTIVATE
            off = c.patch(f"/api/v1/students/{sid}/status", json={"status": "INACTIVE"})
            assert off.status_code == 200
            assert off.json()["status"] == "INACTIVE"
            # default list hides inactive; include_inactive shows it
            assert all(s["id"] != sid for s in c.get("/api/v1/students").json()["students"])
            assert any(
                s["id"] == sid
                for s in c.get(
                    "/api/v1/students", params={"include_inactive": True}
                ).json()["students"]
            )

            # REACTIVATE
            on = c.patch(f"/api/v1/students/{sid}/status", json={"status": "ACTIVE"})
            assert on.status_code == 200
            assert on.json()["status"] == "ACTIVE"

            # DELETE (soft: record survives, learning history untouched)
            deleted = c.patch(f"/api/v1/students/{sid}/status", json={"status": "DELETED"})
            assert deleted.status_code == 200
            assert deleted.json()["status"] == "DELETED"
            assert c.get(f"/api/v1/students/{sid}").status_code == 404
            row = None
            from app.db.session import get_engine

            with get_engine().connect() as conn:
                row = conn.execute(
                    text("SELECT status FROM students WHERE id = CAST(:sid AS uuid)"),
                    {"sid": sid},
                ).scalar()
            assert row == "DELETED"  # row still exists

            # Unknown id → 404 envelope
            missing = c.get(f"/api/v1/students/{uuid.uuid4()}")
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "not_found"
        finally:
            _drop_teacher(email)

    def test_validation_errors(self, client: TestClient) -> None:
        email, c = self._client_with_teacher(client)
        try:
            blank = c.post("/api/v1/students", json={"display_name": "   "})
            assert blank.status_code == 422
            long_name = c.post(
                "/api/v1/students", json={"display_name": "x" * 201}
            )
            assert long_name.status_code == 422
            bad_email = c.post(
                "/api/v1/students",
                json={"display_name": "Ok", "email": "not-an-email"},
            )
            assert bad_email.status_code == 422
            bad_status = c.patch(
                f"/api/v1/students/{uuid.uuid4()}/status",
                json={"status": "GONE"},
            )
            assert bad_status.status_code == 422
        finally:
            _drop_teacher(email)

    def test_vocabulary_view_empty(self, client: TestClient) -> None:
        email, c = self._client_with_teacher(client)
        try:
            sid = c.post("/api/v1/students", json={"display_name": "New"}).json()["id"]
            vocab = c.get(f"/api/v1/students/{sid}/vocabulary")
            assert vocab.status_code == 200
            assert vocab.json() == {"items": [], "total": 0}
        finally:
            _drop_teacher(email)

    def test_vocabulary_view_lists_assignments(self, client: TestClient) -> None:
        email, c = self._client_with_teacher(client)
        try:
            from app.db.session import get_engine

            sid = c.post("/api/v1/students", json={"display_name": "Learner"}).json()["id"]
            with get_engine().begin() as conn:
                sense_id = conn.execute(
                    text(
                        "SELECT id FROM vocabulary_senses "
                        "WHERE headword_normalized = 'bank' LIMIT 1"
                    )
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO student_vocabulary "
                        "(id, student_id, sense_id, learning_state, is_active) "
                        "VALUES (:id, CAST(:sid AS uuid), CAST(:seid AS uuid), "
                        "'ASSIGNED', true)"
                    ),
                    {"id": uuid.uuid4(), "sid": sid, "seid": str(sense_id)},
                )
            vocab = c.get(f"/api/v1/students/{sid}/vocabulary").json()
            assert vocab["total"] == 1
            item = vocab["items"][0]
            assert item["sense"]["headword"] == "bank"
            assert item["learning_state"] == "ASSIGNED"
            assert item["is_active"] is True
            assert "assigned_at" in item and "due_at" in item
        finally:
            _drop_teacher(email)
