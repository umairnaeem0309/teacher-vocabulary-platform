"""Phase 21 tests: per-student dashboard (section 36).

Covers:
- empty student: zero counts, no next-up, no difficult/recent entries;
- live flow: assignment -> next_up; HARD review -> learning count +
  difficult entry + recent review; explicit due backdating -> overdue
  count and next_up flag, future due -> due count (definitions
  consistent with the §32 queue buckets);
- state counts (LEARNING/REVIEWING/MASTERED) and §40 isolation
  (foreign and unknown students are 404).

Reuses the dev database and the Phase 20 helpers' conventions; all rows
are removed in finally blocks.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import auth as auth_core
from tests.conftest import requires_db

PASSWORD = "correct horse battery staple"


def _email() -> str:
    return f"dash-test-{uuid.uuid4().hex[:12]}@example.com"


def _make_teacher(email: str) -> uuid.UUID:
    from app.db.session import get_engine

    tid = uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, :ph, 'Dashboard Test Teacher', true)"
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
        conn.execute(text("DELETE FROM teachers WHERE id = :tid"), {"tid": tid})


def _login(client: TestClient, email: str) -> None:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _pick_senses(count: int) -> list[str]:
    from app.db.session import get_engine

    with get_engine().connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT id FROM vocabulary_senses WHERE is_active "
                    "AND headword_normalized != '' "
                    "ORDER BY headword_normalized LIMIT :n"
                ),
                {"n": count},
            )
            .scalars()
            .all()
        )
    assert len(rows) == count
    return [str(r) for r in rows]


def _assign(student: str, sense_id: str, state: str = "ASSIGNED") -> str:
    from app.db.session import get_engine

    aid = str(uuid.uuid4())
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO student_vocabulary "
                "(id, student_id, sense_id, learning_state, is_active) "
                "VALUES (:id, CAST(:sid AS uuid), CAST(:seid AS uuid), "
                ":state, true)"
            ),
            {"id": aid, "sid": student, "seid": sense_id, "state": state},
        )
    return aid


def _set_due(aid: str, sql: str) -> None:
    """Move the FSRS due date (e.g. \"now() - interval '1 hour'\")."""
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE student_fsrs_states SET due_at = " + sql + " "
                "WHERE student_vocabulary_id = CAST(:aid AS uuid)"
            ),
            {"aid": aid},
        )


