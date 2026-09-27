"""Phase 10 tests: deterministic vocabulary priority (D012, prio-v1.1)."""

import json

import pytest
from pipeline.enrich.priority import (
    PRIORITY_VERSION,
    PriorityResult,
    frequency_component,
    learner_component,
    level_for_score,
    penalty_component,
    polish_component,
    score_sense,
    score_senses,
    significant_gloss_tokens,
)
from pipeline.identity.identity import MasterSense
from pipeline.storage.sqlite_store import ConstructionStore


class _T:
    def __init__(self, confidence: float) -> None:
        self.confidence = confidence


def _sense(**kwargs):
    base = dict(
        headword_display="bank",
        headword_search="bank",
        pos_canonical="noun",
        sense_key="bank|noun|t",
        gloss_display="financial institution",
        gloss_search="financial institution",
    )
    base.update(kwargs)
    return MasterSense(**base)


class TestComponents:
    def test_frequency_curve(self) -> None:
        # NGSL-tuned power curve (D012): rank 1 -> 1.0, monotonically
        # decreasing, floor in the far tail.
        assert frequency_component(None) == 0.5
        assert frequency_component(1) == 1.0
        assert frequency_component(10) == pytest.approx(0.8511, abs=1e-3)
        assert frequency_component(100) == pytest.approx(0.7244, abs=1e-3)
        assert frequency_component(1000) > frequency_component(2801)
        assert frequency_component(1000) > 0.5
        assert frequency_component(60000) == frequency_component(999999)
        assert 0.0 < frequency_component(60000) < 0.4

    def test_learner_relevance_not_difficulty(self) -> None:
        # A1 remains highest; C2 is never disqualified (§14).
        assert learner_component("A1") == 1.0
        assert learner_component("A1") > learner_component("B1")
        assert learner_component("C2") >= 0.55
        assert learner_component(None) == 0.5

    def test_polish_component(self) -> None:
        # Missing Polish evidence is neutral, not a penalty (§127).
        assert polish_component([]) == 0.5
        assert polish_component([_T(0.95), _T(0.75)]) == pytest.approx(0.85)

    def test_weights_sum_to_one(self) -> None:
        r = score_sense("x|n|t", None, None, [], 0, 0, False, [])
        w = r.components["weights"]
        assert w["frequency"] + w["learner"] + w["polish"] + w["quality"] == pytest.approx(1.0)

    def test_all_neutral_is_neutral_floor_low(self) -> None:
        # By construction: every signal neutral -> 0.35 (LOW). Quality is
        # presence-based positive evidence, so the neutral floor sits at
        # LOW; absence of evidence is never scored as VERY LOW (§127).
        r = score_sense("x|noun|t", None, None, [], 0, 0, False, [])
        assert r.score == pytest.approx(0.35)
        assert r.level == "LOW"

    def test_penalty_component(self) -> None:
        assert penalty_component([]) == 1.0
        assert penalty_component(["obsolete"]) == pytest.approx(0.5)
        assert penalty_component(["slang"]) == pytest.approx(0.75)
        # slur-class markers are hard (prio-v1.1 audit): no stacking among
        # themselves, but they do combine with soft markers.
        assert penalty_component(["slur"]) == pytest.approx(0.5)
        assert penalty_component(["derogatory", "offensive"]) == pytest.approx(0.5)
        assert penalty_component(["slur", "slang"]) == pytest.approx(0.375)
        # hard markers do not stack with each other (set semantics);
        # soft markers multiply: 0.5 * 0.75^2 = 0.28125.
        assert penalty_component(["obsolete", "slang", "technical"]) == pytest.approx(0.28125)
        assert penalty_component(["obsolete", "archaic"]) == pytest.approx(0.5)
        assert penalty_component(["slang", "vulgar", "technical"]) == pytest.approx(0.421875)


