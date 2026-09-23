"""Phase 7 tests: CEFR/frequency reconciliation + construction store (D009)."""

import pytest
from pipeline.enrich.applier import EnrichedSense, enrich_senses
from pipeline.enrich.cefr import reconcile_cefr
from pipeline.enrich.frequency import band_for_rank, reconcile_frequency
from pipeline.identity.identity import MasterSense


def _master(pos="noun", cefr_ev=None, freq_ev=None, gloss="financial institution"):
    return MasterSense(
        headword_display="bank",
        headword_search="bank",
        pos_canonical=pos,
        sense_key=f"bank|{pos}|test",
        gloss_display=gloss,
        gloss_search=gloss,
        cefr_evidence=cefr_ev or [],
        frequency_evidence=freq_ev or [],
    )


class TestCefrReconciliation:
    def test_unknown_when_no_evidence(self) -> None:
        d = reconcile_cefr([], "noun")
        assert d.level is None and d.confidence == 0.0 and d.rule == "none"

    def test_single_source(self) -> None:
        d = reconcile_cefr([{"source": "cefrj", "cefr": "B1", "pos_raw": "noun"}], "noun")
        assert d.level == "B1" and d.confidence == 0.85 and d.rule == "single"

    def test_unanimous_multi_source(self) -> None:
        d = reconcile_cefr(
            [
                {"source": "cefrj", "cefr": "B1", "pos_raw": "noun"},
                {"source": "octanove", "cefr": "B1", "pos_raw": "noun"},
            ],
            "noun",
        )
        assert d.level == "B1" and d.confidence == 0.95 and d.rule == "unanimous"

    def test_conflict_prefers_higher_and_flags(self) -> None:
        d = reconcile_cefr(
            [
                {"source": "cefrj", "cefr": "A2", "pos_raw": "noun"},
                {"source": "octanove", "cefr": "C1", "pos_raw": "noun"},
            ],
            "noun",
        )
        assert d.level == "C1"
        assert d.conflict is True
        assert d.confidence == 0.50
        assert d.rule == "conflict-higher"
        assert "cefrj" in d.conflicting_sources

    def test_pos_mismatched_evidence_downgraded(self) -> None:
        d = reconcile_cefr(
            [{"source": "cefrj", "cefr": "A1", "pos_raw": "verb"}], "noun"
        )
        assert d.level == "A1"
        assert "pos-mismatch" in d.rule
        assert d.confidence <= 0.85

    def test_invalid_levels_ignored(self) -> None:
        d = reconcile_cefr(
            [{"source": "x", "cefr": "ZZ", "pos_raw": "noun"}], "noun"
        )
        assert d.level is None

    @pytest.mark.parametrize(
        "level", ["A1", "A2", "B1", "B2", "C1", "C2"]
    )
    def test_all_levels_accepted(self, level: str) -> None:
        d = reconcile_cefr([{"source": "s", "cefr": level, "pos_raw": "noun"}], "noun")
        assert d.level == level


class TestFrequencyReconciliation:
    def test_unknown_when_empty(self) -> None:
        d = reconcile_frequency([])
        assert d.rank is None and d.band is None and d.rule == "none"

    def test_best_rank_wins_and_counts_duplicates(self) -> None:
        d = reconcile_frequency([
            {"source": "ngsl", "rank": 1500, "freq": 900.0},
            {"source": "ngsl", "rank": 700, "freq": 2500.0},
        ])
        assert d.rank == 700
        assert d.duplicates_dropped == 1
        assert d.rule == "best-rank"

    def test_band_boundaries(self) -> None:
        assert band_for_rank(1) == "top1000"
        assert band_for_rank(1000) == "top1000"
        assert band_for_rank(1001) == "top2000"
        assert band_for_rank(2000) == "top2000"
        assert band_for_rank(2500) == "top3000"
        assert band_for_rank(3000) == "top3000"
        assert band_for_rank(3001) == "beyond"
        assert band_for_rank(None) is None


class TestEnrichApplier:
    def test_attaches_decisions_and_reports(self) -> None:
        senses = [
            _master(
                cefr_ev=[
                    {"source": "cefrj", "cefr": "A2", "pos_raw": "noun"},
                    {"source": "octanove", "cefr": "B2", "pos_raw": "noun"},
                ],
                freq_ev=[{"source": "ngsl", "rank": 850, "freq": 2000.0}],
            ),
            _master(pos="verb", gloss="to deposit money"),
        ]
        enriched, report = enrich_senses(senses)
        assert len(enriched) == 2
        assert all(isinstance(e, EnrichedSense) for e in enriched)
        bank = enriched[0]
        assert bank.cefr_level == "B2" and bank.cefr_conflict
        assert bank.frequency_rank == 850 and bank.frequency_band == "top1000"
        verb = enriched[1]
        assert verb.cefr_level is None and verb.frequency_rank is None
        assert report.cefr_conflicts == 1
        assert report.cefr_unknown == 1
        assert report.frequency_unknown == 1


class TestConstructionStore:
    def test_roundtrip_and_qc(self, tmp_path) -> None:
        from pipeline.storage.sqlite_store import ConstructionStore

        senses = [
            _master(
                cefr_ev=[{"source": "cefrj", "cefr": "B1", "pos_raw": "noun"}],
                freq_ev=[{"source": "ngsl", "rank": 1234, "freq": 900.0}],
            ),
            _master(pos="verb", gloss="to deposit money in a bank"),
        ]
        senses[0].translations = [
            __import__(
                "pipeline.normalize.align", fromlist=["AlignedTranslation"]
            ).AlignedTranslation("bank", 0.5, "cognate")
        ]
        enriched, _ = enrich_senses(senses)

        store = ConstructionStore(tmp_path / "construction.sqlite")
        run_id = store.begin_run("norm-v1")
        inserted = store.upsert_senses(enriched)
        store.finish_run(run_id, {"inserted": inserted})

        assert inserted == 2
        assert store.count_senses() == 2
        assert store.count_translations() == 1
        qc = store.qc_summary()
        assert qc["total_senses"] == 2
        assert qc["with_polish"] == 1
        assert qc["with_cefr"] == 1
        assert qc["cefr_conflicts"] == 0
        assert qc["with_frequency"] == 1

        # idempotent re-import does not duplicate
        store.upsert_senses(enriched)
        assert store.count_senses() == 2
        assert store.count_translations() == 1
        store.close()
