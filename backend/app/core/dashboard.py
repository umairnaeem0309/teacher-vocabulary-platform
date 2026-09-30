"""Dashboard service (Phase 21, section 36): practical, not analytics.

For one student, answers the dashboard's primary question — "What should
I review with this student next?" — and reports the working counts the
teacher needs (§36): assigned, learning, reviewing, mastered, due,
overdue, difficult, recent reviews. No business-intelligence features.

Definitions (consistent with the Phase 20 due queue):
- assigned  active vocabulary rows (the student's working deck)
- learning  learning_state == LEARNING (struggled: last rating was HARD)
- reviewing learning_state == REVIEWING (in the review rotation)
- mastered  learning_state == MASTERED (teacher override only)
- due       FSRS due_at within today (inclusive of now)
- overdue   FSRS due_at before now
- difficult most frequent HARD ratings in the last 30 days (top 5,
  deterministic ties by headword then id)
- next_up   the first card of the §32 due queue (overdue first, then due
  today, then new) — exactly what POST /reviews/due returns first
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from app.core.students import _get_scoped

RECENT_WINDOW_DAYS = 30
DIFFICULT_LIMIT = 5
RECENT_REVIEWS_LIMIT = 10
NEXT_UP_LIMIT = 1


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def student_dashboard(
    conn: Any,
    teacher_id: uuid.UUID,
    student_id: str,
) -> dict[str, Any]:
    """Per-student dashboard payload (§36). 404 unless owned (§40)."""
    student = _get_scoped(conn, teacher_id, student_id)

    counts = _counts(conn, student["id"])
    next_up = _next_up(conn, student["id"])
    difficult = _difficult(conn, student["id"])
    recent = _recent_reviews(conn, student["id"])

    return {
        "student": {
            "id": str(student["id"]),
            "display_name": student["display_name"],
            "status": student["status"],
        },
        "counts": counts,
        "next_up": next_up,
        "difficult": difficult,
        "recent_reviews": recent,
    }


def _counts(conn: Any, sid: uuid.UUID) -> dict[str, int]:
    """Working counts over the active deck (§36; no analytics)."""
    row = (
        conn.execute(
            text(
                "SELECT COUNT(*) AS assigned, "
                "COUNT(*) FILTER (WHERE sv.learning_state = 'LEARNING') AS learning, "
                "COUNT(*) FILTER (WHERE sv.learning_state = 'REVIEWING') AS reviewing, "
                "COUNT(*) FILTER (WHERE sv.learning_state = 'MASTERED') AS mastered, "
                "COUNT(*) FILTER (WHERE fs.student_vocabulary_id IS NOT NULL "
                " AND fs.due_at < now()) AS overdue, "
                "COUNT(*) FILTER (WHERE fs.student_vocabulary_id IS NOT NULL "
                " AND fs.due_at >= now() "
                " AND fs.due_at <= date_trunc('day', now()) "
                "    + interval '1 day' - interval '1 microsecond') AS due "
                "FROM student_vocabulary sv "
                "LEFT JOIN student_fsrs_states fs "
                " ON fs.student_vocabulary_id = sv.id "
                "WHERE sv.student_id = CAST(:sid AS uuid) AND sv.is_active"
            ),
            {"sid": str(sid)},
        )
        .mappings()
        .one()
    )
    return {
        "assigned": int(row["assigned"]),
        "learning": int(row["learning"]),
        "reviewing": int(row["reviewing"]),
        "mastered": int(row["mastered"]),
        "due": int(row["due"]),
        "overdue": int(row["overdue"]),
    }


def _next_up(conn: Any, sid: uuid.UUID) -> dict[str, Any] | None:
    """§36 primary question: the first card of the §32 due queue (no auth
    checks — the caller already scoped the student)."""
    from app.core.reviews import _due_rows

    rows = _due_rows(conn, str(sid), limit=NEXT_UP_LIMIT)
    for r in rows:
        return {
            "assignment_id": str(r["assignment_id"]),
            "learning_state": r["learning_state"],
            "is_overdue": r["is_overdue"],
            "due_at": _iso(r["due_at"]),
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
    return None


def _difficult(
    conn: Any,
    sid: uuid.UUID,
    *,
    limit: int = DIFFICULT_LIMIT,
    days: int = RECENT_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Most-struggled vocabulary: HARD ratings in the last `days` days."""
    rows = (
        conn.execute(
            text(
                "SELECT sv.id AS assignment_id, vs.id AS sense_id, vs.headword, "
                "vs.part_of_speech, vs.cefr_level, "
                "COUNT(*) FILTER (WHERE re.rating = 'HARD') AS hard_count, "
                "COUNT(*) AS total_reviews "
                "FROM review_events re "
                "JOIN student_vocabulary sv ON sv.id = re.student_vocabulary_id "
                "JOIN vocabulary_senses vs ON vs.id = sv.sense_id "
                "WHERE re.student_id = CAST(:sid AS uuid) "
                "AND re.reviewed_at >= now() - CAST(:days AS int) * interval '1 day' "
                "GROUP BY sv.id, vs.id, vs.headword, vs.part_of_speech, vs.cefr_level "
                "HAVING COUNT(*) FILTER (WHERE re.rating = 'HARD') > 0 "
                "ORDER BY hard_count DESC, vs.headword, sv.id "
                "LIMIT :lim"
            ),
            {"sid": str(sid), "days": days, "lim": limit},
        )
        .mappings()
        .all()
    )
    return [
        {
            "assignment_id": str(r["assignment_id"]),
            "sense_id": str(r["sense_id"]),
            "headword": r["headword"],
            "part_of_speech": r["part_of_speech"],
            "cefr_level": r["cefr_level"],
            "hard_count": int(r["hard_count"]),
            "total_reviews": int(r["total_reviews"]),
        }
        for r in rows
    ]