class TestLevels:
    def test_threshold_order(self) -> None:
        assert level_for_score(0.9) == "VERY HIGH"
        assert level_for_score(0.70) == "VERY HIGH"
        assert level_for_score(0.69) == "HIGH"
        assert level_for_score(0.55) == "HIGH"
        assert level_for_score(0.40) == "MEDIUM"
        assert level_for_score(0.25) == "LOW"
        assert level_for_score(0.1) == "VERY LOW"

    def test_all_five_levels_exist(self) -> None:
        scores = [0.9, 0.65, 0.5, 0.35, 0.1]
        assert {level_for_score(s) for s in scores} == {
            "VERY HIGH", "HIGH", "MEDIUM", "LOW", "VERY LOW",
        }


class TestScoring:
    def test_common_simple_sense_scores_high(self) -> None:
        r = score_sense(
            "bank|noun|t", frequency_rank=250, cefr_level="A2",
            translations=[_T(0.95)], examples_count=2, gloss_tokens=3,
            wordnet_linked=True, tags=[],
        )
        assert r.score >= 0.70
        assert r.level == "VERY HIGH"

    def test_flagged_obsolete_rare_sense_scores_low(self) -> None:
        r = score_sense(
            "hest|noun|t", frequency_rank=None, cefr_level=None,
            translations=[], examples_count=0, gloss_tokens=1,
            wordnet_linked=False, tags=["obsolete"],
        )
        assert r.score < 0.30
        assert r.level == "VERY LOW"

    def test_c2_word_can_score_high(self) -> None:
        # §14: a C2 word with strong other signals is NOT disqualified.
        r = score_sense(
            "nuance|noun|t", frequency_rank=3000, cefr_level="C2",
            translations=[_T(0.95)], examples_count=2, gloss_tokens=4,
            wordnet_linked=True, tags=[],
        )
        assert r.level in ("HIGH", "VERY HIGH")

    def test_missing_signals_are_neutral_not_punished(self) -> None:
        no_evidence = score_sense(
            "xyz|noun|t", None, None, [], 0, 0, False, []
        )
        with_frequency = score_sense(
            "xyz|noun|t", 100, None, [], 0, 0, False, []
        )
        assert no_evidence.score < with_frequency.score
        assert 0.2 < no_evidence.score < 0.55

    def test_explainability_components_recorded(self) -> None:
        r = score_sense(
            "bank|noun|t", 250, "A2", [_T(0.9)], 2, 3, True, []
        )
        c = r.components
        assert c["frequency"] == frequency_component(250)
        assert c["learner"] == learner_component("A2")
        assert c["inputs"]["frequency_rank"] == 250
        assert c["weights"]["frequency"] == 0.35
        # components JSON round-trips for PG import
        parsed = json.loads(r.components_json())
        assert parsed["polish"] == 0.9

    def test_determinism(self) -> None:
        args = ("bank|noun|t", 250, "A2", [_T(0.9)], 2, 3, True, [])
        r1 = score_sense(*args)
        r2 = score_sense(*args)
        assert r1.score == r2.score
        assert r1.components == r2.components

    def test_significant_gloss_tokens(self) -> None:
        # prio-v1.1: punctuation and apostrophe fragments are not depth.
        assert significant_gloss_tokens("") == 0
        assert significant_gloss_tokens(". . .") == 0
        assert significant_gloss_tokens("financial institution") == 2
        # single-char and apostrophe fragments don't count
        assert significant_gloss_tokens("a lady s maid") == 2  # lady, maid
        assert significant_gloss_tokens("the digit 1") == 2  # the, digit

    def test_slur_sense_never_very_high(self) -> None:
        # prio-v1.1 audit: a slur sense of a common word must not sit at
        # the top of the teaching queue (brown "dark-skinned" case).
        r = score_sense(
            "brown|adj|t", frequency_rank=1913, cefr_level="A2",
            translations=[], examples_count=2, gloss_tokens=35,
            wordnet_linked=True, tags=["slur", "ethnic", "informal"],
        )
        assert r.level in ("LOW", "VERY LOW")
        assert r.components["penalty_factor"] == pytest.approx(0.5)

    def test_version_is_prio_v1_1(self) -> None:
        r = score_sense("x|noun|t", None, None, [], 0, 0, False, [])
        assert r.version == PRIORITY_VERSION == "prio-v1.1"


