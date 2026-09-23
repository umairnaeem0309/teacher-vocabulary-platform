"""CEFR reconciliation (Phase 7, section 14).

Rules (D009):

1. Evidence items are (source, cefr, pos_raw). Only evidence whose POS maps
   to the sense's canonical POS is preferred; mismatched-POS evidence is
   kept but does not drive the normalized value.
2. If preferred evidence agrees (single source or unanimous) -> that level
   with confidence 0.95 (unanimous multi-source) or 0.85 (single source).
3. If preferred evidence conflicts -> pick the HIGHER level (leaning
   easier-side assumption is wrong for teaching: showing a B2 word as A2
   invites teaching it too early; the reverse is safe) with confidence
   0.5, and set ``cefr_conflict=True`` so the conflict stays visible.
4. No usable evidence -> None (unknown), confidence 0. Never invented
   (section 108).

All source evidence is preserved upstream in ``cefr_evidence`` regardless
of reconciliation outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.normalize.pos import canonical_pos

CEFR_ORDER = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}

CONF_UNANIMOUS = 0.95
CONF_SINGLE = 0.85
CONF_CONFLICT = 0.50


@dataclass
class CefrDecision:
    """Reconciled CEFR output for one sense."""

    level: str | None = None
    confidence: float = 0.0
    conflict: bool = False
    agreeing_sources: list[str] = field(default_factory=list)
    conflicting_sources: list[str] = field(default_factory=list)
    rule: str = "none"  # none | unanimous | single | conflict-higher

    @property
    def cefr_confidence(self) -> float:
        return self.confidence


def _pos_matches(evidence_pos_raw: str, sense_pos: str) -> bool:
    return canonical_pos(evidence_pos_raw) == sense_pos


def reconcile_cefr(
    evidence: list[dict],
    sense_pos: str,
) -> CefrDecision:
    """Reconcile CEFR evidence dicts: {source, cefr, pos_raw}."""
    usable = [
        e for e in evidence
        if e.get("cefr") in CEFR_ORDER and _pos_matches(e.get("pos_raw", ""), sense_pos)
    ]
    if not usable:
        # nothing POS-matched: fall back to any evidence but mark rule
        usable = [e for e in evidence if e.get("cefr") in CEFR_ORDER]
        if not usable:
            return CefrDecision(rule="none")
        decision = _decide(usable)
        decision.confidence = min(decision.confidence, CONF_SINGLE)
        decision.rule = f"pos-mismatch:{decision.rule}"
        return decision
    return _decide(usable)


def _decide(usable: list[dict]) -> CefrDecision:
    levels = {e["cefr"] for e in usable}
    sources = sorted({e.get("source", "?") for e in usable})
    if len(levels) == 1:
        level = levels.pop()
        if len(sources) > 1:
            return CefrDecision(
                level=level, confidence=CONF_UNANIMOUS, conflict=False,
                agreeing_sources=sources, rule="unanimous",
            )
        return CefrDecision(
            level=level, confidence=CONF_SINGLE, conflict=False,
            agreeing_sources=sources, rule="single",
        )
    # Conflict: preserve visibility, choose the higher level (D009 rule 3).
    level = max(levels, key=lambda c: CEFR_ORDER[c])
    conflicting = sorted(
        {e.get("source", "?") for e in usable if e["cefr"] != level}
    )
    return CefrDecision(
        level=level, confidence=CONF_CONFLICT, conflict=True,
        agreeing_sources=sorted(
            {e.get("source", "?") for e in usable if e["cefr"] == level}
        ),
        conflicting_sources=conflicting,
        rule="conflict-higher",
    )
