"""Vocabulary priority scoring (Phase 10, sections 15-17, 86).

A deterministic, reproducible, explainable score (prio-v1) combining the
available construction-DB signals. Rules from the spec:

- never CEFR alone, never raw frequency alone (§15-16, §86);
- higher CEFR is NOT automatically lower usefulness (§14): CEFR enters as
  a mild learner-relevance prior only, capped at one small component;
- lexical quality/flags matter (§86): obsolete/archaic/etc. penalize;
- multiple signals, every component recorded for explainability (§16).

Signals used in prio-v1 (all normalized to [0, 1] before weighting;
weights sum to 1.0):

- frequency (rank-based, NGSL best rank; 0.35): NGSL-tuned power curve
  rank^-0.07 (rank 1 -> 1.0, 100 -> 0.72, 2801 -> 0.57), None -> 0.5
  neutral;
- learner relevance (CEFR, 0.15): A1..C2 mapped to 1.0..0.55 so a
  beginner word can rank high but a C2 word is never disqualified;
  None -> 0.5 neutral;
- polish usefulness (translation evidence, 0.20): mean D007 alignment
  confidence when Polish translations exist; missing evidence is NEUTRAL
  (0.5), not a penalty — translation coverage grows with the full dump
  and absence of evidence is not evidence of uselessness (§127);
- sense quality (0.30): has example(s) + gloss token count + WordNet
  link present — cheap, objective richness indicators;
- lexical quality penalty (flags, multiplicative): obsolete /
  archaic / rare / technical / slang / internet / alt-of markers
  multiply the score down — 0.5 for a hard marker, 0.75 per soft
  marker, floored at 0.25;

With every signal neutral the score is the neutral floor 0.35 (LOW):
absence of evidence is not scored as uselessness (§127) — VERY LOW is
reserved for senses the lexical-quality penalty pushes below LOW.

Levels are fixed quantile-free thresholds on the final score: VERY HIGH
>= 0.70, HIGH >= 0.55, MEDIUM >= 0.40, LOW >= 0.25, VERY LOW below.
Thresholds are part of the version — changing them bumps prio-vN.

The score is stored internally; the teacher UI shows levels (§16).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

PRIORITY_VERSION = "prio-v1"

# Component weights (documented in D012; must sum to 1.0 before penalty).
_W_FREQUENCY = 0.35
_W_LEARNER = 0.15
_W_POLISH = 0.20
_W_QUALITY = 0.30
_W_FREQUENCY_NEUTRAL = 0.50
_W_LEARNER_NEUTRAL = 0.50
_W_POLISH_NEUTRAL = 0.50

# Hard markers (strong evidence the sense is marginal for learners).
_HARD_MARKERS = frozenset({
    "obsolete", "archaic", "historical", "rare", "rare-sense",
})
# Soft markers (context-dependent but often marginal).
_SOFT_MARKERS = frozenset({
    "technical", "specialized", "slang", "vulgar", "internet",
    "alt-of", "initialism", "abbreviation", "misspelling",
    "pronunciation-spelling", "obsolete-sense", "archaic-sense",
})

# CEFR level -> learner relevance (NOT difficulty; §14/§16).
_LEARNER_RELEVANCE = {"A1": 1.0, "A2": 0.9, "B1": 0.78, "B2": 0.68, "C1": 0.60, "C2": 0.55}

# Frequency rank -> usefulness curve, tuned to the evidence domain:
# our frequency ranks come from NGSL (2,801 lemmas, ranks 1..2801), so
# the curve must spread scores inside that range, not over 20k ranks.
# power curve rank^-0.07: rank 1 -> 1.0, 10 -> 0.8511, 100 -> 0.7244,
# 1000 -> 0.6166, 2801 (NGSL end) -> 0.5737. Ranks far beyond NGSL
# (>= 50k) floor at 0.30.
_RANK_BEYOND = 50000
_FREQ_BEYOND = 0.30

# Level thresholds (part of the version).
LEVELS = ("VERY HIGH", "HIGH", "MEDIUM", "LOW", "VERY LOW")


@dataclass
class PriorityResult:
    """One sense's score with full component breakdown (§16)."""

    sense_key: str
    score: float
    level: str
    version: str = PRIORITY_VERSION
    components: dict = field(default_factory=dict)

    def components_json(self) -> str:
        return json.dumps(self.components, ensure_ascii=False, sort_keys=True)


@dataclass
class PriorityReport:
    """QC summary for the scoring pass (§126)."""

    senses_total: int = 0
    scored: int = 0
    levels: dict = field(default_factory=dict)
    version: str = PRIORITY_VERSION

    def as_dict(self) -> dict:
        return {
            "senses_total": self.senses_total,
            "scored": self.scored,
            "levels": dict(sorted(self.levels.items())),
            "version": self.version,
        }


def level_for_score(score: float) -> str:
    """Fixed thresholds; part of the formula version (D012).

    Recalibrated to the NGSL-tuned frequency curve so core vocabulary
    (rank <= ~300, good Polish + quality) reaches VERY HIGH.
    """
    if score >= 0.70:
        return "VERY HIGH"
    if score >= 0.55:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    if score >= 0.25:
        return "LOW"
    return "VERY LOW"


