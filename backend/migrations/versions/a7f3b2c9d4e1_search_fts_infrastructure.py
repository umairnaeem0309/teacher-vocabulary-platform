"""search infrastructure: tsvector columns + GIN indexes

Revision ID: a7f3b2c9d4e1
Revises: c3d94a71b6e2
Create Date: 2026-09-29

Phase 14 (section 20 Layer 1): PostgreSQL native text search.

Generated tsvector columns cover the searchable text of the master
vocabulary: English headwords + forms, Polish translations and English
definitions. Weights: A = headword/translations (what a teacher names
directly), B = forms and definitions (contextual evidence). Columns are
maintained by generated columns (persisted), so imports and future writes
cannot drift from the indexed text.

Dictionary choice: 'simple' — the data is pre-normalized
(`headword_normalized`, `translation_normalized`) and the corpus mixes
English and Polish; a language-specific dictionary would wrong-stem one
of the two.
"""

import sqlalchemy as sa
from alembic import op

revision = "a7f3b2c9d4e1"
down_revision = "c3d94a71b6e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- vocabulary_senses: headword (A) + definition preview (B) ---
    op.add_column(
        "vocabulary_senses",
        sa.Column(
            "fts",
            sa.dialects.postgresql.TSVECTOR,
            sa.Computed(
                "setweight(to_tsvector('simple', coalesce(headword_normalized, '')), 'A')"
                " || setweight(to_tsvector('simple', coalesce(definition_preview, '')), 'B')",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_senses_fts", "vocabulary_senses", ["fts"], postgresql_using="gin"
    )

    # --- sense_translations: Polish translation (A) ---
    # Multiple translations per sense: stored per row; the sense-level
    # query aggregates with a subselect into the ranking tsvector.
    op.add_column(
        "sense_translations",
        sa.Column(
            "fts",
            sa.dialects.postgresql.TSVECTOR,
            sa.Computed(
                "setweight(to_tsvector('simple', coalesce(translation_normalized, '')), 'A')",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_translations_fts", "sense_translations", ["fts"], postgresql_using="gin"
    )

    # --- sense_definitions: full definitions (B) ---
    op.add_column(
        "sense_definitions",
        sa.Column(
            "fts",
            sa.dialects.postgresql.TSVECTOR,
            sa.Computed(
                "to_tsvector('simple', coalesce(definition, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_definitions_fts", "sense_definitions", ["fts"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_definitions_fts", table_name="sense_definitions")
    op.drop_column("sense_definitions", "fts")
    op.drop_index("ix_translations_fts", table_name="sense_translations")
    op.drop_column("sense_translations", "fts")
    op.drop_index("ix_senses_fts", table_name="vocabulary_senses")
    op.drop_column("vocabulary_senses", "fts")
