"""Review service (Phase 20, sections 31-33): FSRS scheduling.

Library-backed (py-fsrs 6, FSRS-6 model) with deterministic settings
(fuzzing off — §31 requires deterministic, documentable transitions).
The FSRS card is stored as JSON on student_fsrs_states; every review
writes an immutable review_events row (§33) with enough state to
reconstruct what happened, then derives the §31 learning state from
the FSRS state deterministically:

    new/unreviewed            -> NEW
    FSRS Learning (state 1)   -> LEARNING
    FSRS Relearning (state 3) -> REVIEWING (lapsed, back in rotation)
    FSRS Review + lapses == 0 -> ASSIGNED (scheduled, never seen in review)
    FSRS Review + lapses > 0  -> REVIEWING

Teacher ratings map exactly as specified (§6): HARD->Again(1),
MEDIUM->Hard(2), EASY->Good(3). Rating.Easy(4) is never produced from
the three-button UI.

Learning-state derivation (§31, deterministic — py-fsrs 6 with
learning steps disabled graduates straight to the Review state, so
FSRS state alone cannot express "struggled"; the last rating can):

    never reviewed              -> NEW
    last rating == HARD (Again) -> LEARNING   (struggling, short interval)
    first review, else          -> ENCOUNTERED (seen once, scheduled)
    later non-HARD reviews      -> REVIEWING  (in the review rotation)
    MASTERED                    -> teacher override only (explicit PATCH)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fsrs import Card, Rating, Scheduler
from sqlalchemy import text

from app.core.errors import NotFoundError, ValidationError
from app.core.students import _get_scoped

FSRS_VERSION = "fsrs6-py-6.3.2"
SCHEDULER = Scheduler(enable_fuzzing=False, learning_steps=(), relearning_steps=())

TEACHER_TO_FSRS: dict[str, Rating] = {
    "HARD": Rating.Again,
    "MEDIUM": Rating.Hard,
    "EASY": Rating.Good,
}

# FSRS card state enum values (py-fsrs State).
FSRS_LEARNING, FSRS_REVIEW, FSRS_RELEARNING = 1, 2, 3


def derive_learning_state(
    card: Card,
    *,
    has_been_reviewed: bool,
    assignment_active: bool,
    last_rating: Rating,
    repetitions: int,
) -> str:
    """Deterministic §31 mapping to the learning state (see module doc)."""
    if not assignment_active or not has_been_reviewed:
        return "NEW"
    if last_rating == Rating.Again:
        return "LEARNING"
    if repetitions <= 1:
        return "ENCOUNTERED"
    return "REVIEWING"


def _load_card(state_json: str | None) -> Card | None:
    if not state_json:
        return None
    return Card.from_json(state_json)


def review_assignment(
    conn: Any,
    teacher_id: uuid.UUID,
    student_id: str,
    assignment_id: str,
    rating: str,
    *,
    reviewed_at: datetime | None = None,
) -> dict[str, Any]:
    """Record one review: FSRS update + immutable event + state move (§32).

    Idempotent at the transport level is NOT desired (each POST is a real
    review), but double-submission of the same review is detected by the
    client guard; the DB accepts sequential reviews.
    """
    rating_u = (rating or "").strip().upper()
    if rating_u not in TEACHER_TO_FSRS:
        raise ValidationError(
            "Rating must be one of HARD, MEDIUM, EASY."
        )
    fsrs_rating = TEACHER_TO_FSRS[rating_u]
    sid = str(_get_scoped(conn, teacher_id, student_id)["id"])
    try:
        aid = str(uuid.UUID(assignment_id))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError("No such assignment.") from exc

    row = (
        conn.execute(
            text(
                "SELECT sv.id, sv.learning_state, sv.is_active, "
                "sv.sense_id, fs.id AS fsrs_id, fs.state_json, "
                "fs.stability, fs.difficulty, fs.repetitions, fs.lapses, "
                "fs.due_at, fs.last_review_at, fs.fsrs_version "
                "FROM student_vocabulary sv "
                "LEFT JOIN student_fsrs_states fs "
                " ON fs.student_vocabulary_id = sv.id "
                "WHERE sv.id = CAST(:aid AS uuid) "
                "AND sv.student_id = CAST(:sid AS uuid)"
            ),
            {"aid": aid, "sid": sid},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFoundError("No such assignment.")
    if not row["is_active"]:
        raise ValidationError("This assignment is inactive (unassigned).")

    when = reviewed_at or datetime.now(UTC)
    previous_card = _load_card(row["state_json"])

    card = previous_card or Card()
    new_card, _log = SCHEDULER.review_card(
        card, fsrs_rating, review_datetime=when
    )
    new_state_json = new_card.to_json()

    # py-fsrs 6 cards do not carry repetition counters; derive them from
    # the immutable review history (§33): reps = events, lapses = Again
    # ratings that hit a card in the Review state (a true lapse).
    # fsrs_grade is a varchar enum: values are stored as names (AGAIN...).
    prior = conn.execute(
        text(
            "SELECT count(*) AS reps, "
            "count(*) FILTER (WHERE fsrs_grade = 'AGAIN' AND previous_state_json "
            "  IS NOT NULL "
            "  AND (previous_state_json::jsonb->>'state')::int = 2) "
            "  AS lapses "
            "FROM review_events WHERE student_vocabulary_id = CAST(:sv AS uuid)"
        ),
        {"sv": aid},
    ).mappings().first()
    reps = (prior["reps"] or 0) + 1
    was_lapse = (
        fsrs_rating == Rating.Again
        and previous_card is not None
        and previous_card.state == FSRS_REVIEW
    )
    lapses = (prior["lapses"] or 0) + (1 if was_lapse else 0)

    learning_state = derive_learning_state(
        new_card,
        has_been_reviewed=True,
        assignment_active=True,
        last_rating=fsrs_rating,
        repetitions=reps,
    )

    # Upsert FSRS state (§31/§35: due queue reads this table).
    conn.execute(
        text(
            "INSERT INTO student_fsrs_states "
            "(id, student_vocabulary_id, stability, difficulty, repetitions, "
            " lapses, last_review_at, due_at, fsrs_version, state_json) "
            "VALUES (:id, CAST(:sv AS uuid), :st, :df, :rep, :lap, "
            " :last, :due, :ver, CAST(:sjson AS jsonb)) "
            "ON CONFLICT (student_vocabulary_id) DO UPDATE SET "
            " stability = :st, difficulty = :df, repetitions = :rep, "
            " lapses = :lap, last_review_at = :last, due_at = :due, "
            " fsrs_version = :ver, state_json = CAST(:sjson AS jsonb)"
        ),
        {
            "id": row["fsrs_id"] or uuid.uuid4(),
            "sv": aid,
            "st": new_card.stability,
            "df": new_card.difficulty,
            "rep": reps,
            "lap": lapses,
            "last": new_card.last_review,
            "due": new_card.due,
            "ver": FSRS_VERSION,
            "sjson": new_state_json,
        },
    )

    # Immutable history (§33): previous + new state, never overwritten.
    conn.execute(
        text(
            "INSERT INTO review_events "
            "(id, student_vocabulary_id, student_id, sense_id, teacher_id, "
            " rating, fsrs_grade, previous_state_json, new_state_json, "
            " previous_due_at, new_due_at, reviewed_at) "
            "VALUES (:id, CAST(:sv AS uuid), CAST(:sid AS uuid), "
            " CAST(:seid AS uuid), CAST(:tid AS uuid), :rating, :grade, "
            " CAST(:pjson AS jsonb), CAST(:njson AS jsonb), :pdue, :ndue, :at)"
        ),
        {
            "id": uuid.uuid4(),
            "sv": aid,
            "sid": sid,
            "seid": str(row["sense_id"]),
            "tid": str(teacher_id),
            "rating": rating_u,
            "grade": fsrs_rating.value,
            "pjson": row["state_json"],
            "njson": new_state_json,
            "pdue": row["due_at"],
            "ndue": new_card.due,
            "at": when,
        },
    )

    conn.execute(
        text(
            "UPDATE student_vocabulary SET learning_state = :ls, updated_at = now() "
            "WHERE id = CAST(:aid AS uuid)"
        ),
        {"ls": learning_state, "aid": aid},
    )

    return {
        "assignment_id": aid,
        "rating": rating_u,
        "fsrs_grade": fsrs_rating.value,
        "learning_state": learning_state,
        "stability": new_card.stability,
        "difficulty": new_card.difficulty,
        "repetitions": reps,
        "lapses": lapses,
        "due_at": new_card.due.isoformat(),
        "reviewed_at": when.isoformat(),
    }


def due_queue(
    conn: Any,
    teacher_id: uuid.UUID,
    student_id: str,
    *,
    limit: int = 50,
    include_new: bool = True,
) -> dict[str, Any]:
    """What to review next (§32/§35): overdue first, then due, then new.

    Overdue = due_at < now; due = now <= due_at <= end of today; new =
    assigned but never reviewed (no FSRS row). Ordered so the teacher
    sees the most-urgent cards first; deterministic within ties.
    """
    sid = str(_get_scoped(conn, teacher_id, student_id)["id"])
    # include_new adds never-reviewed rows to the queue; the OR lives
    # INSIDE the parenthesized due-condition (an outside OR would match
    # every unreviewed row in the database).
    new_branch = (
        " OR fs.student_vocabulary_id IS NULL" if include_new else ""
    )
    rows = conn.execute(
        text(
            "SELECT sv.id AS assignment_id, sv.learning_state, "
            "fs.due_at, fs.repetitions, fs.lapses, fs.last_review_at, "
            "vs.id AS sense_id, vs.headword, vs.part_of_speech, vs.cefr_level, "
            "vs.definition_preview, "
            "(SELECT st.translation FROM sense_translations st "
            " WHERE st.sense_id = vs.id ORDER BY st.position LIMIT 1) "
            "AS translation_pl, "
            "(SELECT se.example FROM sense_examples se "
            " WHERE se.sense_id = vs.id ORDER BY se.position LIMIT 1) "
            "AS example, "
            "CASE "
            " WHEN fs.student_vocabulary_id IS NULL THEN 2 "  # new last
            " WHEN fs.due_at < now() THEN 0 "  # overdue first
            " ELSE 1 "
            "END AS bucket, "
            "CASE WHEN fs.student_vocabulary_id IS NULL THEN NULL "
            " ELSE fs.due_at < now() END AS is_overdue "
            "FROM student_vocabulary sv "
            "JOIN vocabulary_senses vs ON vs.id = sv.sense_id "
            "LEFT JOIN student_fsrs_states fs "
            " ON fs.student_vocabulary_id = sv.id "
            "WHERE sv.student_id = CAST(:sid AS uuid) AND sv.is_active "
            "AND (fs.student_vocabulary_id IS NULL"
            + new_branch
            + " OR fs.due_at <= date_trunc('day', now()) "
            "        + interval '1 day' - interval '1 microsecond')"
            + " ORDER BY bucket, fs.due_at NULLS LAST, vs.headword, sv.id "
            "LIMIT :lim"
        ),
        {"sid": sid, "lim": limit},
    ).mappings().all()
    items = [
        {
            "assignment_id": str(r["assignment_id"]),
            "learning_state": r["learning_state"],
            "is_overdue": r["is_overdue"],
            "due_at": r["due_at"].isoformat() if r["due_at"] else None,
            "repetitions": r["repetitions"],
            "lapses": r["lapses"],
            "last_review_at": r["last_review_at"].isoformat()
            if r["last_review_at"]
            else None,
            "sense": {
                "id": str(r["sense_id"]),
                "headword": r["headword"],
                "part_of_speech": r["part_of_speech"],
                "cefr_level": r["cefr_level"],
                "definition_preview": r["definition_preview"],
                "translation_pl": r["translation_pl"],
                "example": r["example"],
            },
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}