def frequency_component(rank: int | None) -> float:
    """NGSL-tuned rank curve in [0, 1]; missing rank is neutral.

    rank^-0.07 with a far-tail floor: rank 1 -> 1.0, 10 -> 0.8511,
    100 -> 0.7244, 1000 -> 0.6166, 2801 -> 0.5737. Rewards genuinely
    common words without letting raw frequency dominate (§15); frequency
    is one signal among four (weight 0.35).
    """
    if rank is None:
        return _W_FREQUENCY_NEUTRAL
    rank = max(1, int(rank))
    if rank >= _RANK_BEYOND:
        return _FREQ_BEYOND
    return round(rank ** -0.07, 4)


def learner_component(cefr_level: str | None) -> float:
    """CEFR as mild learner relevance; missing level is neutral."""
    if cefr_level is None:
        return _W_LEARNER_NEUTRAL
    return _LEARNER_RELEVANCE.get(cefr_level, _W_LEARNER_NEUTRAL)


def polish_component(translations: list) -> float:
    """Mean D007 alignment confidence when Polish evidence exists.

    Missing Polish evidence is neutral (0.5), not zero — translation
    coverage is partial and absence of evidence must not be scored as
    evidence of uselessness (§127).
    """
    if not translations:
        return _W_POLISH_NEUTRAL
    confs = [t.confidence for t in translations if getattr(t, "confidence", None) is not None]
    return round(sum(confs) / len(confs), 4) if confs else _W_POLISH_NEUTRAL


def quality_component(
    examples_count: int,
    gloss_tokens: int,
    wordnet_linked: bool,
) -> float:
    """Cheap objective richness: examples + gloss depth + WordNet anchor."""
    score = 0.0
    if examples_count > 0:
        score += 0.4
    if gloss_tokens >= 3:
        score += 0.3
    elif gloss_tokens >= 1:
        score += 0.15
    if wordnet_linked:
        score += 0.3
    return round(score, 4)


def penalty_component(tags: list[str]) -> float:
    """Multiplicative factor in [0.25, 1]; 1.0 = no penalty.

    Hard markers halve the factor; each soft marker shaves 25%. Factors
    combine multiplicatively and floor at 0.25 (never zero: even a
    flagged sense stays reachable, §14). Applied directly to the
    weighted base, so flags move senses across level bands.
    """
    factor = 1.0
    tags_set = {t.strip().lower() for t in tags or []}
    if tags_set & _HARD_MARKERS:
        factor *= 0.5
    soft_hits = len(tags_set & _SOFT_MARKERS)
    factor *= 0.75 ** soft_hits
    return max(factor, 0.25)


def score_sense(
    sense_key: str,
    frequency_rank: int | None,
    cefr_level: str | None,
    translations: list,
    examples_count: int,
    gloss_tokens: int,
    wordnet_linked: bool,
    tags: list[str],
) -> PriorityResult:
    """Deterministic priority for one sense; full breakdown recorded."""
    freq = frequency_component(frequency_rank)
    learner = learner_component(cefr_level)
    polish = polish_component(translations)
    quality = quality_component(examples_count, gloss_tokens, wordnet_linked)
    penalty = penalty_component(tags)

    base = (
        _W_FREQUENCY * freq
        + _W_LEARNER * learner
        + _W_POLISH * polish
        + _W_QUALITY * quality
    )
    score = round(base * penalty, 4)
    score = min(1.0, max(0.0, score))
    return PriorityResult(
        sense_key=sense_key,
        score=score,
        level=level_for_score(score),
        components={
            "frequency": freq,
            "learner": learner,
            "polish": polish,
            "quality": quality,
            "penalty_factor": penalty,
            "weights": {
                "frequency": _W_FREQUENCY,
                "learner": _W_LEARNER,
                "polish": _W_POLISH,
                "quality": _W_QUALITY,
            },
            "inputs": {
                "frequency_rank": frequency_rank,
                "cefr_level": cefr_level,
                "translations": len(translations),
                "examples": examples_count,
                "gloss_tokens": gloss_tokens,
                "wordnet_linked": wordnet_linked,
                "tags": sorted(tags or []),
            },
        },
    )


def _field(row: object, key: str) -> Any:
    """Read a field from a dict row or attribute row; never raises.

    Row shape is duck-typed by contract (see score_senses); Any here is
    the honest type for that boundary.
    """
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def score_senses(rows: list) -> tuple[list[PriorityResult], PriorityReport]:
    """Score a batch of priority-input rows (dicts or objects).

    Each row needs: sense_key, frequency_rank, cefr_level, translations
    (list with .confidence), examples_count, gloss_search or gloss_tokens,
    wordnet_linked, tags.
    """
    report = PriorityReport()
    results: list[PriorityResult] = []
    for row in rows:
        report.senses_total += 1
        gloss = _field(row, "gloss_search") or ""
        gloss_tokens = _field(row, "gloss_tokens")
        result = score_sense(
            sense_key=str(_field(row, "sense_key")),
            frequency_rank=_field(row, "frequency_rank"),
            cefr_level=_field(row, "cefr_level"),
            translations=_field(row, "translations") or [],
            examples_count=_field(row, "examples_count") or 0,
            gloss_tokens=(
                gloss_tokens if gloss_tokens is not None else len(str(gloss).split())
            ),
            wordnet_linked=bool(_field(row, "wordnet_linked")),
            tags=_field(row, "tags") or [],
        )
        results.append(result)
        report.scored += 1
        report.levels[result.level] = report.levels.get(result.level, 0) + 1
    return results, report
