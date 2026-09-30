"""Student management service (Phase 17, section 27).

All §27 operations with §40 authorization baked in: every query is
scoped to the owning teacher, so a valid session can never read or
mutate another teacher's students. Soft lifecycle per §27: deactivate
and reactivate flip ``status``; delete is a soft delete (DELETED) —
historical learning records are never destroyed (§27 hard rule).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import text

from app.core.errors import ConflictError, NotFoundError, ValidationError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_student_input(
    display_name: str | None,
    email: str | None,
    notes: str | None,
) -> None:
    """§40 valid-input gate for create/edit payloads."""
    if display_name is None or not display_name.strip() or len(display_name) > 200:
        raise ValidationError("A display name (1-200 characters) is required.")
    if email is not None and email.strip() and (
        len(email) > 320 or not _EMAIL_RE.match(email.strip())
    ):
        raise ValidationError("A valid email address is required.")
    if notes is not None and len(notes) > 10_000:
        raise ValidationError("Notes must be at most 10,000 characters.")


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "display_name": row["display_name"],
        "email": row["email"],
        "notes": row["notes"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "assigned_count": row["assigned_count"],
    }


_LIST_SQL = """
SELECT s.id, s.display_name, s.email, s.notes, s.status,
       s.created_at, s.updated_at,
       (SELECT count(*) FROM student_vocabulary sv
         WHERE sv.student_id = s.id AND sv.is_active) AS assigned_count
FROM students s
WHERE s.teacher_id = CAST(:tid AS uuid) AND s.status != 'DELETED'
"""


def list_students(
    conn: Any, teacher_id: uuid.UUID, include_inactive: bool = False
) -> list[dict[str, Any]]:
    """The teacher's students (§27 open profile list), youngest last."""
    sql = _LIST_SQL
    if not include_inactive:
        sql += " AND s.status = 'ACTIVE'"
    sql += " ORDER BY s.display_name, s.id"
    rows = conn.execute(text(sql), {"tid": str(teacher_id)}).mappings().all()
    return [_row_to_dict(r) for r in rows]


def _get_scoped(
    conn: Any, teacher_id: uuid.UUID, student_id: str, *, include_deleted: bool = False
) -> Any:
    """Fetch one student, 404 unless it exists AND belongs to the teacher.

    The scope check is in the WHERE clause (§40: never trust student_id) —
    a foreign id and a nonexistent id are indistinguishable to the caller.
    Soft-deleted rows are hidden unless ``include_deleted`` (the status
    endpoint needs them to confirm a deletion it just performed).
    """
    row = conn.execute(
        text(
            "SELECT s.id, s.display_name, s.email, s.notes, s.status, "
            "s.created_at, s.updated_at, "
            "(SELECT count(*) FROM student_vocabulary sv "
            " WHERE sv.student_id = s.id AND sv.is_active) AS assigned_count "
            "FROM students s "
            "WHERE s.id = CAST(:sid AS uuid) "
            "AND s.teacher_id = CAST(:tid AS uuid)"
            + ("" if include_deleted else " AND s.status != 'DELETED'")
        ),
        {"sid": student_id, "tid": str(teacher_id)},
    ).mappings().first()
    if row is None:
        raise NotFoundError("No such student.")
    return row


def get_student(
    conn: Any, teacher_id: uuid.UUID, student_id: str
) -> dict[str, Any]:
    """Open profile (§27): identity + counts; vocabulary list is separate."""
    return _row_to_dict(_get_scoped(conn, teacher_id, student_id))


def create_student(
    conn: Any,
    teacher_id: uuid.UUID,
    display_name: str,
    email: str | None,
    notes: str | None,
) -> dict[str, Any]:
    validate_student_input(display_name, email, notes)
    email_norm = email.strip().lower() if email and email.strip() else None
    if email_norm is not None:
        dup = conn.execute(
            text(
                "SELECT 1 FROM students WHERE teacher_id = CAST(:tid AS uuid) "
                "AND lower(email) = :e AND status != 'DELETED'"
            ),
            {"tid": str(teacher_id), "e": email_norm},
        ).first()
        if dup is not None:
            raise ConflictError("A student with this email already exists.")
    sid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO students (id, teacher_id, display_name, email, notes, status) "
            "VALUES (:id, CAST(:tid AS uuid), :dn, :e, :n, 'ACTIVE')"
        ),
        {
            "id": sid,
            "tid": str(teacher_id),
            "dn": display_name.strip(),
            "e": email_norm,
            "n": notes,
        },
    )
    return get_student(conn, teacher_id, str(sid))


