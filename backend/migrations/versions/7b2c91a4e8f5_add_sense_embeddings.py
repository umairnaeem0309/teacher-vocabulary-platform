"""sense_embeddings table (pgvector + HNSW)

Revision ID: 7b2c91a4e8f5
Revises: 4c047544de4d
Create Date: 2026-09-27

Adds the Phase 12 embeddings storage: one row per sense with a fixed
1024-dimension vector (BGE-M3), plus model/version provenance so results
stay explainable and re-generations are versioned (section 88). An HNSW
index on cosine distance supports semantic search (section 90 planning).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '7b2c91a4e8f5'
down_revision: Union[str, Sequence[str], None] = '4c047544de4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('sense_embeddings',
    sa.Column('sense_id', sa.Uuid(), nullable=False),
    sa.Column('embedding', Vector(1024), nullable=False),
    sa.Column('model_name', sa.String(length=120), nullable=False),
    sa.Column('model_version', sa.String(length=40), nullable=False),
    sa.Column('dims', sa.Integer(), nullable=False),
    sa.Column('embedding_version', sa.String(length=40), nullable=False),
    sa.Column('text_sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['sense_id'], ['vocabulary_senses.id'], name=op.f('fk_sense_embeddings_sense_id_vocabulary_senses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('sense_id', name=op.f('pk_sense_embeddings')),
    sa.UniqueConstraint('sense_id', 'embedding_version', name='uq_sense_embedding_version')
    )
    op.create_index('ix_sense_embeddings_version', 'sense_embeddings', ['embedding_version'], unique=False)
    op.create_index(
        'ix_sense_embeddings_hnsw',
        'sense_embeddings',
        ['embedding'],
        unique=False,
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_sense_embeddings_hnsw', table_name='sense_embeddings')
    op.drop_index('ix_sense_embeddings_version', table_name='sense_embeddings')
    op.drop_table('sense_embeddings')
