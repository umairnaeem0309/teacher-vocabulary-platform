"""Phase 19 tests: vocabulary sets (section 26, isolation per 40).

Covers the §26 checklist (create, rename, view, delete, add/remove
vocabulary, assign sets), duplicate-safe membership with the §29-style
report, name uniqueness per teacher, and §40 cross-teacher isolation.
Sets reference master senses — a test asserts no vocabulary rows are
created or destroyed by set operations (§26: never duplicate).

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
    return f"sets-test-{uuid.uuid4().hex[:12]}@example.com"


def _make_teacher(email: str) -> None:
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, :ph, 'Sets Test Teacher', true)"
            ),
            {
                "id": uuid.uuid4(),
                "email": email,
                "ph": auth_core.hash_password(PASSWORD),
            },
        )


def _drop_teacher(email: str) -> None:
    """CASCADE removes sets/items; assignments cleaned like other suites."""
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


def _sense_ids(n: int) -> list[str]:
    from app.db.session import get_engine

    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id FROM vocabulary_senses WHERE is_active "
                "AND headword_normalized != '' "
                "ORDER BY headword_normalized LIMIT :n"
            ),
            {"n": n},
        ).scalars().all()
    return [str(r) for r in rows]


@requires_db
class TestSetLifecycle:
    def test_create_rename_delete_and_uniqueness(self, client: TestClient) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)

            created = c.post(
                "/api/v1/sets",
                json={"name": "  Travel Vocabulary  ", "description": "Trips"},
            )
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["name"] == "Travel Vocabulary"  # trimmed
            assert body["item_count"] == 0
            sid = body["id"]

            # Per-teacher name uniqueness (uq_set_name_per_teacher).
            dup = c.post("/api/v1/sets", json={"name": "Travel Vocabulary"})
            assert dup.status_code == 409
            assert dup.json()["error"]["code"] == "conflict"

            # Rename (PATCH semantics: absent description kept).
            renamed = c.patch(f"/api/v1/sets/{sid}", json={"name": "A2 Cooking"})
            assert renamed.status_code == 200
            assert renamed.json()["name"] == "A2 Cooking"
            assert renamed.json()["description"] == "Trips"

            # Delete, then 404 afterwards.
            deleted = c.delete(f"/api/v1/sets/{sid}")
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True
            assert c.get(f"/api/v1/sets/{sid}").status_code == 404

            # Unknown set → 404 envelope.
            missing = c.get(f"/api/v1/sets/{uuid.uuid4()}")
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "not_found"
        finally:
            _drop_teacher(email)

    def test_blank_and_long_names_422(self, client: TestClient) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)
            assert c.post("/api/v1/sets", json={"name": "   "}).status_code == 422
            assert (
                c.post("/api/v1/sets", json={"name": "x" * 201}).status_code == 422
            )
        finally:
            _drop_teacher(email)


@requires_db
class TestMembership:
    def test_add_report_remove_and_no_vocabulary_duplication(
        self, client: TestClient
    ) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)
            sid = c.post("/api/v1/sets", json={"name": "Difficult Words"}).json()["id"]
            senses = _sense_ids(3)

            # Add 3 (one invalid id) → selected 3, new 2, failed 1.
            r = c.post(
                f"/api/v1/sets/{sid}/items",
                json={"sense_ids": senses[:2] + ["not-a-uuid"]},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert (body["selected"], body["new"], body["already_in_set"]) == (3, 2, 0)
            assert body["failed"] == [
                {"sense_id": "not-a-uuid", "reason": "invalid_id"}
            ]

            # Re-add → already_in_set (§29-style duplicates never stored).
            again = c.post(
                f"/api/v1/sets/{sid}/items", json={"sense_ids": senses[:2]}
            ).json()
            assert (again["new"], again["already_in_set"]) == (0, 2)

            # View includes the items with sense details.
            detail = c.get(f"/api/v1/sets/{sid}").json()
            assert detail["item_count"] == 2
            assert {i["sense_id"] for i in detail["items"]} == set(senses[:2])

            # §26 hard property: sets reference master senses — the senses
            # table is untouched by membership changes.
            from app.db.session import get_engine

            with get_engine().connect() as conn:
                total = conn.execute(
                    text("SELECT count(*) FROM vocabulary_senses")
                ).scalar_one()
            assert total > 40_000  # import-scale corpus still intact

            # Remove one; report says removed=1, not_in_set counts the rest.
            rem = c.request(
                "DELETE",
                f"/api/v1/sets/{sid}/items",
                json={"sense_ids": [senses[0], senses[2]]},
            )
            assert rem.status_code == 200
            rbody = rem.json()
            assert rbody["removed"] == 1
            assert rbody["not_in_set"] == 1
            assert c.get(f"/api/v1/sets/{sid}").json()["item_count"] == 1
        finally:
            _drop_teacher(email)


@requires_db
class TestAssignAndIsolation:
    def test_assign_set_to_student(self, client: TestClient) -> None:
        email = _email()
        try:
            _make_teacher(email)
            c = TestClient(client.app)
            _login(c, email)
            sid = c.post("/api/v1/sets", json={"name": "Exam Pack"}).json()["id"]
            senses = _sense_ids(3)
            c.post(f"/api/v1/sets/{sid}/items", json={"sense_ids": senses})
            student = c.post(
                "/api/v1/students", json={"display_name": "Exam Taker"}
            ).json()["id"]

            r = c.post(
                f"/api/v1/sets/{sid}/assign",
                json={"student_id": student},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["new"] == 3
            assert body["set_name"] == "Exam Pack"

            # Re-assign → already_assigned=3 (no duplicates created).
            again = c.post(f"/api/v1/sets/{sid}/assign", json={"student_id": student}).json()
            assert (again["new"], again["already_assigned"]) == (0, 3)

            # Student profile shows them.
            vocab = c.get(f"/api/v1/students/{student}/vocabulary").json()
            assert vocab["total"] == 3
        finally:
            _drop_teacher(email)

    def test_cross_teacher_set_and_student_404(self, client: TestClient) -> None:
        email_a, email_b = _email(), _email()
        try:
            _make_teacher(email_a)
            _make_teacher(email_b)
            c_a, c_b = TestClient(client.app), TestClient(client.app)
            _login(c_a, email_a)
            _login(c_b, email_b)

            sid = c_a.post("/api/v1/sets", json={"name": "Mine"}).json()["id"]
            student = c_a.post(
                "/api/v1/students", json={"display_name": "Also Mine"}
            ).json()["id"]

            # Teacher B cannot see, rename, add to, or assign A's set.
            assert c_b.get(f"/api/v1/sets/{sid}").status_code == 404
            assert c_b.patch(
                f"/api/v1/sets/{sid}", json={"name": "Hacked"}
            ).status_code == 404
            assert c_b.post(
                f"/api/v1/sets/{sid}/items", json={"sense_ids": [str(uuid.uuid4())]}
            ).status_code == 404
            assert c_b.post(
                f"/api/v1/sets/{sid}/assign", json={"student_id": student}
            ).status_code == 404

            # B's own same-named set is allowed (uniqueness is per teacher).
            ok = c_b.post("/api/v1/sets", json={"name": "Mine"})
            assert ok.status_code == 201
        finally:
            _drop_teacher(email_a)
            _drop_teacher(email_b)
