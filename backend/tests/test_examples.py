"""Phase 11 tests: example integration (ex-v1, section 87)."""


from pipeline.enrich.examples import (
    EXAMPLES_VERSION,
    ExampleRecord,
    ExamplesReport,
    clean_example,
    integrate_examples,
)
from pipeline.identity.identity import MasterSense
from pipeline.storage.sqlite_store import ConstructionStore


def _sense() -> MasterSense:
    return MasterSense(
        headword_display="bank",
        headword_search="bank",
        pos_canonical="noun",
        sense_key="bank|noun|t",
        gloss_display="financial institution",
        gloss_search="financial institution",
    )


class _Enriched:
    def __init__(self, sense: MasterSense) -> None:
        self.sense = sense
        self.cefr_level = None
        self.cefr_confidence = 0.0
        self.cefr_conflict = False
        self.frequency_rank = None
        self.frequency_band = None


class TestCleanExample:
    def test_collapses_whitespace(self) -> None:
        assert clean_example("  he   went\n\thome  ") == "he went home"

    def test_rejects_short_and_long(self) -> None:
        assert clean_example("ok") is None  # < 3 chars
        assert clean_example("x" * 301) is None
        assert clean_example("x" * 300) is not None

    def test_rejects_punctuation_only(self) -> None:
        assert clean_example(". . .") is None
        assert clean_example("--!?") is None

    def test_rejects_none_and_keeps_polish(self) -> None:
        assert clean_example(None) is None
        assert clean_example("Zszedł po schodach do domu") is not None


class TestIntegrateExamples:
    def test_merges_sources_wikt_first(self) -> None:
        records, report = integrate_examples(
            {"a|noun|t": ["He paid at the bank."]},
            {"a|noun|t": ["The bank was steep."]},
        )
        assert [r.source for r in records] == ["wiktextract", "wordnet"]
        assert [r.position for r in records] == [1, 2]
        assert report.records == 2
        assert report.senses_with_examples == 1

    def test_dedup_casefolded_first_wins(self) -> None:
        records, report = integrate_examples(
            {"a|noun|t": ["Sit by the river bank.", "SIT BY THE RIVER BANK."]},
        )
        assert len(records) == 1
        assert report.dropped_duplicate == 1
        assert records[0].text == "Sit by the river bank."

    def test_cap_five(self) -> None:
        texts = [f"example number {i} here" for i in range(1, 9)]
        records, report = integrate_examples({"a|noun|t": texts})
        assert len(records) == 5
        assert [r.position for r in records] == [1, 2, 3, 4, 5]
        assert report.dropped_over_cap == 3

    def test_unclean_dropped(self) -> None:
        records, report = integrate_examples(
            {"a|noun|t": ["ok", ". . .", "A valid example sentence."]}
        )
        assert len(records) == 1
        assert report.dropped_unclean == 2

    def test_deterministic_and_sorted_keys(self) -> None:
        wikt = {"b|noun|t": ["for b one"], "a|noun|t": ["for a one"]}
        r1, rep1 = integrate_examples(wikt)
        r2, rep2 = integrate_examples(dict(reversed(list(wikt.items()))))
        assert [r.sense_key for r in r1] == ["a|noun|t", "b|noun|t"]
        assert [(r.sense_key, r.position, r.text) for r in r1] == [
            (r.sense_key, r.position, r.text) for r in r2
        ]
        assert rep1.as_dict() == rep2.as_dict()

    def test_report_counts(self) -> None:
        records, report = integrate_examples({"a|noun|t": ["one example here"]})
        assert report.senses_in_input == 1
        assert report.records == len(records)
        assert report.version == EXAMPLES_VERSION == "ex-v1"
        assert isinstance(report, ExamplesReport)


class TestExamplesStore:
    def test_roundtrip_and_full_refresh(self, tmp_path) -> None:
        store = ConstructionStore(tmp_path / "c.sqlite")
        store.upsert_senses([_Enriched(_sense())])
        recs = [
            ExampleRecord("bank|noun|t", 1, "first example", "wiktextract"),
            ExampleRecord("bank|noun|t", 2, "second example", "wordnet"),
        ]
        assert store.upsert_examples(recs) == 2
        assert store.count_examples() == {
            "records": 2,
            "senses": 1,
            "from_wiktextract": 1,
            "from_wordnet": 1,
        }
        # full refresh replaces prior rows
        assert store.upsert_examples([recs[0]]) == 1
        assert store.count_examples()["records"] == 1
        rows = store.conn.execute(
            "SELECT position, text, source FROM sense_examples"
        ).fetchall()
        assert rows == [(1, "first example", "wiktextract")]
        store.close()