@requires_db
class TestDashboard:
    def _setup(self, client: TestClient) -> tuple[str, TestClient, str]:
        email = _email()
        _make_teacher(email)
        c = TestClient(client.app)
        _login(c, email)
        student = c.post("/api/v1/students", json={"display_name": "Dash Me"}).json()["id"]
        return email, c, student

    def test_empty_student(self, client: TestClient) -> None:
        email, c, student = self._setup(client)
        try:
            resp = c.get(f"/api/v1/students/{student}/dashboard")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["student"]["id"] == student
            assert body["student"]["display_name"] == "Dash Me"
            assert body["counts"] == {
                "assigned": 0,
                "learning": 0,
                "reviewing": 0,
                "mastered": 0,
                "due": 0,
                "overdue": 0,
            }
            assert body["next_up"] is None
            assert body["difficult"] == []
            assert body["recent_reviews"] == []
        finally:
            _drop_teacher(email)

    def test_flow_counts_and_next_up(self, client: TestClient) -> None:
        email, c, student = self._setup(client)
        try:
            sense = _pick_senses(1)[0]
            aid = _assign(student, sense)

            body = c.get(f"/api/v1/students/{student}/dashboard").json()
            assert body["counts"]["assigned"] == 1
            # New (never reviewed) card answers the §36 question first.
            assert body["next_up"] is not None
            assert body["next_up"]["assignment_id"] == aid
            assert body["next_up"]["is_overdue"] is None
            assert body["next_up"]["sense"]["headword"]

            # A HARD review: learning count, difficult entry, recent entry.
            r = c.post(
                "/api/v1/reviews",
                json={
                    "student_id": student,
                    "assignment_id": aid,
                    "rating": "HARD",
                },
            )
            assert r.status_code == 201, r.text

            body = c.get(f"/api/v1/students/{student}/dashboard").json()
            assert body["counts"]["learning"] == 1
            assert len(body["difficult"]) == 1
            assert body["difficult"][0]["assignment_id"] == aid
            assert body["difficult"][0]["hard_count"] == 1
            assert body["difficult"][0]["total_reviews"] == 1
            assert len(body["recent_reviews"]) == 1
            assert body["recent_reviews"][0]["rating"] == "HARD"
            assert body["recent_reviews"][0]["headword"]

            # Overdue (explicitly backdated): overdue bucket + next_up flag.
            _set_due(aid, "now() - interval '1 hour'")
            body = c.get(f"/api/v1/students/{student}/dashboard").json()
            assert body["counts"]["overdue"] == 1
            assert body["counts"]["due"] == 0
            assert body["next_up"]["assignment_id"] == aid
            assert body["next_up"]["is_overdue"] is True

            # Due later today (end of today minus 1s: deterministic at any
            # wall-clock time): due bucket, next_up not overdue.
            _set_due(
                aid,
                "date_trunc('day', now()) + interval '1 day' - interval '1 second'",
            )
            body = c.get(f"/api/v1/students/{student}/dashboard").json()
            assert body["counts"]["due"] == 1
            assert body["counts"]["overdue"] == 0
            assert body["next_up"]["assignment_id"] == aid
            assert body["next_up"]["is_overdue"] is False

            # Far-future due: leaves the queue, next_up falls back to none.
            _set_due(aid, "now() + interval '30 days'")
            body = c.get(f"/api/v1/students/{student}/dashboard").json()
            assert body["next_up"] is None
            assert body["counts"]["due"] == 0
            assert body["counts"]["overdue"] == 0
        finally:
            _drop_teacher(email)

    def test_state_counts_isolation_and_404(self, client: TestClient) -> None:
        email, c, student = self._setup(client)
        try:
            senses = _pick_senses(3)
            _assign(student, senses[0], "LEARNING")
            _assign(student, senses[1], "REVIEWING")
            _assign(student, senses[2], "MASTERED")

            body = c.get(f"/api/v1/students/{student}/dashboard").json()
            assert body["counts"]["assigned"] == 3
            assert body["counts"]["learning"] == 1
            assert body["counts"]["reviewing"] == 1
            assert body["counts"]["mastered"] == 1

            # §40: another teacher cannot see this dashboard.
            other_email = _email()
            _make_teacher(other_email)
            try:
                c2 = TestClient(client.app)
                _login(c2, other_email)
                foreign = c2.get(f"/api/v1/students/{student}/dashboard")
                assert foreign.status_code == 404
            finally:
                _drop_teacher(other_email)

            # Unknown student id is indistinguishable from foreign (404).
            missing = c.get(f"/api/v1/students/{uuid.uuid4()}/dashboard")
            assert missing.status_code == 404

            # Overview (§98): this teacher sees only their own student,
            # with the same counts; the other teacher's list is empty.
            ov = c.get("/api/v1/dashboard").json()
            assert ov["total"] == 1
            row = ov["students"][0]
            assert row["student"]["id"] == student
            assert row["assigned"] == 3
            assert ov["totals"]["assigned"] == 3
        finally:
            _drop_teacher(email)

    def test_overview_isolation_and_ordering(self, client: TestClient) -> None:
        email, c, student = self._setup(client)
        try:
            other_email = _email()
            _make_teacher(other_email)
            try:
                c2 = TestClient(client.app)
                _login(c2, other_email)
                # Empty roster for the second teacher, and the first
                # teacher's student never leaks into it (§40).
                assert c2.get("/api/v1/dashboard").json()["total"] == 0

                # Attention-need ordering: an overdue student sorts before
                # a merely-due one, which sorts before a plain one.
                s_due = c2.post("/api/v1/students", json={"display_name": "A Due"}).json()["id"]
                s_over = c2.post("/api/v1/students", json={"display_name": "B Over"}).json()["id"]
                s_plain = c2.post("/api/v1/students", json={"display_name": "C Plain"}).json()["id"]
                sense = _pick_senses(1)[0]
                _assign(s_due, sense)
                _assign(s_over, sense)
                from app.db.session import get_engine

                with get_engine().begin() as conn:
                    for sid in (s_due, s_over):
                        conn.execute(
                            text(
                                "UPDATE student_vocabulary SET learning_state = "
                                "'REVIEWING' WHERE student_id = CAST(:sid AS uuid)"
                            ),
                            {"sid": sid},
                        )
                from fsrs import Card, Rating

                from app.core.reviews import SCHEDULER

                now = __import__("datetime").datetime.now(__import__("datetime").UTC)
                card_due, _ = SCHEDULER.review_card(Card(), Rating.Good, review_datetime=now)
                card_over, _ = SCHEDULER.review_card(Card(), Rating.Good, review_datetime=now)
                with get_engine().begin() as conn:
                    for sid, card, due_sql in (
                        (
                            s_due,
                            card_due,
                            "date_trunc('day', now()) + interval '1 day' - interval '1 second'",
                        ),
                        (s_over, card_over, "now() - interval '1 hour'"),
                    ):
                        sv_id = conn.execute(
                            text(
                                "SELECT id FROM student_vocabulary "
                                "WHERE student_id = CAST(:sid AS uuid)"
                            ),
                            {"sid": sid},
                        ).scalar_one()
                        conn.execute(
                            text(
                                "INSERT INTO student_fsrs_states "
                                "(id, student_vocabulary_id, state_json, "
                                " stability, difficulty, repetitions, lapses, "
                                " due_at, fsrs_version) VALUES (:id, "
                                " CAST(:sv AS uuid), CAST(:sj AS jsonb), "
                                " :st, :df, 1, 0, " + due_sql + ", :ver)"
                            ),
                            {
                                "id": uuid.uuid4(),
                                "sv": str(sv_id),
                                "sj": card.to_json(),
                                "st": card.stability,
                                "df": card.difficulty,
                                "ver": "fsrs6-py-6.3.2",
                            },
                        )
                order = [
                    row["student"]["id"] for row in c2.get("/api/v1/dashboard").json()["students"]
                ]
                assert order.index(s_over) < order.index(s_due)
                assert order.index(s_due) < order.index(s_plain)
            finally:
                _drop_teacher(other_email)
        finally:
            _drop_teacher(email)
