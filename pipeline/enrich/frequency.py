"""Frequency integration (Phase 7, section 15).

Frequency is objective occurrence data, stored separately from priority
(never merged with it — sections 15-16).

Rules (D009):

- Duplicate lemmas (NGSL has none per Phase 3, but the rule guards the
  merge anyway): keep the BEST (lowest) rank; record that a duplicate was
  dropped in stats — never silent (section 45).
- ``frequency_band`` is a coarse, teacher-meaningful bucket derived ONLY
  from rank: top1000, top2000, top3000, beyond. Band is metadata for
  filtering/display, not the priority score (Phase 10 computes that).
"""

from __future__ import annotations

from dataclasses import dataclass

BANDS = [(1000, "top1000"), (2000, "top2000"), (3000, "top3000")]
CONF_EXACT = 0.95  # exact rank from a corpus list


@dataclass
class FrequencyDecision:
    """Reconciled frequency output for one word."""

    rank: int | None = None
    frequency_per_million: float | None = None
    band: str | None = None
    source: str | None = None
    confidence: float = 0.0
    duplicates_dropped: int = 0
    rule: str = "none"  # none | best-rank


def band_for_rank(rank: int | None) -> str | None:
    """Map a corpus rank to a coarse band; None stays None."""
    if rank is None:
        return None
    for upper, name in BANDS:
        if rank <= upper:
            return name
    return "beyond"


def reconcile_frequency(evidence: list[dict]) -> FrequencyDecision:
    """Reconcile frequency evidence dicts: {source, rank, freq}."""
    usable = [e for e in evidence if isinstance(e.get("rank"), int)]
    if not usable:
        return FrequencyDecision()
    usable.sort(key=lambda e: e["rank"])  # best (lowest) rank first
    best = usable[0]
    return FrequencyDecision(
        rank=best["rank"],
        frequency_per_million=best.get("freq"),
        band=band_for_rank(best["rank"]),
        source=best.get("source"),
        confidence=CONF_EXACT,
        duplicates_dropped=len(usable) - 1,
        rule="best-rank",
    )
