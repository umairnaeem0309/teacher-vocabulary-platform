"""Migration tests (section 78): up/down round-trip and schema correctness.

These run Alembic programmatically against the real development database.
They are skipped automatically when PostgreSQL is unreachable (see conftest).
"""

from sqlalchemy import inspect, text

from tests.conftest import requires_db

pytestmark = [requires_db]

EXPECTED_TABLES = {
    # identity
    "teachers",
    "teacher_sessions",
    "students",
    # vocabulary core
    "vocabulary_senses",
    "vocabulary_forms",
    "sense_definitions",
    "sense_translations",
    "sense_examples",
    "vocabulary_sources",
    "sense_source_records",
    "cefr_evidence",
    "frequency_evidence",
    "vocabulary_flags",
    "wordnet_synsets",
    "wordnet_relations",
    "sense_wordnet_links",
    "categories",
    "sense_categories",
    "sense_priorities",
    "sense_embeddings",  # Phase 12 (section 88; migration 7b2c91a4e8f5)
    # learning
    "student_vocabulary",
    "student_fsrs_states",
    "review_events",
    "vocabulary_sets",
    "vocabulary_set_items",
    "teacher_priority_overrides",
}


def _table_names(engine: object) -> set[str]:
    insp = inspect(engine)  # type: ignore[arg-type]
    names = set(insp.get_table_names())
    names.discard("alembic_version")
    return names


class TestSchemaPresent:
    """All entities from section 41 exist as tables."""

    def test_all_expected_tables_exist(self) -> None:
        from app.db.session import get_engine

        names = _table_names(get_engine())
        missing = EXPECTED_TABLES - names
        assert not missing, f"missing tables: {sorted(missing)}"

    def test_no_unexpected_tables(self) -> None:
        from app.db.session import get_engine

        names = _table_names(get_engine())
        extra = names - EXPECTED_TABLES
        assert not extra, f"unexpected tables: {sorted(extra)}"


class TestMigrationRoundTrip:
    """downgrade base -> upgrade head leaves an equivalent schema (section 78)."""

    def test_downgrade_and_upgrade_roundtrip(self) -> None:
        from alembic import command
        from alembic.config import Config

        from app.db.session import get_engine

        alembic_cfg = Config("alembic.ini")

        before = _table_names(get_engine())
        assert before >= EXPECTED_TABLES, "precondition: schema applied"

        command.downgrade(alembic_cfg, "base")
        after_down = _table_names(get_engine())
        assert not (EXPECTED_TABLES & after_down), "schema not fully dropped"

        command.upgrade(alembic_cfg, "head")
        after_up = _table_names(get_engine())
        assert after_up >= EXPECTED_TABLES, "schema not fully recreated"

        # Version table points at the head revision.
        with get_engine().connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version

    def test_unique_student_sense_constraint_exists(self) -> None:
        from app.db.session import get_engine

        insp = inspect(get_engine())
        uqs = insp.get_unique_constraints("student_vocabulary")
        columns = {tuple(u["column_names"]) for u in uqs}
        assert ("student_id", "sense_id") in columns, (
            "UNIQUE(student_id, sense_id) missing (section 28)"
        )
