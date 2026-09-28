"""sense_priorities composite primary key (sense_id, version)

Revision ID: c3d94a71b6e2
Revises: 7b2c91a4e8f5
Create Date: 2026-09-28

Phase 13 gap fix: Phase 2 keyed sense_priorities by sense_id only, which
cannot represent the versioned priority history required since D012
(section 86: history is never destroyed). The construction DB holds two
versions per sense (prio-v1, prio-v1.1 = 83,380 rows). Switch the primary
key to (sense_id, version) so every formula version is one row; re-imports
upsert by (sense_id, version).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3d94a71b6e2'
down_revision: Union[str, Sequence[str], None] = '7b2c91a4e8f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('pk_sense_priorities', 'sense_priorities', type_='primary')
    op.create_primary_key('pk_sense_priorities', 'sense_priorities', ['sense_id', 'version'])
    op.create_index(
        'ix_sense_priorities_sense', 'sense_priorities', ['sense_id'], unique=False
    )


def downgrade() -> None:
    # collapse any multi-version history back to one row per sense before
    # restoring the sense_id-only key (keep the lexicographically last
    # version per sense, matching the "current version" semantics)
    op.execute(
        """
        DELETE FROM sense_priorities a
        USING sense_priorities b
        WHERE a.sense_id = b.sense_id AND a.version < b.version
        """
    )
    op.drop_index('ix_sense_priorities_sense', table_name='sense_priorities')
    op.drop_constraint('pk_sense_priorities', 'sense_priorities', type_='primary')
    op.create_primary_key('pk_sense_priorities', 'sense_priorities', ['sense_id'])
