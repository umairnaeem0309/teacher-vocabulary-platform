"""Vocabulary sets domain (Phase 19, section 26).

CRUD + membership + set assignment, all teacher-authenticated and
WHERE-scoped to the owning teacher (§40). Logic in app.core.sets.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.v1.auth import _require_teacher
from app.api.v1.students import _tid
from app.core import sets as sets_core
from app.db.session import get_engine

router = APIRouter(prefix="/sets", tags=["sets"])

TeacherDep = Annotated[dict[str, Any], Depends(_require_teacher)]


class SetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)


class SetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)


class SetItemsRequest(BaseModel):
    sense_ids: list[str] = Field(min_length=1, max_length=1000)


class SetAssignRequest(BaseModel):
    student_id: str
    learning_state: str = Field(
        default="ASSIGNED",
        pattern="^(NEW|ASSIGNED|ENCOUNTERED|LEARNING|REVIEWING|MASTERED)$",
    )


@router.get("")
def list_sets(teacher: TeacherDep) -> dict[str, Any]:
    with get_engine().connect() as conn:
        items = sets_core.list_sets(conn, _tid(teacher))
    return {"sets": items, "total": len(items)}


@router.post("", status_code=201)
def create_set(teacher: TeacherDep, body: SetCreate) -> dict[str, Any]:
    with get_engine().begin() as conn:
        return sets_core.create_set(conn, _tid(teacher), body.name, body.description)


@router.get("/{set_id}")
def get_set(teacher: TeacherDep, set_id: str) -> dict[str, Any]:
    with get_engine().connect() as conn:
        return sets_core.get_set(conn, _tid(teacher), set_id)


@router.patch("/{set_id}")
def update_set(
    teacher: TeacherDep, set_id: str, body: SetUpdate
) -> dict[str, Any]:
    sent = body.model_fields_set
    with get_engine().begin() as conn:
        return sets_core.update_set(
            conn,
            _tid(teacher),
            set_id,
            name=body.name,
            description=body.description,
            sent=sent,
        )


@router.delete("/{set_id}")
def delete_set(teacher: TeacherDep, set_id: str) -> dict[str, Any]:
    with get_engine().begin() as conn:
        return sets_core.delete_set(conn, _tid(teacher), set_id)


@router.post("/{set_id}/items", status_code=200)
def add_items(
    teacher: TeacherDep, set_id: str, body: SetItemsRequest
) -> dict[str, Any]:
    with get_engine().begin() as conn:
        return sets_core.add_items(conn, _tid(teacher), set_id, body.sense_ids)


@router.delete("/{set_id}/items")
def remove_items(
    teacher: TeacherDep, set_id: str, body: SetItemsRequest
) -> dict[str, Any]:
    with get_engine().begin() as conn:
        return sets_core.remove_items(conn, _tid(teacher), set_id, body.sense_ids)


@router.post("/{set_id}/assign")
def assign_set(teacher: TeacherDep, set_id: str, body: SetAssignRequest) -> dict[str, Any]:
    with get_engine().begin() as conn:
        return sets_core.assign_set(
            conn,
            _tid(teacher),
            set_id,
            body.student_id,
            learning_state=body.learning_state,
        )
