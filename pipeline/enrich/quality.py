"""Quality indicators (Phase 11, section 87).

Every sense carries eight indicators — the §87 minimum set — computed
deterministically from stored evidence. Indicators describe what evidence
EXISTS; they never delete or demote a sense (incomplete senses stay, per
§87: "do not delete incomplete senses").

Indicators (qual-v1):

- translation_available: any Polish translation assigned to the sense;
- translation_confidence: mean D007 alignment confidence (0.0 when none);
- definition_available: gloss present (definition text from Phase 5/6);
- example_available: ≥ 1 integrated example (Phase 11 examples table);
- cefr_available: reconciled CEFR level present (D009);
- frequency_available: NGSL rank present (D009);
- category_confidence: best sense_categories confidence (0.0 when none);
- sense_confidence: composite 0..1 quality-of-evidence score (below).

The composite is deliberately NOT the Phase 10 priority (which answers
"teach this first?"): it answers "how much evidence supports this sense
record?", used for review queues and import triage. Missing evidence is
0.0 — honestly empty, never invented (§108, §127).

Composite (weights sum to 1.0):

    sense_confidence = 0.30·translation_side + 0.25·definition_side
                     + 0.20·example_side     + 0.15·cefr_side
                     + 0.10·frequency_side

    translation_side = translation_confidence (mean D007 confidence)
    definition_side  = 1.0 if gloss has ≥ 1 significant token else 0.0
    example_side     = min(1.0, examples / 2)
    cefr_side        = cefr_available (1.0/0.0 — level presence, not value)
    frequency_side   = frequency_available

A sense with no evidence at all scores 0.0 and remains in the platform
with its provenance (§87, §127).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

QUALITY_VERSION = "qual-v1"

_W_TRANSLATION = 0.30
_W_DEFINITION = 0.25
_W_EXAMPLE = 0.20
_W_CEFR = 0.15
_W_FREQUENCY = 0.10


@dataclass
class QualityIndicators:
    """The §87 minimum indicator set for one sense."""

    sense_key: str
    translation_available: bool
    translation_confidence: float
    definition_available: bool
    example_available: bool
    cefr_available: bool
    frequency_available: bool
    category_confidence: float
    sense_confidence: float
    version: str = QUALITY_VERSION

    def as_row(self) -> tuple:
        """Row for the sense_quality table."""
        return (
            self.sense_key,
            int(self.translation_available),
            self.translation_confidence,
            int(self.definition_available),
            int(self.example_available),
            int(self.cefr_available),
            int(self.frequency_available),
            self.category_confidence,
            self.sense_confidence,
            self.version,
        )


@dataclass
class QualityReport:
    """QC summary for the indicator pass (§126)."""

    senses_total: int = 0
    with_translation: int = 0
    with_definition: int = 0
    with_example: int = 0
    with_cefr: int = 0
    with_frequency: int = 0
    with_category: int = 0
    mean_sense_confidence: float = 0.0
    version: str = QUALITY_VERSION

    def as_dict(self) -> dict:
        return {
            "senses_total": self.senses_total,
            "with_translation": self.with_translation,
            "with_definition": self.with_definition,
            "with_example": self.with_example,
            "with_cefr": self.with_cefr,
            "with_frequency": self.with_frequency,
            "with_category": self.with_category,
            "mean_sense_confidence": round(self.mean_sense_confidence, 4),
            "version": self.version,
        }


def significant_token_count(gloss: str) -> int:
    """Tokens with >= 2 alphanumeric characters (same rule as prio-v1.1)."""
    count = 0
    for token in (gloss or "").split():
        if sum(1 for ch in token if ch.isalnum()) >= 2:
            count += 1
    return count


def compute_quality(
    sense_key: str,
    translation_confidences: list[float],
    gloss: str,
    examples_count: int,
    cefr_level: str | None,
    frequency_rank: int | None,
    category_confidence: float,
) -> QualityIndicators:
    """Deterministic indicators for one sense; missing evidence stays 0/False."""
    translation_available = bool(translation_confidences)
    translation_conf = (
        round(sum(translation_confidences) / len(translation_confidences), 4)
        if translation_available
        else 0.0
    )
    definition_available = significant_token_count(gloss) >= 1
    example_available = examples_count > 0
    cefr_available = cefr_level is not None
    frequency_available = frequency_rank is not None

    composite = (
        _W_TRANSLATION * translation_conf
        + _W_DEFINITION * (1.0 if definition_available else 0.0)
        + _W_EXAMPLE * min(1.0, examples_count / 2)
        + _W_CEFR * (1.0 if cefr_available else 0.0)
        + _W_FREQUENCY * (1.0 if frequency_available else 0.0)
    )
    sense_confidence = round(min(1.0, max(0.0, composite)), 4)

    return QualityIndicators(
        sense_key=sense_key,
        translation_available=translation_available,
        translation_confidence=translation_conf,
        definition_available=definition_available,
        example_available=example_available,
        cefr_available=cefr_available,
        frequency_available=frequency_available,
        category_confidence=round(min(1.0, max(0.0, category_confidence)), 4),
        sense_confidence=sense_confidence,
    )


def _field(row: object, key: str) -> Any:
    """Read a field from a dict row or attribute row; never raises.

    Row shape is duck-typed by contract (see compute_quality_batch); Any
    here is the honest type for that boundary.
    """
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def compute_quality_batch(rows: list) -> tuple[list[QualityIndicators], QualityReport]:
    """Compute indicators for many senses.

    Each row needs: sense_key, translation_confidences (list of float),
    gloss, examples_count, cefr_level, frequency_rank,
    category_confidence.
    """
    indicators: list[QualityIndicators] = []
    report = QualityReport()
    conf_sum = 0.0
    for row in rows:
        ind = compute_quality(
            sense_key=str(_field(row, "sense_key")),
            translation_confidences=_field(row, "translation_confidences") or [],
            gloss=_field(row, "gloss") or "",
            examples_count=_field(row, "examples_count") or 0,
            cefr_level=_field(row, "cefr_level"),
            frequency_rank=_field(row, "frequency_rank"),
            category_confidence=_field(row, "category_confidence") or 0.0,
        )
        indicators.append(ind)
        report.senses_total += 1
        report.with_translation += ind.translation_available
        report.with_definition += ind.definition_available
        report.with_example += ind.example_available
        report.with_cefr += ind.cefr_available
        report.with_frequency += ind.frequency_available
        report.with_category += ind.category_confidence > 0.0
        conf_sum += ind.sense_confidence
    report.mean_sense_confidence = (
        conf_sum / report.senses_total if report.senses_total else 0.0
    )
    return indicators, report


def indicators_json(ind: QualityIndicators) -> str:
    """Stable JSON rendering for PG import / UI transport."""
    return json.dumps(
        {
            "translation_available": ind.translation_available,
            "translation_confidence": ind.translation_confidence,
            "definition_available": ind.definition_available,
            "example_available": ind.example_available,
            "cefr_available": ind.cefr_available,
            "frequency_available": ind.frequency_available,
            "category_confidence": ind.category_confidence,
            "sense_confidence": ind.sense_confidence,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