def update_student(
    conn: Any,
    teacher_id: uuid.UUID,
    student_id: str,
    display_name: str | None,
    email: str | None,
    notes: str | None,
    *,
    sent: set[str] | None = None,
) -> dict[str, Any]:
    """Edit (§27): absent fields keep their values; explicitly sent nulls
    clear them (``sent`` = fields present in the request body)."""
    sent = sent if sent is not None else {k for k, v in (
        ("display_name", display_name), ("email", email), ("notes", notes)
    ) if v is not None}
    current = _get_scoped(conn, teacher_id, student_id)
    new_name = (
        display_name.strip()
        if "display_name" in sent and display_name is not None
        else current["display_name"]
    )
    if "email" in sent:
        new_email = email.strip().lower() if email is not None and email.strip() else None
    else:
        new_email = current["email"]
    new_notes = notes if "notes" in sent else current["notes"]
    validate_student_input(new_name, new_email, new_notes)
    if new_email is not None:
        dup = conn.execute(
            text(
                "SELECT 1 FROM students WHERE teacher_id = CAST(:tid AS uuid) "
                "AND lower(email) = :e AND status != 'DELETED' "
                "AND id != CAST(:sid AS uuid)"
            ),
            {"tid": str(teacher_id), "e": new_email, "sid": student_id},
        ).first()
        if dup is not None:
            raise ConflictError("A student with this email already exists.")
    conn.execute(
        text(
            "UPDATE students SET display_name = :dn, email = :e, notes = :n, "
            "updated_at = now() WHERE id = CAST(:sid AS uuid) "
            "AND teacher_id = CAST(:tid AS uuid)"
        ),
        {"sid": student_id, "tid": str(teacher_id), "dn": new_name, "e": new_email, "n": new_notes},
    )
    return get_student(conn, teacher_id, student_id)


def set_status(
    conn: Any, teacher_id: uuid.UUID, student_id: str, status: str
) -> dict[str, Any]:
    """Deactivate/reactivate/delete (§27): status flips only.

    Delete keeps the row (status DELETED) so review history and FSRS
    state survive — §27 forbids destroying historical learning records.
    """
    if status not in ("ACTIVE", "INACTIVE", "DELETED"):
        raise ValidationError("Invalid student status.")
    _get_scoped(conn, teacher_id, student_id)
    conn.execute(
        text(
            "UPDATE students SET status = :st, updated_at = now() "
            "WHERE id = CAST(:sid AS uuid) AND teacher_id = CAST(:tid AS uuid)"
        ),
        {"sid": student_id, "tid": str(teacher_id), "st": status},
    )
    # Refetch including DELETED: confirming a soft delete must not 404.
    return _row_to_dict(
        _get_scoped(conn, teacher_id, student_id, include_deleted=True)
    )


def student_vocabulary(
    conn: Any, teacher_id: uuid.UUID, student_id: str
) -> list[dict[str, Any]]:
    """View assigned vocabulary + learning state (§27/§28)."""
    _get_scoped(conn, teacher_id, student_id)
    rows = conn.execute(
        text(
            "SELECT sv.id AS sv_id, sv.learning_state, sv.is_active, "
            "sv.assigned_at, sv.teacher_priority_override, "
            "vs.id AS sense_id, vs.headword, vs.part_of_speech, vs.cefr_level, "
            "vs.definition_preview, vs.priority_level, "
            "(SELECT st.translation FROM sense_translations st "
            " WHERE st.sense_id = vs.id ORDER BY st.position LIMIT 1) AS translation_pl, "
            "fs.due_at, fs.repetitions, fs.lapses "
            "FROM student_vocabulary sv "
            "JOIN vocabulary_senses vs ON vs.id = sv.sense_id "
            "LEFT JOIN student_fsrs_states fs ON fs.student_vocabulary_id = sv.id "
            "WHERE sv.student_id = CAST(:sid AS uuid) "
            "ORDER BY sv.assigned_at DESC, vs.headword"
        ),
        {"sid": student_id},
    ).mappings().all()
    return [
        {
            "id": str(r["sv_id"]),
            "learning_state": r["learning_state"],
            "is_active": r["is_active"],
            "assigned_at": r["assigned_at"].isoformat(),
            "teacher_priority_override": r["teacher_priority_override"],
            "sense": {
                "id": str(r["sense_id"]),
                "headword": r["headword"],
                "part_of_speech": r["part_of_speech"],
                "cefr_level": r["cefr_level"],
                "definition_preview": r["definition_preview"],
                "priority_level": r["priority_level"],
                "translation_pl": r["translation_pl"],
            },
            "due_at": r["due_at"].isoformat() if r["due_at"] else None,
            "repetitions": r["repetitions"],
            "lapses": r["lapses"],
        }
        for r in rows
    ]