class TestBatch:
    def test_score_senses_report(self) -> None:
        rows = [
            {
                "sense_key": "a|noun|t", "frequency_rank": 100,
                "cefr_level": "A1", "translations": [_T(0.9)],
                "examples_count": 1, "gloss_tokens": 3,
                "wordnet_linked": True, "tags": [],
            },
            {
                "sense_key": "b|noun|t", "frequency_rank": None,
                "cefr_level": None, "translations": [],
                "examples_count": 0, "gloss_search": "one word",
                "wordnet_linked": False, "tags": ["archaic"],
            },
        ]
        results, report = score_senses(rows)
        assert len(results) == 2
        assert report.senses_total == 2
        assert report.scored == 2
        assert sum(report.levels.values()) == 2
        assert report.version == PRIORITY_VERSION
        assert results[0].score > results[1].score


class TestPriorityStore:
    def test_roundtrip_and_version_history(self, tmp_path) -> None:
        store = ConstructionStore(tmp_path / "c.sqlite")
        store.upsert_senses([_Enriched(_sense())])
        r1 = score_sense("bank|noun|t", 250, "A2", [_T(0.9)], 2, 3, True, [])
        assert store.upsert_priorities([r1]) == 1
        counts = store.count_priorities()
        assert counts == {"rows": 1, "senses": 1, "versions": 1}
        # A later formula version adds rows, never destroys history (§86).
        r2 = PriorityResult(
            sense_key="bank|noun|t", score=0.7, level="HIGH",
            version="prio-v2", components={"note": "new formula"},
        )
        store.upsert_priorities([r2])
        counts = store.count_priorities()
        assert counts == {"rows": 2, "senses": 1, "versions": 2}
        row = store.conn.execute(
            "SELECT level FROM sense_priorities WHERE version=?",
            (PRIORITY_VERSION,),
        ).fetchone()
        assert row == ("VERY HIGH",)  # score 0.8528: rank 250 + A2 + polish 0.9 + full quality
        store.close()

    def test_old_version_rows_survive_new_run(self, tmp_path) -> None:
        # D012 audit addendum: re-running the pipeline with the current
        # version replaces only its own rows; older versions' rows survive
        # for historical explainability (section 86).
        store = ConstructionStore(tmp_path / "c.sqlite")
        store.upsert_senses([_Enriched(_sense())])
        r1 = score_sense("bank|noun|t", 250, "A2", [_T(0.9)], 2, 3, True, [])
        store.upsert_priorities([r1])
        r_old = PriorityResult(
            sense_key="bank|noun|t", score=0.7412, level="VERY HIGH",
            version="prio-v1", components={"note": "pre-audit formula"},
        )
        store.upsert_priorities([r_old])
        r_new = score_sense("bank|noun|t", 100, "A1", [_T(0.9)], 2, 3, True, [])
        store.upsert_priorities([r_new])  # replaces r1, not r_old
        counts = store.count_priorities()
        assert counts == {"rows": 2, "senses": 1, "versions": 2}
        row = store.conn.execute(
            "SELECT score FROM sense_priorities WHERE version='prio-v1'"
        ).fetchone()
        assert row == (pytest.approx(0.7412),)
        store.close()

    def test_components_json_stored(self, tmp_path) -> None:
        store = ConstructionStore(tmp_path / "c.sqlite")
        store.upsert_senses([_Enriched(_sense())])
        r = score_sense("bank|noun|t", 100, "A1", [], 0, 2, False, ["slang"])
        store.upsert_priorities([r])
        raw = store.conn.execute(
            "SELECT components_json FROM sense_priorities"
        ).fetchone()[0]
        parsed = json.loads(raw)
        assert parsed["inputs"]["tags"] == ["slang"]
        assert parsed["penalty_factor"] == pytest.approx(0.75)
        store.close()


class _Enriched:
    def __init__(self, sense) -> None:
        self.sense = sense
        self.cefr_level = None
        self.cefr_confidence = 0.0
        self.cefr_conflict = False
        self.frequency_rank = None
        self.frequency_band = None
