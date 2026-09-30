"""Assignment service (Phase 18, sections 28-30).

Creates student-vocabulary records with §29 duplicate prevention at
both required layers: the application identifies already-assigned
senses before inserting, and the database UNIQUE(student_id, sense_id)
constraint (uq_student_sense) is the backstop. Bulk operations run in
one transaction and report ``selected / new / already_assigned /
failed`` per §29.

§40 authorization mirrors the students service: the student must exist
and belong to the calling teacher (WHERE-scoped), otherwise 404.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from app.core.errors import NotFoundError, ValidationError
from app.core.students import _get_scoped

# §31 states an assignment may start in / be moved to.
ALLOWED_STATES = ("NEW", "ASSIGNED", "ENCOUNTERED", "LEARNING", "REVIEWING", "MASTERED")


def _validate_uuid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError(f"No such {label}.") from exc


def _student_scoped(conn: Any, teacher_id: uuid.UUID, student_id: str) -> str:
    """404 unless the student exists and belongs to the teacher."""
    return str(_get_scoped(conn, teacher_id, student_id)["id"])


def assign_senses(
    conn: Any,
    teacher_id: uuid.UUID,
    student_id: str,
    sense_ids: list[str],
    *,
    learning_state: str = "ASSIGNED",
    reactivate: bool = True,
) -> dict[str, Any]:
    """Assign one or more senses to one student (§28/§29).

    Transactional upsert: already-assigned senses are skipped and
    reported, never duplicated (application pre-check + UNIQUE backstop).
    An inactive (previously unassigned) record is reactivated instead of
    inserting a duplicate row.
    """
    if learning_state not in ALLOWED_STATES:
        raise ValidationError(f"Invalid learning state: {learning_state!r}")
    sid = _student_scoped(conn, teacher_id, student_id)
    if not sense_ids:
        raise ValidationError("At least one sense id is required.")
    if len(sense_ids) > 1000:
        raise ValidationError("At most 1000 senses per bulk operation.")

    # Only senses that exist and are active count as assignable.
    wanted = list(dict.fromkeys(sid_str.strip() for sid_str in sense_ids if sid_str.strip()))
    parsed: list[str] = []
    invalid: list[str] = []
    for raw in wanted:
        try:
            parsed.append(str(uuid.UUID(raw)))
        except (ValueError, AttributeError):
            invalid.append(raw)
    existing_senses: set[str] = set()
    if parsed:
        rows = conn.execute(
            text(
                "SELECT id FROM vocabulary_senses "
                "WHERE id = ANY(CAST(:ids AS uuid[])) AND is_active"
            ),
            {"ids": parsed},
        ).fetchall()
        existing_senses = {str(r[0]) for r in rows}
    not_found = [s for s in parsed if s not in existing_senses]

    to_insert = sorted(existing_senses)
    current: dict[str, tuple[bool, str]] = {}
    if to_insert:
        rows = conn.execute(
            text(
                "SELECT sense_id, is_active, learning_state FROM student_vocabulary "
                "WHERE student_id = CAST(:sid AS uuid) "
                "AND sense_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"sid": sid, "ids": to_insert},
        ).fetchall()
        current = {str(r[0]): (r[1], r[2]) for r in rows}

    new_ids: list[str] = []
    reactivated_ids: list[str] = []
    already: list[str] = []
    for sense_id in to_insert:
        state_info = current.get(sense_id)
        if state_info is None:
            new_ids.append(sense_id)
        elif not state_info[0] and reactivate:
            reactivated_ids.append(sense_id)
        else:
            already.append(sense_id)

    if new_ids:
        conn.execute(
            text(
                "INSERT INTO student_vocabulary "
                "(id, student_id, sense_id, learning_state, is_active) "
                "SELECT x.id, CAST(:sid AS uuid), x.sense_id, :st, true "
                "FROM (SELECT unnest(CAST(:ids AS uuid[])) AS sense_id, "
                "gen_random_uuid() AS id) x "
                "ON CONFLICT (student_id, sense_id) DO NOTHING"
            ),
            {"sid": sid, "ids": new_ids, "st": learning_state},
        )
    if reactivated_ids:
        conn.execute(
            text(
                "UPDATE student_vocabulary SET is_active = true, "
                "learning_state = :st, assigned_at = now(), updated_at = now() "
                "WHERE student_id = CAST(:sid AS uuid) "
                "AND sense_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"sid": sid, "ids": reactivated_ids, "st": learning_state},
        )

    return {
        "selected": len(sense_ids),
        "new": len(new_ids) + len(reactivated_ids),
        "already_assigned": len(already),
        "failed": [
            {"sense_id": s, "reason": "sense_not_found"}
            for s in not_found
        ]
        + [{"sense_id": s, "reason": "invalid_id"} for s in invalid],
        "student_id": sid,
        "sense_ids": new_ids + reactivated_ids,
    }


def get_assignment(
    conn: Any, teacher_id: uuid.UUID, student_id: str, assignment_id: str
) -> dict[str, Any]:
    """One assignment row, scoped through the owning student."""
    sid = _student_scoped(conn, teacher_id, student_id)
    aid = _validate_uuid(assignment_id, "assignment")
    row = (
        conn.execute(
            text(
                "SELECT sv.id, sv.learning_state, sv.is_active, "
                "sv.teacher_priority_override, sv.assigned_at, sv.updated_at, "
                "vs.id AS sense_id, vs.headword, vs.part_of_speech, vs.cefr_level "
                "FROM student_vocabulary sv "
                "JOIN vocabulary_senses vs ON vs.id = sv.sense_id "
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
    return _assignment_dict(row)


def _assignment_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "learning_state": row["learning_state"],
        "is_active": row["is_active"],
        "teacher_priority_override": row["teacher_priority_override"],
        "assigned_at": row["assigned_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "sense": {
            "id": str(row["sense_id"]),
            "headword": row["headword"],
            "part_of_speech": row["part_of_speech"],
            "cefr_level": row["cefr_level"],
        },
    }


def update_assignment(
    conn: Any,
    teacher_id: uuid.UUID,
    student_id: str,
    assignment_id: str,
    *,
    learning_state: str | None = None,
    teacher_priority_override: str | None = None,
    is_active: bool | None = None,
    sent: set[str] | None = None,
) -> dict[str, Any]:
    """Edit one assignment: state moves / teacher priority override / hide.

    §31: teacher overrides are explicit — the endpoint applies exactly
    what the teacher sent, nothing is inferred.
    """
    sid = _student_scoped(conn, teacher_id, student_id)
    aid = _validate_uuid(assignment_id, "assignment")
    sent = sent or set()

    if learning_state is not None and learning_state not in ALLOWED_STATES:
        raise ValidationError(f"Invalid learning state: {learning_state!r}")
    if teacher_priority_override is not None and (
        teacher_priority_override not in ALLOWED_PRIORITY_LEVELS
    ):
        raise ValidationError(
            f"Invalid priority level: {teacher_priority_override!r}"
        )

    sets: list[str] = []
    params: dict[str, Any] = {"aid": aid, "sid": sid}
    if "learning_state" in sent and learning_state is not None:
        sets.append("learning_state = :st")
        params["st"] = learning_state
    if "teacher_priority_override" in sent:
        sets.append("teacher_priority_override = :tpo")
        params["tpo"] = teacher_priority_override
    if "is_active" in sent and is_active is not None:
        sets.append("is_active = :act")
        params["act"] = is_active
    if not sets:
        raise ValidationError("No assignment fields to update.")
    sets.append("updated_at = now()")
    result = conn.execute(
        text(
            "UPDATE student_vocabulary SET "
            + ", ".join(sets)
            + " WHERE id = CAST(:aid AS uuid) AND student_id = CAST(:sid AS uuid)"
        ),
        params,
    )
    if result.rowcount == 0:
        raise NotFoundError("No such assignment.")
    return get_assignment(conn, teacher_id, student_id, assignment_id)


ALLOWED_PRIORITY_LEVELS = ("VERY HIGH", "HIGH", "MEDIUM", "LOW", "VERY LOW")
