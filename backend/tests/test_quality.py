"""Phase 11 tests: quality indicators (qual-v1, section 87)."""

import json

import pytest
from pipeline.enrich.quality import (
    QUALITY_VERSION,
    compute_quality,
    compute_quality_batch,
    indicators_json,
    significant_token_count,
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


class TestSignificantTokens:
    def test_same_rule_as_priority(self) -> None:
        assert significant_token_count("") == 0
        assert significant_token_count(". . .") == 0
        assert significant_token_count("a lady s maid") == 2
        assert significant_token_count("financial institution") == 2


class TestComputeQuality:
    def test_full_evidence(self) -> None:
        ind = compute_quality(
            "a|noun|t",
            translation_confidences=[0.9, 0.8],
            gloss="financial institution",
            examples_count=3,
            cefr_level="A2",
            frequency_rank=627,
            category_confidence=0.85,
        )
        assert ind.translation_available is True
        assert ind.translation_confidence == pytest.approx(0.85)
        assert ind.definition_available is True
        assert ind.example_available is True
        assert ind.cefr_available is True
        assert ind.frequency_available is True
        assert ind.category_confidence == pytest.approx(0.85)
        # 0.3*0.85 + 0.25 + 0.2 + 0.15 + 0.1 = 0.955
        assert ind.sense_confidence == pytest.approx(0.955)
        assert ind.version == QUALITY_VERSION == "qual-v1"

    def test_no_evidence_is_zero_not_deleted(self) -> None:
        # §87: do not delete incomplete senses — they score 0.0 honestly.
        ind = compute_quality("x|noun|t", [], "", 0, None, None, 0.0)
        assert ind.sense_confidence == 0.0
        assert not any(
            (ind.translation_available, ind.definition_available,
             ind.example_available, ind.cefr_available, ind.frequency_available)
        )
        assert ind.as_row()[1:] == (
            0, 0.0, 0, 0, 0, 0, 0.0, 0.0, "qual-v1",
        )[:9]

    def test_clamps(self) -> None:
        ind = compute_quality("x|noun|t", [], "def", 5, "A1", 1, 2.0)
        assert ind.category_confidence == 1.0
        assert ind.sense_confidence <= 1.0

    def test_example_side_saturates_at_two(self) -> None:
        one = compute_quality("x|noun|t", [], "definition gloss here", 1, None, None, 0.0)
        two = compute_quality("x|noun|t", [], "definition gloss here", 2, None, None, 0.0)
        five = compute_quality("x|noun|t", [], "definition gloss here", 5, None, None, 0.0)
        assert five.sense_confidence == two.sense_confidence
        assert two.sense_confidence > one.sense_confidence

    def test_punctuation_gloss_is_not_a_definition(self) -> None:
        ind = compute_quality("x|noun|t", [], ". - .", 0, None, None, 0.0)
        assert ind.definition_available is False

    def test_translation_confidence_is_mean(self) -> None:
        ind = compute_quality("x|noun|t", [1.0, 0.5], "gloss", 0, None, None, 0.0)
        assert ind.translation_confidence == pytest.approx(0.75)
        assert ind.translation_available is True


class TestBatch:
    def test_batch_and_report(self) -> None:
        rows = [
            {
                "sense_key": "a|noun|t", "translation_confidences": [0.9],
                "gloss": "gloss here", "examples_count": 1,
                "cefr_level": "A1", "frequency_rank": 100,
                "category_confidence": 0.8,
            },
            {
                "sense_key": "b|noun|t", "translation_confidences": [],
                "gloss": "", "examples_count": 0,
                "cefr_level": None, "frequency_rank": None,
                "category_confidence": 0.0,
            },
        ]
        indicators, report = compute_quality_batch(rows)
        assert len(indicators) == 2
        assert report.senses_total == 2
        assert report.with_translation == 1
        assert report.with_definition == 1
        assert report.with_example == 1
        assert report.with_cefr == 1
        assert report.with_frequency == 1
        assert report.with_category == 1
        assert report.version == "qual-v1"
        assert indicators[0].sense_confidence > indicators[1].sense_confidence

    def test_object_rows(self) -> None:
        class R:
            sense_key = "o|noun|t"
            translation_confidences = [0.7]
            gloss = "definition"
            examples_count = 1
            cefr_level = "B1"
            frequency_rank = None
            category_confidence = 0.0

        indicators, report = compute_quality_batch([R()])
        assert indicators[0].translation_confidence == pytest.approx(0.7)
        assert report.senses_total == 1


class TestJson:
    def test_indicators_json_roundtrip(self) -> None:
        ind = compute_quality("a|noun|t", [0.9], "gloss", 1, "A1", 5, 0.8)
        parsed = json.loads(indicators_json(ind))
        assert parsed["translation_available"] is True
        assert parsed["translation_confidence"] == pytest.approx(0.9)
        assert parsed["category_confidence"] == pytest.approx(0.8)
        assert indicators_json(ind) == indicators_json(ind)  # stable


class TestQualityStore:
    def test_roundtrip_and_replace(self, tmp_path) -> None:
        store = ConstructionStore(tmp_path / "c.sqlite")
        store.upsert_senses([_Enriched(_sense())])
        ind = compute_quality("bank|noun|t", [0.9], "gloss here", 1, "A1", 10, 0.8)
        assert store.upsert_quality([ind]) == 1
        assert store.count_quality()["senses"] == 1
        assert store.count_quality()["mean_sense_confidence"] == pytest.approx(
            ind.sense_confidence
        )
        row = store.conn.execute(
            "SELECT translation_available, cefr_available, sense_confidence, version "
            "FROM sense_quality WHERE sense_key='bank|noun|t'"
        ).fetchone()
        assert row == (1, 1, ind.sense_confidence, "qual-v1")
        # replace semantics: one current row per sense
        ind2 = compute_quality("bank|noun|t", [], "", 0, None, None, 0.0)
        store.upsert_quality([ind2])
        assert store.count_quality()["senses"] == 1
        assert store.conn.execute(
            "SELECT sense_confidence FROM sense_quality"
        ).fetchone()[0] == 0.0
        store.close()
