"""Migration tests (section 78): up/down round-trip and schema correctness.

Table-presence checks run against the configured development database
(read-only: presence of expected tables only). The up/down round-trip runs
against a dedicated scratch database (``vocab_platform_test``), NOT the dev
database: ``alembic downgrade base`` drops every table and must therefore
never point at data we care about. The scratch DB is created on demand and
dropped afterwards. Tests skip when PostgreSQL is unreachable (conftest).
"""

import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

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


def _admin_url(dev_url: object) -> object:
    """Same server/credentials as dev_url but pointed at the admin DB.

    Works on the SQLAlchemy URL object (never str(), which masks the
    password as ***).
    """
    return dev_url.set(database="postgres")  # type: ignore[attr-defined]


def _scratch_engine() -> Engine:
    """Return an engine to a disposable scratch DB (created here, dropped here).

    Reuses the dev connection's server/port/user; the database name gets a
    random suffix so concurrent runs never collide. Extensions (pgvector)
    must be created explicitly because the scratch DB starts empty.
    """
    from app.db.session import get_engine

    dev_url = get_engine().url
    scratch_name = f"vocab_scratch_{uuid.uuid4().hex[:10]}"
    admin = create_engine(_admin_url(dev_url), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{scratch_name}"'))
    finally:
        admin.dispose()
    scratch_url = dev_url.set(database=scratch_name)  # type: ignore[attr-defined]
    return create_engine(scratch_url)


def _drop_scratch(engine: Engine) -> None:
    name = engine.url.database
    engine.dispose()
    from app.db.session import get_engine

    admin = create_engine(_admin_url(get_engine().url), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


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
    """downgrade base -> upgrade head on a scratch DB leaves dev data intact.

    Regression guard: an earlier version of this test ran
    ``alembic downgrade base`` against the development database and wiped
    all data mid-run (twice). The roundtrip now always targets a disposable
    scratch database.
    """

    def test_downgrade_and_upgrade_roundtrip(self) -> None:
        from alembic import command
        from alembic.config import Config

        from app.db.session import get_engine

        engine = _scratch_engine()
        try:
            # pgvector must exist before migration 7b2c91a4e8f5 adds a
            # vector(1024) column on an empty database.
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()

            alembic_cfg = Config("alembic.ini")
            # Programmatic override -> env.py targets the scratch DB only.
            # NOTE: pass the URL object, not str() — str() masks the password.
            alembic_cfg.attributes["sqlalchemy_url"] = engine.url

            command.upgrade(alembic_cfg, "head")
            after_up = _table_names(engine)
            assert after_up >= EXPECTED_TABLES, "schema not fully recreated"

            command.downgrade(alembic_cfg, "base")
            after_down = _table_names(engine)
            assert not (EXPECTED_TABLES & after_down), "schema not fully dropped"

            # Roundtrip: upgrade again; schema equivalent to the first pass.
            command.upgrade(alembic_cfg, "head")
            after_up2 = _table_names(engine)
            assert after_up2 >= EXPECTED_TABLES, "schema not fully recreated"

            # Version table points at the head revision.
            with engine.connect() as conn:
                version = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            assert version

            # Dev data untouched (the actual regression we are guarding).
            with get_engine().connect() as conn:
                dev_senses = conn.execute(
                    text("SELECT count(*) FROM vocabulary_senses")
                ).scalar()
            assert dev_senses is not None
        finally:
            _drop_scratch(engine)

    def test_unique_student_sense_constraint_exists(self) -> None:
        from app.db.session import get_engine

        insp = inspect(get_engine())
        uqs = insp.get_unique_constraints("student_vocabulary")
        columns = {tuple(u["column_names"]) for u in uqs}
        assert ("student_id", "sense_id") in columns, (
            "UNIQUE(student_id, sense_id) missing (section 28)"
        )
