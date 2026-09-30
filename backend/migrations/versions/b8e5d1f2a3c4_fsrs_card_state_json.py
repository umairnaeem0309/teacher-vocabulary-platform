"""Add state_json to student_fsrs_states (Phase 20).

The full FSRS card (py-fsrs Card.to_json()) is persisted so the exact
scheduler input/output round-trips — stability/difficulty/reps/lapses
columns remain denormalized for the due-queue scans and dashboards.

Revision ID: b8e5d1f2a3c4
Revises: a7f3b2c9d4e1
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "b8e5d1f2a3c4"
down_revision = "a7f3b2c9d4e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "student_fsrs_states",
        sa.Column("state_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("student_fsrs_states", "state_json")
