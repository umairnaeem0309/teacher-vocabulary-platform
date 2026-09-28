"""Phase 13 tests: PostgreSQL vocabulary import (section 89)."""

from __future__ import annotations

import json

from pipeline.storage.pg_import import (
    ImportReport,
    collapse_cefr,
    import_vocabulary,
    normalize_sense_row,
    validate_sense_row,
)

from tests.conftest import requires_db

PG_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/vocab_platform"
IMPORT_PREFIX = "it13"


def _sense(key: str, **over: object) -> dict:
    row = {
        "sense_key": key,
        "key_version": "sensekey-v1",
        "headword_display": "Bank",
        "headword_search": "bank",
        "pos_canonical": "noun",
        "gloss_display": "a financial institution",
        "cefr_level": "A2",
        "frequency_rank": 620,
        "tags_json": '["obsolete", "US", "countable"]',
        "sources_json": '["wiktextract"]',
        "processing_version": "norm-v1",
        "priority_score": 0.7,
        "priority_level": "HIGH",
        "priority_version": "prio-v1.1",
    }
    row.update(over)
    return row


def _payload(senses: list[dict], **extra: list[dict]) -> dict:
    base: dict = {"senses": senses}
    base.update(extra)
    return base


class TestValidation:
    def test_valid_row_passes(self) -> None:
        assert validate_sense_row(_sense("x|noun|t")) is None

    def test_missing_required_field(self) -> None:
        row = _sense("x|noun|t", headword_search="")
        msg = validate_sense_row(row)
        assert msg is not None and "headword_search" in msg

    def test_wrong_key_version_rejected(self) -> None:
        row = _sense("x|noun|t", key_version="sensekey-v2")
        msg = validate_sense_row(row)
        assert msg is not None and "key_version" in msg

    def test_unknown_pos_rejected(self) -> None:
        row = _sense("x|noun|t", pos_canonical="particle")
        msg = validate_sense_row(row)
        assert msg is not None and "pos_canonical" in msg

    def test_unknown_cefr_rejected(self) -> None:
        row = _sense("x|noun|t", cefr_level="B7")
        msg = validate_sense_row(row)
        assert msg is not None and "cefr_level" in msg

    def test_oversized_sense_key_rejected(self) -> None:
        row = _sense("x" * 401 + "|noun|t")
        msg = validate_sense_row(row)
        assert msg is not None and "400" in msg

    def test_non_numeric_rank_rejected(self) -> None:
        row = _sense("x|noun|t", frequency_rank="high")
        assert validate_sense_row(row) is not None

    def test_normalize_maps_columns(self) -> None:
        out = normalize_sense_row(_sense("x|noun|t"))
        assert out["headword"] == "Bank"
        assert out["headword_normalized"] == "bank"
        assert out["part_of_speech"] == "noun"
        assert out["definition_preview"].startswith("a financial")
        assert out["is_active"] is True

    def test_normalize_blank_pos_to_none(self) -> None:
        out = normalize_sense_row(_sense("x|noun|t", pos_canonical=""))
        assert out["part_of_speech"] is None


class TestCollapseCefr:
    def test_dedup_keeps_deterministic_survivor(self) -> None:
        rows = [
            {"sense_key": "s", "source": "cefrj", "cefr": "B1", "pos_raw": "verb"},
            {"sense_key": "s", "source": "cefrj", "cefr": "A1", "pos_raw": "noun"},
        ]
        collapsed, dropped = collapse_cefr(rows)
        assert dropped == 1
        assert len(collapsed) == 1
        assert collapsed[0]["cefr"] == "A1"  # lexicographically smallest

    def test_no_dedup_across_sources(self) -> None:
        rows = [
            {"sense_key": "s", "source": "cefrj", "cefr": "B1", "pos_raw": "verb"},
            {"sense_key": "s", "source": "octanove", "cefr": "A1", "pos_raw": "noun"},
        ]
        collapsed, dropped = collapse_cefr(rows)
        assert dropped == 0 and len(collapsed) == 2

    def test_empty(self) -> None:
        assert collapse_cefr([]) == ([], 0)


class TestReport:
    def test_summary_and_json(self) -> None:
        r = ImportReport()
        r.records_processed = 10
        r.records_inserted = 7
        r.records_updated = 2
        r.records_rejected = 1
        r.warn("w1")
        d = json.loads(r.as_json())
        assert d["records_processed"] == 10
        assert d["warnings"] == ["w1"]
        assert "rejected=1" in r.summary()


