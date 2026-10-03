"""Phase 20 tests: FSRS reviews (sections 31-33, 35).

Covers:
- the §6 rating mapping (HARD->Again, MEDIUM->Hard, EASY->Good) and
  deterministic FSRS interval fixtures (library-backed, fuzzing off);
- the §32 flow: due queue ordering (overdue -> due -> new), record
  review, next-due calculation, learning-state moves;
- §33 immutable history: every event stores previous/new card state and
  due dates; sequential reviews append, never overwrite;
- §40 isolation (foreign students/assignments 404) and validation.

Reuses the dev database; all rows are removed in finally blocks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from fsrs import Card, Rating
from sqlalchemy import text

from app.core import auth as auth_core
from app.core.reviews import FSRS_VERSION, SCHEDULER, TEACHER_TO_FSRS
from tests.conftest import requires_db

PASSWORD = "correct horse battery staple"


def _email() -> str:
    return f"review-test-{uuid.uuid4().hex[:12]}@example.com"


def _make_teacher(email: str) -> uuid.UUID:
    from app.db.session import get_engine

    tid = uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, :ph, 'Review Test Teacher', true)"
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
        sv_ids = conn.execute(
            text(
                "SELECT id FROM student_vocabulary WHERE student_id IN "
                "(SELECT id FROM students WHERE teacher_id = :tid)"
            ),
            {"tid": tid},
        ).scalars().all()
        if sv_ids:
            conn.execute(
                text(
                    "DELETE FROM review_events WHERE student_vocabulary_id = ANY(:ids)"
                ),
                {"ids": sv_ids},
            )
            conn.execute(
                text(
                    "DELETE FROM student_fsrs_states "
                    "WHERE student_vocabulary_id = ANY(:ids)"
                ),
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
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


class TestRatingMappingAndFixtures:
    """§6/§31: deterministic mapping and interval fixtures (no DB)."""

    def test_mapping_exact(self) -> None:
        assert TEACHER_TO_FSRS["HARD"] is Rating.Again
        assert TEACHER_TO_FSRS["MEDIUM"] is Rating.Hard
        assert TEACHER_TO_FSRS["EASY"] is Rating.Good

    def test_fsrs_interval_fixtures_deterministic(self) -> None:
        now = datetime.now(UTC)
        card = Card()
        # Graduation: Good on a new card -> Review state, ~2 day interval.
        c1, _ = SCHEDULER.review_card(card, Rating.Good, review_datetime=now)
        assert c1.state == 2
        assert 1.5 <= (c1.due - now).total_seconds() / 86400 <= 2.5
        # Successful reviews grow intervals (2d -> ~2 weeks -> ~5 weeks).
        c2, _ = SCHEDULER.review_card(
            c1, Rating.Good, review_datetime=now + timedelta(days=3)
        )
        interval_2 = (c2.due - c2.last_review).total_seconds() / 86400
        assert 10 <= interval_2 <= 20
        c3, _ = SCHEDULER.review_card(
            c2, Rating.Good, review_datetime=now + timedelta(days=17)
        )
        interval_3 = (c3.due - c3.last_review).total_seconds() / 86400
        assert interval_3 > interval_2
        # A lapse (Again on Review-state card) collapses the interval
        # (no relearning steps configured: 3-day relearn gap, per FSRS-6).
        c4, _ = SCHEDULER.review_card(
            c3, Rating.Again, review_datetime=now + timedelta(days=57)
        )
        interval_4 = (c4.due - c4.last_review).total_seconds() / 86400
        assert interval_4 < interval_3 / 5

    def test_fsrs_version_recorded(self) -> None:
        assert FSRS_VERSION.startswith("fsrs6-py-")


@requires_db
class TestReviewFlow:
    def _setup(
        self, client: TestClient
    ) -> tuple[str, TestClient, str, str, str]:
        email = _email()
        _make_teacher(email)
        c = TestClient(client.app)
        _login(c, email)
        student = c.post(
            "/api/v1/students", json={"display_name": "Review Me"}
        ).json()["id"]
        sense_id = None
        from app.db.session import get_engine

        with get_engine().begin() as conn:
            sense_id = str(
                conn.execute(
                    text(
                        "SELECT id FROM vocabulary_senses WHERE is_active "
                        "AND headword_normalized != '' "
                        "ORDER BY headword_normalized LIMIT 1"
                    )
                ).scalar_one()
            )
            aid = str(uuid.uuid4())
            conn.execute(
                text(
                    "INSERT INTO student_vocabulary "
                    "(id, student_id, sense_id, learning_state, is_active) "
                    "VALUES (:id, CAST(:sid AS uuid), CAST(:seid AS uuid), "
                    "'ASSIGNED', true)"
                ),
                {"id": aid, "sid": student, "seid": sense_id},
            )
        return email, c, student, aid, sense_id

    def test_due_queue_orders_and_review_moves_state(
        self, client: TestClient
    ) -> None:
        email, c, student, aid, _sense = self._setup(client)
        try:
            # New (never reviewed) assignments appear in the queue.
            queue = c.get(
                "/api/v1/reviews/due", params={"student_id": student}
            ).json()
            assert queue["total"] == 1
            item = queue["items"][0]
            assert item["assignment_id"] == aid
            assert item["is_overdue"] is None  # new card: not "overdue"
            assert item["sense"]["headword"]

            # HARD -> Again: still learning-ish, gets a short interval.
            r = c.post(
                "/api/v1/reviews",
                json={
                    "student_id": student,
                    "assignment_id": aid,
                    "rating": "HARD",
                },
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["rating"] == "HARD"
            assert body["fsrs_grade"] == 1  # Again
            assert body["learning_state"] == "LEARNING"  # struggled
            due_at = datetime.fromisoformat(body["due_at"])
            days = (due_at - datetime.now(UTC)).total_seconds() / 86400
            # Again with learning steps disabled -> ~1 day relearn interval.
            assert 0 <= days <= 1.5

            # MEDIUM -> Hard grade 2; remembered (not NEW/LEARNING any more).
            r2 = c.post(
                "/api/v1/reviews",
                json={
                    "student_id": student,
                    "assignment_id": aid,
                    "rating": "MEDIUM",
                },
            ).json()
            assert r2["fsrs_grade"] == 2
            assert r2["learning_state"] == "REVIEWING"

            # EASY -> Good grade 3; interval now much longer.
            r3 = c.post(
                "/api/v1/reviews",
                json={
                    "student_id": student,
                    "assignment_id": aid,
                    "rating": "EASY",
                },
            ).json()
            assert r3["fsrs_grade"] == 3
            assert r3["repetitions"] == 3
            assert r3["lapses"] == 0
            assert r3["learning_state"] == "REVIEWING"
            due3 = datetime.fromisoformat(r3["due_at"])
            # After an Again-heavy start, stability is still low (~1 day);
            # interval growth itself is proven by the fixtures test above.
            assert (due3 - datetime.now(UTC)).total_seconds() / 86400 >= 0.5

            # The student profile reflects the updated state + due date.
            vocab = c.get(f"/api/v1/students/{student}/vocabulary").json()
            entry = next(i for i in vocab["items"] if i["id"] == aid)
            assert entry["learning_state"] == r3["learning_state"]
            # Same instant; PG returns +05:00 local, FSRS string is UTC.
            assert datetime.fromisoformat(entry["due_at"]) == datetime.fromisoformat(
                r3["due_at"]
            )

            # §33: three immutable events, ordered, each with both states.
            from app.db.session import get_engine

            with get_engine().connect() as conn:
                events = conn.execute(
                    text(
                        "SELECT rating, fsrs_grade, previous_state_json, "
                        "new_state_json, previous_due_at, new_due_at "
                        "FROM review_events "
                        "WHERE student_vocabulary_id = CAST(:sv AS uuid) "
                        "ORDER BY reviewed_at"
                    ),
                    {"sv": aid},
                ).mappings().all()
            assert len(events) == 3
            assert [int(e["fsrs_grade"]) for e in events] == [1, 2, 3]
            first, second, third = events
            assert first["previous_state_json"] is None  # brand-new card
            assert second["previous_state_json"] == first["new_state_json"]
            assert third["previous_state_json"] == second["new_state_json"]
            assert third["new_due_at"] is not None
        finally:
            _drop_teacher(email)

    def test_queue_hides_until_due(self, client: TestClient) -> None:
        email, c, student, aid, _sense = self._setup(client)
        try:
            # EASY schedules ~2+ days out; the card should leave the queue.
            c.post(
                "/api/v1/reviews",
                json={
                    "student_id": student,
                    "assignment_id": aid,
                    "rating": "EASY",
                },
            )
            queue = c.get(
                "/api/v1/reviews/due", params={"student_id": student}
            ).json()
            assert queue["total"] == 0
            # ...but reappears when include_new=false is irrelevant here and
            # the future-due card is excluded even with include_new=true.
            assert all(i["assignment_id"] != aid for i in queue["items"])
        finally:
            _drop_teacher(email)

    def test_queue_narrowing_and_reset(self, client: TestClient) -> None:
        """§36 selection filters and §38 review-state reset/adjust."""
        email, c, student, aid, _sense = self._setup(client)
        try:
            base = {"student_id": student}
            assert c.get("/api/v1/reviews/due", params=base).json()["total"] == 1

            # §36: learning-state scope.
            assert (
                c.get(
                    "/api/v1/reviews/due",
                    params={**base, "learning_states": "ASSIGNED"},
                ).json()["total"]
                == 1
            )
            assert (
                c.get(
                    "/api/v1/reviews/due",
                    params={**base, "learning_states": "MASTERED"},
                ).json()["total"]
                == 0
            )

            # §36: explicit assignment selection.
            assert (
                c.get(
                    "/api/v1/reviews/due", params={**base, "assignment_ids": aid}
                ).json()["total"]
                == 1
            )
            assert (
                c.get(
                    "/api/v1/reviews/due",
                    params={**base, "assignment_ids": str(uuid.uuid4())},
                ).json()["total"]
                == 0
            )

            # §36: headword search substring.
            headword = c.get("/api/v1/reviews/due", params=base).json()["items"][0][
                "sense"
            ]["headword"]
            assert (
                c.get(
                    "/api/v1/reviews/due", params={**base, "search": headword[:3]}
                ).json()["total"]
                >= 1
            )
            assert (
                c.get(
                    "/api/v1/reviews/due", params={**base, "search": "zzzzzz"}
                ).json()["total"]
                == 0
            )

            # §36: a new card is not "difficult" (no lapses yet).
            assert (
                c.get(
                    "/api/v1/reviews/due", params={**base, "difficult_only": "true"}
                ).json()["total"]
                == 0
            )

            # Record a review, then §38 adjust its due date into the past.
            c.post(
                "/api/v1/reviews",
                json={"student_id": student, "assignment_id": aid, "rating": "EASY"},
            )
            past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            patch = c.patch(
                f"/api/v1/assignments/{aid}",
                params=base,
                json={"due_at": past},
            )
            assert patch.status_code == 200, patch.text
            due = c.get("/api/v1/reviews/due", params=base).json()
            assert due["total"] == 1
            assert due["items"][0]["is_overdue"] is True

            # §38 reset: FSRS card cleared, §33 review history retained.
            reset = c.patch(
                f"/api/v1/assignments/{aid}",
                params=base,
                json={"reset_review": True},
            )
            assert reset.status_code == 200, reset.text
            from app.db.session import get_engine

            with get_engine().connect() as conn:
                fsrs_rows = conn.execute(
                    text(
                        "SELECT count(*) FROM student_fsrs_states "
                        "WHERE student_vocabulary_id = CAST(:a AS uuid)"
                    ),
                    {"a": aid},
                ).scalar()
                events = conn.execute(
                    text(
                        "SELECT count(*) FROM review_events "
                        "WHERE student_vocabulary_id = CAST(:a AS uuid)"
                    ),
                    {"a": aid},
                ).scalar()
            assert fsrs_rows == 0
            assert events == 1  # immutable history is never reset
            after = c.get("/api/v1/reviews/due", params=base).json()
            assert after["total"] == 1
            assert after["items"][0]["is_overdue"] is None  # new again
        finally:
            _drop_teacher(email)

    def test_validation_and_isolation(self, client: TestClient) -> None:
        email, c, student, aid, _sense = self._setup(client)
        try:
            bad_rating = c.post(
                "/api/v1/reviews",
                json={
                    "student_id": student,
                    "assignment_id": aid,
                    "rating": "PERFECT",
                },
            )
            assert bad_rating.status_code == 422

            unknown = c.post(
                "/api/v1/reviews",
                json={
                    "student_id": student,
                    "assignment_id": str(uuid.uuid4()),
                    "rating": "EASY",
                },
            )
            assert unknown.status_code == 404

            # Another teacher's student is invisible end to end.
            other_email = _email()
            _make_teacher(other_email)
            try:
                c2 = TestClient(client.app)
                _login(c2, other_email)
                foreign = c2.get(
                    "/api/v1/reviews/due", params={"student_id": student}
                )
                assert foreign.status_code == 404
            finally:
                _drop_teacher(other_email)

            # FSRS parameters endpoint is real and deterministic.
            params = c.get("/api/v1/fsrs/parameters").json()
            assert params["enable_fuzzing"] is False
            assert params["rating_mapping"]["HARD"] == "Again(1)"
        finally:
            _drop_teacher(email)
