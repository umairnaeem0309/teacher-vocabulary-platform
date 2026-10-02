"""Seed the teacher account and fixtures used by the Playwright acceptance tests.

Creates (or reuses) a dedicated acceptance teacher, resets that teacher's
data so every end-to-end run starts from a known state, and seeds a student
**John** who already has assigned vocabulary with FSRS state that is genuinely
overdue. That matters for §59: step 8 selects an existing student, step 14
filters DUE (needs real due rows), and steps 21-22 verify the due counts
change after a review.

Credentials come from ``E2E_TEACHER_EMAIL`` / ``E2E_TEACHER_PASSWORD`` and
print as JSON on stdout for the Playwright global setup.

    cd backend
    PYTHONPATH=.. PYTHONIOENCODING=utf-8 uv run python ../scripts/phase27_seed_acceptance.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fsrs import Card, Rating  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core import auth as auth_core  # noqa: E402
from app.core.reviews import FSRS_VERSION, SCHEDULER  # noqa: E402

EMAIL = os.environ.get("E2E_TEACHER_EMAIL", "acceptance@example.com")
PASSWORD = os.environ.get("E2E_TEACHER_PASSWORD", "acceptance-teacher-Passw0rd!")
JOHN = "John"
OVERDUE_CARDS = 6
OVERDUE_DAYS = 3

# Rows owned by the acceptance teacher, in dependency order.
RESET_TABLES = (
    "review_events WHERE student_vocabulary_id IN "
    "(SELECT id FROM student_vocabulary WHERE student_id IN "
    "(SELECT id FROM students WHERE teacher_id = :tid))",
    "student_fsrs_states WHERE student_vocabulary_id IN "
    "(SELECT id FROM student_vocabulary WHERE student_id IN "
    "(SELECT id FROM students WHERE teacher_id = :tid))",
    "teacher_priority_overrides WHERE student_id IN "
    "(SELECT id FROM students WHERE teacher_id = :tid)",
    "student_vocabulary WHERE student_id IN "
    "(SELECT id FROM students WHERE teacher_id = :tid)",
    "vocabulary_set_items WHERE set_id IN "
    "(SELECT id FROM vocabulary_sets WHERE teacher_id = :tid)",
    "vocabulary_sets WHERE teacher_id = :tid",
    "students WHERE teacher_id = :tid",
    "teacher_sessions WHERE teacher_id = :tid",
)


def _overdue_card() -> tuple[Card, datetime, datetime, int, int]:
    """A reviewed FSRS card whose next review date is in the past.

    py-fsrs 6 cards carry no repetition counters (the app derives them from
    the immutable review history), so reps/lapses are returned separately
    and stored denormalized for the due-queue scan.
    """
    card = Card()
    card, _ = SCHEDULER.review_card(card, Rating.Hard)
    card, _ = SCHEDULER.review_card(card, Rating.Good)
    now = datetime.now(UTC)
    card.last_review = now - timedelta(days=OVERDUE_DAYS + 7)
    card.due = now - timedelta(days=OVERDUE_DAYS)
    return card, card.due, card.last_review, 2, 0


def _seed_john(conn, teacher_id: uuid.UUID) -> tuple[str, int]:
    """Create student John with OVERDUE_CARDS reviewed, overdue senses."""
    sense_ids = [
        str(r)
        for r in conn.execute(
            text(
                "SELECT id FROM vocabulary_senses WHERE is_active "
                "ORDER BY priority_score DESC NULLS LAST, headword_normalized "
                "LIMIT :n"
            ),
            {"n": OVERDUE_CARDS},
        ).scalars()
    ]
    if not sense_ids:
        raise SystemExit("no active senses to seed for John")

    john_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO students (id, teacher_id, display_name, email, status) "
            "VALUES (:id, :tid, :name, NULL, 'ACTIVE')"
        ),
        {"id": john_id, "tid": teacher_id, "name": JOHN},
    )

    for sense_id in sense_ids:
        sv_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO student_vocabulary "
                "(id, student_id, sense_id, learning_state, is_active) "
                "VALUES (:sv, :john, :sense, 'REVIEWING', true)"
            ),
            {"sv": sv_id, "john": john_id, "sense": sense_id},
        )
        card, due, last_review, reps, lapses = _overdue_card()
        conn.execute(
            text(
                "INSERT INTO student_fsrs_states "
                "(id, student_vocabulary_id, stability, difficulty, repetitions, "
                " lapses, last_review_at, due_at, fsrs_version, state_json) "
                "VALUES (:id, CAST(:sv AS uuid), :st, :df, :rep, :lap, "
                " :last, :due, :ver, CAST(:sjson AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "sv": sv_id,
                "st": card.stability,
                "df": card.difficulty,
                "rep": reps,
                "lap": lapses,
                "last": last_review,
                "due": due,
                "ver": FSRS_VERSION,
                "sjson": card.to_json(),
            },
        )
    return str(john_id), len(sense_ids)


def main() -> int:
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        row = conn.execute(
            text("SELECT id FROM teachers WHERE email = :email"),
            {"email": EMAIL},
        ).scalar()
        if row is None:
            tid: uuid.UUID = uuid.uuid4()
            created = True
            conn.execute(
                text(
                    "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                    "VALUES (:id, :email, :ph, 'Acceptance Teacher', true)"
                ),
                {"id": tid, "email": EMAIL, "ph": auth_core.hash_password(PASSWORD)},
            )
        else:
            tid = row
            created = False
            conn.execute(
                text(
                    "UPDATE teachers SET is_active = true, password_hash = :ph "
                    "WHERE id = :tid"
                ),
                {"tid": tid, "ph": auth_core.hash_password(PASSWORD)},
            )

        # Clean slate for a deterministic acceptance run.
        for clause in RESET_TABLES:
            conn.execute(text(f"DELETE FROM {clause}"), {"tid": tid})

        john_id, seeded = _seed_john(conn, tid)

        # Mint the suite's shared browser session right here, server-side:
        # the Playwright global setup turns it into storage state, so only
        # §59's "login as teacher" step spends a real HTTP login. That keeps
        # every run inside the §39 rate limit (10 logins / 5 minutes / IP).
        token = auth_core.new_session_token()
        auth_core.create_session(conn, tid, token)

    print(
        json.dumps(
            {
                "teacher_id": str(tid),
                "email": EMAIL,
                "password": PASSWORD,
                "created": created,
                "john_student_id": john_id,
                "john_overdue_cards": seeded,
                "session_token": token,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
