"""Vocabulary sets service (Phase 19, section 26).

A set is a named collection of references to existing master senses —
it never duplicates vocabulary. Operations mirror §26: create, rename,
view, delete, add/remove vocabulary, assign sets. All queries are
WHERE-scoped to the owning teacher (§40 isolation, per D019); item
membership is duplicate-safe with the (set_id, sense_id) primary key as
the §29-style backstop and an explicit selected/new/already report.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from app.core.assignments import assign_senses
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.students import _get_scoped

MAX_NAME = 200


def validate_set_name(name: str | None) -> str:
    if name is None or not name.strip() or len(name) > MAX_NAME:
        raise ValidationError(f"A set name (1-{MAX_NAME} characters) is required.")
    return name.strip()


def _set_scoped(conn: Any, teacher_id: uuid.UUID, set_id: str) -> Any:
    """Fetch one set, 404 unless it exists AND belongs to the teacher."""
    try:
        sid = str(uuid.UUID(set_id))
    except (ValueError, AttributeError) as exc:
        raise NotFoundError("No such set.") from exc
    row = conn.execute(
        text(
            "SELECT id, name, description, created_at, updated_at, "
            "(SELECT count(*) FROM vocabulary_set_items i "
            " WHERE i.set_id = s.id) AS item_count "
            "FROM vocabulary_sets s WHERE s.id = CAST(:sid AS uuid) "
            "AND s.teacher_id = CAST(:tid AS uuid)"
        ),
        {"sid": sid, "tid": str(teacher_id)},
    ).mappings().first()
    if row is None:
        raise NotFoundError("No such set.")
    return row


def _set_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "item_count": row["item_count"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def create_set(
    conn: Any,
    teacher_id: uuid.UUID,
    name: str,
    description: str | None,
) -> dict[str, Any]:
    name = validate_set_name(name)
    if description is not None and len(description) > 10_000:
        raise ValidationError("Description must be at most 10,000 characters.")
    dup = conn.execute(
        text(
            "SELECT 1 FROM vocabulary_sets "
            "WHERE teacher_id = CAST(:tid AS uuid) AND name = :n"
        ),
        {"tid": str(teacher_id), "n": name},
    ).first()
    if dup is not None:
        raise ConflictError("A set with this name already exists.")
    sid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO vocabulary_sets (id, teacher_id, name, description) "
            "VALUES (:id, CAST(:tid AS uuid), :n, :d)"
        ),
        {"id": sid, "tid": str(teacher_id), "n": name, "d": description},
    )
    return _set_dict(_set_scoped(conn, teacher_id, str(sid)))


def list_sets(conn: Any, teacher_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT s.id, s.name, s.description, s.created_at, s.updated_at, "
            "(SELECT count(*) FROM vocabulary_set_items i "
            " WHERE i.set_id = s.id) AS item_count "
            "FROM vocabulary_sets s WHERE s.teacher_id = CAST(:tid AS uuid) "
            "ORDER BY s.name"
        ),
        {"tid": str(teacher_id)},
    ).mappings().all()
    return [_set_dict(r) for r in rows]


def get_set(
    conn: Any, teacher_id: uuid.UUID, set_id: str, *, with_items: bool = True
) -> dict[str, Any]:
    """View one set (§26); with_items includes sense details per item."""
    row = _set_scoped(conn, teacher_id, set_id)
    out = _set_dict(row)
    if with_items:
        items = conn.execute(
            text(
                "SELECT i.sense_id, i.added_at, vs.headword, vs.part_of_speech, "
                "vs.cefr_level, vs.definition_preview, "
                "(SELECT st.translation FROM sense_translations st "
                " WHERE st.sense_id = vs.id ORDER BY st.position LIMIT 1) "
                "AS translation_pl "
                "FROM vocabulary_set_items i "
                "JOIN vocabulary_senses vs ON vs.id = i.sense_id "
                "WHERE i.set_id = CAST(:sid AS uuid) "
                "ORDER BY i.added_at, vs.headword"
            ),
            {"sid": str(row["id"])},
        ).mappings().all()
        out["items"] = [
            {
                "sense_id": str(r["sense_id"]),
                "added_at": r["added_at"].isoformat(),
                "headword": r["headword"],
                "part_of_speech": r["part_of_speech"],
                "cefr_level": r["cefr_level"],
                "definition_preview": r["definition_preview"],
                "translation_pl": r["translation_pl"],
            }
            for r in items
        ]
    return out


def update_set(
    conn: Any,
    teacher_id: uuid.UUID,
    set_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    sent: set[str] | None = None,
) -> dict[str, Any]:
    """Rename / re-describe (§26); PATCH semantics per D019."""
    row = _set_scoped(conn, teacher_id, set_id)
    sent = sent or set()
    params: dict[str, Any] = {"sid": str(row["id"]), "tid": str(teacher_id)}
    sets: list[str] = []
    if "name" in sent:
        new_name = validate_set_name(name)
        dup = conn.execute(
            text(
                "SELECT 1 FROM vocabulary_sets "
                "WHERE teacher_id = CAST(:tid AS uuid) AND name = :n "
                "AND id != CAST(:sid AS uuid)"
            ),
            {"tid": str(teacher_id), "n": new_name, "sid": str(row["id"])},
        ).first()
        if dup is not None:
            raise ConflictError("A set with this name already exists.")
        sets.append("name = :n")
        params["n"] = new_name
    if "description" in sent:
        if description is not None and len(description) > 10_000:
            raise ValidationError("Description must be at most 10,000 characters.")
        sets.append("description = :d")
        params["d"] = description
    if sets:
        sets.append("updated_at = now()")
        conn.execute(
            text(
                "UPDATE vocabulary_sets SET "
                + ", ".join(sets)
                + " WHERE id = CAST(:sid AS uuid) "
                "AND teacher_id = CAST(:tid AS uuid)"
            ),
            params,
        )
    return _set_dict(_set_scoped(conn, teacher_id, set_id))


def delete_set(conn: Any, teacher_id: uuid.UUID, set_id: str) -> dict[str, Any]:
    """Delete (§26). Removes the collection and memberships only —
    master vocabulary and student learning records are untouched."""
    row = _set_scoped(conn, teacher_id, set_id)
    conn.execute(
        text(
            "DELETE FROM vocabulary_sets WHERE id = CAST(:sid AS uuid) "
            "AND teacher_id = CAST(:tid AS uuid)"
        ),
        {"sid": str(row["id"]), "tid": str(teacher_id)},
    )
    return {"deleted": True, "id": str(row["id"]), "name": row["name"]}


def add_items(
    conn: Any, teacher_id: uuid.UUID, set_id: str, sense_ids: list[str]
) -> dict[str, Any]:
    """Add senses to a set (§26); duplicate-safe with per-item report."""
    if not sense_ids:
        raise ValidationError("At least one sense id is required.")
    if len(sense_ids) > 1000:
        raise ValidationError("At most 1000 senses per operation.")
    sid = str(_set_scoped(conn, teacher_id, set_id)["id"])

    parsed: list[str] = []
    invalid: list[str] = []
    for raw in sense_ids:
        token = raw.strip() if isinstance(raw, str) else ""
        if not token:
            continue
        try:
            parsed.append(str(uuid.UUID(token)))
        except (ValueError, AttributeError):
            invalid.append(token if isinstance(token, str) else str(token))
    parsed = list(dict.fromkeys(parsed))

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

    member: set[str] = set()
    to_add = sorted(existing_senses)
    if to_add:
        rows = conn.execute(
            text(
                "SELECT sense_id FROM vocabulary_set_items "
                "WHERE set_id = CAST(:sid AS uuid) "
                "AND sense_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"sid": sid, "ids": to_add},
        ).fetchall()
        member = {str(r[0]) for r in rows}
    new_ids = [s for s in to_add if s not in member]
    already = [s for s in to_add if s in member]

    if new_ids:
        conn.execute(
            text(
                "INSERT INTO vocabulary_set_items (set_id, sense_id) "
                "SELECT CAST(:sid AS uuid), x "
                "FROM unnest(CAST(:ids AS uuid[])) AS x "
                "ON CONFLICT (set_id, sense_id) DO NOTHING"
            ),
            {"sid": sid, "ids": new_ids},
        )
    conn.execute(
        text("UPDATE vocabulary_sets SET updated_at = now() WHERE id = CAST(:sid AS uuid)"),
        {"sid": sid},
    )
    return {
        "selected": len(sense_ids),
        "new": len(new_ids),
        "already_in_set": len(already),
        "failed": [{"sense_id": s, "reason": "sense_not_found"} for s in not_found]
        + [{"sense_id": s, "reason": "invalid_id"} for s in invalid],
        "set_id": sid,
        "sense_ids": new_ids,
    }


def remove_items(
    conn: Any, teacher_id: uuid.UUID, set_id: str, sense_ids: list[str]
) -> dict[str, Any]:
    """Remove senses from a set; reports removed vs not_in_set."""
    if not sense_ids:
        raise ValidationError("At least one sense id is required.")
    sid = str(_set_scoped(conn, teacher_id, set_id)["id"])
    parsed: list[str] = []
    for raw in sense_ids:
        try:
            parsed.append(str(uuid.UUID(raw.strip())))
        except (ValueError, AttributeError):
            continue
    parsed = list(dict.fromkeys(parsed))
    result = conn.execute(
        text(
            "DELETE FROM vocabulary_set_items WHERE set_id = CAST(:sid AS uuid) "
            "AND sense_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"sid": sid, "ids": parsed},
    )
    conn.execute(
        text("UPDATE vocabulary_sets SET updated_at = now() WHERE id = CAST(:sid AS uuid)"),
        {"sid": sid},
    )
    return {
        "set_id": sid,
        "selected": len(sense_ids),
        "removed": result.rowcount,
        "not_in_set": len(parsed) - result.rowcount,
    }


def assign_set(
    conn: Any,
    teacher_id: uuid.UUID,
    set_id: str,
    student_id: str,
    *,
    learning_state: str = "ASSIGNED",
) -> dict[str, Any]:
    """Assign every sense in a set to a student (§26 'assign sets')."""
    row = _set_scoped(conn, teacher_id, set_id)
    _get_scoped(conn, teacher_id, student_id)  # §40: student must be ours
    item_ids = [
        str(r[0])
        for r in conn.execute(
            text(
                "SELECT sense_id FROM vocabulary_set_items "
                "WHERE set_id = CAST(:sid AS uuid) "
                "ORDER BY (SELECT headword_normalized FROM vocabulary_senses vs "
                "          WHERE vs.id = sense_id)"
            ),
            {"sid": str(row["id"])},
        ).fetchall()
    ]
    report = assign_senses(
        conn, teacher_id, student_id, item_ids, learning_state=learning_state
    )
    report["set_id"] = str(row["id"])
    report["set_name"] = row["name"]
    return report