@requires_db
class TestPgImport:
    def test_import_and_idempotent_reimport(self) -> None:
        from sqlalchemy import create_engine

        engine = create_engine(PG_URL, pool_pre_ping=True)
        try:
            payload = _payload(
                [
                    _sense(f"{IMPORT_PREFIX}-a|noun|t"),
                    _sense(f"{IMPORT_PREFIX}-b|verb|t", pos_canonical="verb"),
                ],
                definitions=[
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t", "gloss_display": "def a"}
                ],
                translations=[
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t", "translation": "bank",
                     "confidence": 0.5, "method": "cognate"}
                ],
                examples=[
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t", "position": 0,
                     "text": "ex one", "source": "wiktextract"}
                ],
                cefr_evidence=[
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t", "source": "cefrj",
                     "cefr": "B1", "pos_raw": "noun"},
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t", "source": "cefrj",
                     "cefr": "A2", "pos_raw": "noun"},
                ],
                frequency_evidence=[
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t", "source": "ngsl",
                     "rank": 99, "freq": 1234.0}
                ],
                priorities=[
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t", "score": 0.5,
                     "level": "HIGH", "version": "prio-v1", "components_json": '{"q": 1}'},
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t", "score": 0.6,
                     "level": "HIGH", "version": "prio-v1.1", "components_json": '{"q": 2}'},
                ],
                categories=[
                    {"node_key": f"{IMPORT_PREFIX}-cat", "name": "Cat",
                     "parent_key": None, "position": 1},
                    {"node_key": f"{IMPORT_PREFIX}-cat-sub", "name": "Sub",
                     "parent_key": f"{IMPORT_PREFIX}-cat", "position": 1},
                ],
                sense_categories=[
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t",
                     "category_key": f"{IMPORT_PREFIX}-cat",
                     "subcategory_key": f"{IMPORT_PREFIX}-cat-sub",
                     "confidence": 0.8, "method": "gloss"},
                    # top-level row implied by the sub row: must be skipped
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t",
                     "category_key": f"{IMPORT_PREFIX}-cat",
                     "subcategory_key": None,
                     "confidence": 0.8, "method": "gloss"},
                ],
                wordnet_synsets=[
                    {"synset_id": f"{IMPORT_PREFIX}-syn-1", "part_of_speech": "n",
                     "definition": "d", "ili": "i1"}
                ],
                wordnet_relations=[],
                wordnet_links=[
                    {"sense_key": f"{IMPORT_PREFIX}-a|noun|t",
                     "synset_id": f"{IMPORT_PREFIX}-syn-1", "confidence": 0.7}
                ],
            )

            with engine.connect() as conn:
                with conn.begin():
                    report1 = import_vocabulary(conn, payload)
                assert report1.records_inserted == 2
                assert report1.records_rejected == 0
                counts1 = self._counts(conn)
                # dup cefr collapsed (2 -> 1); top-level category skipped
                assert counts1["cefr_evidence"] == 1
                assert counts1["sense_categories"] == 1
                assert counts1["sense_priorities"] == 2  # both versions kept
                assert any("collapsed" in w for w in report1.warnings)
                assert any("no double counting" in w for w in report1.warnings)
                conn.commit()  # end the read-only autobegin transaction

                # capture generated ids
                ids1 = self._ids(conn)
                conn.commit()

                # idempotent re-import: no new roots, children refreshed 1:1
                with conn.begin():
                    report2 = import_vocabulary(conn, payload)
                assert report2.records_inserted == 0
                assert report2.records_updated == 2
                counts2 = self._counts(conn)
                assert counts2 == counts1
                assert self._ids(conn) == ids1  # root UUIDs preserved
                conn.commit()

                # delete-refresh: remove a child from payload, row disappears
                payload["examples"] = []
                with conn.begin():
                    import_vocabulary(conn, payload)
                assert self._counts(conn)["sense_examples"] == 0
        finally:
            self._cleanup(engine)

    def test_priority_columns_backfilled_from_current_version(self) -> None:
        from sqlalchemy import create_engine, text

        engine = create_engine(PG_URL, pool_pre_ping=True)
        try:
            payload = _payload(
                [
                    # Real construction rows carry NO denormalized priority
                    # fields (they live only in sense_priorities); mirror that.
                    _sense(
                        f"{IMPORT_PREFIX}-pc|noun|t",
                        priority_score=None,
                        priority_level=None,
                        priority_version=None,
                    ),
                    _sense(
                        f"{IMPORT_PREFIX}-pc2|verb|t",
                        pos_canonical="verb",
                        priority_score=None,
                        priority_level=None,
                        priority_version=None,
                    ),
                ],
                priorities=[
                    {"sense_key": f"{IMPORT_PREFIX}-pc|noun|t", "score": 0.5,
                     "level": "HIGH", "version": "prio-v1", "components_json": None},
                    {"sense_key": f"{IMPORT_PREFIX}-pc|noun|t", "score": 0.9,
                     "level": "CRITICAL", "version": "prio-v1.1", "components_json": None},
                    # sense 2: only an older version exists -> columns stay NULL
                    {"sense_key": f"{IMPORT_PREFIX}-pc2|verb|t",
                     "score": 0.1, "level": "LOW", "version": "prio-v1",
                     "components_json": None},
                ],
            )
            with engine.connect() as conn:
                with conn.begin():
                    report = import_vocabulary(conn, payload)
                # Shared dev DB: the refresh covers every sense with a
                # prio-v1.1 row, not just this payload's; assert inclusion.
                assert report.detail["priority_columns"] >= 1
                row = conn.execute(
                    text(
                        "SELECT priority_score, priority_level, priority_version "
                        "FROM vocabulary_senses WHERE sense_key = :k"
                    ),
                    {"k": f"{IMPORT_PREFIX}-pc|noun|t"},
                ).fetchone()
                assert row == (0.9, "CRITICAL", "prio-v1.1")
                row2 = conn.execute(
                    text(
                        "SELECT priority_score, priority_level, priority_version "
                        "FROM vocabulary_senses WHERE sense_key = :k"
                    ),
                    {"k": f"{IMPORT_PREFIX}-pc2|verb|t"},
                ).fetchone()
                # only prio-v1 exists for this sense: columns stay NULL
                assert row2 == (None, None, None)
                conn.commit()
        finally:
            self._cleanup(engine)

    def test_invalid_sense_rejected_and_reported(self) -> None:
        from sqlalchemy import create_engine, text

        engine = create_engine(PG_URL, pool_pre_ping=True)
        try:
            bad = _sense(f"{IMPORT_PREFIX}-bad|noun|t", key_version="sensekey-v9")
            orphan_child = {
                "sense_key": f"{IMPORT_PREFIX}-ghost|noun|t",
                "gloss_display": "orphan",
            }
            with engine.connect() as conn:
                with conn.begin():
                    report = import_vocabulary(
                        conn,
                        _payload(
                            [
                                _sense(f"{IMPORT_PREFIX}-ok|noun|t"),
                                bad,
                            ],
                            definitions=[orphan_child],
                        ),
                    )
                assert report.records_processed == 2
                assert report.records_rejected == 1
                assert report.records_inserted == 1
                assert any("rejected" in w for w in report.warnings)
                assert any("definitions" in w for w in report.warnings)
                n = conn.execute(
                    text("SELECT count(*) FROM vocabulary_senses WHERE sense_key LIKE :p"),
                    {"p": f"{IMPORT_PREFIX}%"},
                ).scalar()
                assert n == 1
        finally:
            self._cleanup(engine)

    def test_rollback_on_error_leaves_no_trace(self) -> None:
        from sqlalchemy import create_engine, text

        engine = create_engine(PG_URL, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                try:
                    with conn.begin():
                        import_vocabulary(
                            conn,
                            _payload([_sense(f"{IMPORT_PREFIX}-r|noun|t")]),
                        )
                        raise RuntimeError("boom")
                except RuntimeError:
                    pass
                n = conn.execute(
                    text("SELECT count(*) FROM vocabulary_senses WHERE sense_key LIKE :p"),
                    {"p": f"{IMPORT_PREFIX}%"},
                ).scalar()
                assert n == 0
        finally:
            self._cleanup(engine)

    @staticmethod
    def _counts(conn) -> dict:
        from sqlalchemy import text

        out = {}
        out["vocabulary_senses"] = conn.execute(
            text("SELECT count(*) FROM vocabulary_senses WHERE sense_key LIKE :p"),
            {"p": f"{IMPORT_PREFIX}%"},
        ).scalar()
        for t in (
            "vocabulary_forms", "sense_definitions",
            "sense_translations", "sense_examples", "cefr_evidence",
            "frequency_evidence", "vocabulary_flags", "sense_priorities",
            "sense_categories", "sense_wordnet_links",
        ):
            out[t] = conn.execute(
                text(f"SELECT count(*) FROM {t} WHERE {t}.sense_id IN "
                     "(SELECT id FROM vocabulary_senses WHERE sense_key LIKE :p)"),
                {"p": f"{IMPORT_PREFIX}%"},
            ).scalar()
        out["categories"] = conn.execute(
            text("SELECT count(*) FROM categories WHERE key LIKE :p"),
            {"p": f"{IMPORT_PREFIX}%"},
        ).scalar()
        return out

    @staticmethod
    def _ids(conn) -> dict:
        from sqlalchemy import text

        rows = conn.execute(
            text("SELECT sense_key, id FROM vocabulary_senses WHERE sense_key LIKE :p"),
            {"p": f"{IMPORT_PREFIX}%"},
        ).fetchall()
        return {r[0]: str(r[1]) for r in rows}

    @staticmethod
    def _cleanup(engine) -> None:
        from sqlalchemy import text

        child_tables = (
            "sense_categories", "sense_wordnet_links", "sense_priorities",
            "vocabulary_flags", "frequency_evidence", "cefr_evidence",
            "sense_examples", "sense_translations", "sense_definitions",
            "vocabulary_forms",
        )
        with engine.begin() as conn:
            for t in child_tables:
                conn.execute(
                    text(f"DELETE FROM {t} WHERE sense_id IN "
                         "(SELECT id FROM vocabulary_senses WHERE sense_key LIKE :p)"),
                    {"p": f"{IMPORT_PREFIX}%"},
                )
            conn.execute(
                text("DELETE FROM vocabulary_senses WHERE sense_key LIKE :p"),
                {"p": f"{IMPORT_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM categories WHERE key LIKE :p"),
                {"p": f"{IMPORT_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM wordnet_synsets WHERE synset_id LIKE :p"),
                {"p": f"{IMPORT_PREFIX}%"},
            )