def _recent_reviews(
    conn: Any,
    sid: uuid.UUID,
    *,
    limit: int = RECENT_REVIEWS_LIMIT,
) -> list[dict[str, Any]]:
    """Latest review activity (§36), most recent first."""
    rows = (
        conn.execute(
            text(
                "SELECT re.rating, re.reviewed_at, re.new_due_at, "
                "vs.headword, vs.part_of_speech "
                "FROM review_events re "
                "JOIN vocabulary_senses vs ON vs.id = re.sense_id "
                "WHERE re.student_id = CAST(:sid AS uuid) "
                "ORDER BY re.reviewed_at DESC, re.id "
                "LIMIT :lim"
            ),
            {"sid": str(sid), "lim": limit},
        )
        .mappings()
        .all()
    )
    return [
        {
            "rating": r["rating"],
            "reviewed_at": _iso(r["reviewed_at"]),
            "new_due_at": _iso(r["new_due_at"]),
            "headword": r["headword"],
            "part_of_speech": r["part_of_speech"],
        }
        for r in rows
    ]


def overview(
    conn: Any,
    teacher_id: uuid.UUID,
    *,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """All-students rollup for /dashboard (§98): one row per student with
    the §36 working counts, plus totals. Students with no active deck
    still appear (assigned=0) so the list doubles as a roster view;
    ordering is by overdue DESC, due DESC, then name — the students who
    need attention first sort to the top."""
    rows = (
        conn.execute(
            text(
                "SELECT s.id, s.display_name, s.status, "
                "COUNT(sv.id) AS assigned, "
                "COUNT(*) FILTER (WHERE sv.learning_state = 'LEARNING') AS learning, "
                "COUNT(*) FILTER (WHERE sv.learning_state = 'REVIEWING') AS reviewing, "
                "COUNT(*) FILTER (WHERE sv.learning_state = 'MASTERED') AS mastered, "
                "COUNT(*) FILTER (WHERE fs.student_vocabulary_id IS NOT NULL "
                " AND fs.due_at < now()) AS overdue, "
                "COUNT(*) FILTER (WHERE fs.student_vocabulary_id IS NOT NULL "
                " AND fs.due_at >= now() "
                " AND fs.due_at <= date_trunc('day', now()) "
                "    + interval '1 day' - interval '1 microsecond') AS due "
                "FROM students s "
                "LEFT JOIN student_vocabulary sv "
                " ON sv.student_id = s.id AND sv.is_active "
                "LEFT JOIN student_fsrs_states fs "
                " ON fs.student_vocabulary_id = sv.id "
                "WHERE s.teacher_id = CAST(:tid AS uuid) "
                "AND s.status != 'DELETED'"
                + ("" if include_inactive else " AND s.status = 'ACTIVE' ")
                + "GROUP BY s.id, s.display_name, s.status "
                "ORDER BY overdue DESC, due DESC, s.display_name, s.id"
            ),
            {"tid": str(teacher_id)},
        )
        .mappings()
        .all()
    )
    students: list[dict[str, Any]] = [
        {
            "student": {
                "id": str(r["id"]),
                "display_name": r["display_name"],
                "status": r["status"],
            },
            "assigned": int(r["assigned"]),
            "learning": int(r["learning"]),
            "reviewing": int(r["reviewing"]),
            "mastered": int(r["mastered"]),
            "due": int(r["due"]),
            "overdue": int(r["overdue"]),
        }
        for r in rows
    ]
    count_keys = ("assigned", "learning", "reviewing", "mastered", "due", "overdue")
    totals = {
        key: sum(int(s[key]) for s in students) for key in count_keys
    }
    return {"students": students, "total": len(students), "totals": totals}
