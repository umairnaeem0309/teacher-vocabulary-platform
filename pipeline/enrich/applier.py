"""Enrichment applier (Phase 7): master senses in, enriched senses out."""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.enrich.cefr import CefrDecision, reconcile_cefr
from pipeline.enrich.frequency import FrequencyDecision, reconcile_frequency
from pipeline.records import RecordStats


@dataclass
class EnrichedSense:
    """A master sense plus reconciled CEFR/frequency (wrapper around merge)."""

    sense: object  # MasterSense
    cefr: CefrDecision
    frequency: FrequencyDecision

    # Convenience accessors used by later phases/UI.
    @property
    def cefr_level(self) -> str | None:
        return self.cefr.level

    @property
    def cefr_confidence(self) -> float:
        return self.cefr.cefr_confidence

    @property
    def cefr_conflict(self) -> bool:
        return self.cefr.conflict

    @property
    def frequency_rank(self) -> int | None:
        return self.frequency.rank

    @property
    def frequency_band(self) -> str | None:
        return self.frequency.band


@dataclass
class EnrichmentReport:
    """Machine-readable enrichment summary (sections 45, 126)."""

    stats: RecordStats = field(default_factory=RecordStats)
    cefr_levels: dict = field(default_factory=dict)
    cefr_conflicts: int = 0
    cefr_unknown: int = 0
    frequency_unknown: int = 0
    frequency_duplicates_dropped: int = 0


def enrich_senses(senses: list) -> tuple[list[EnrichedSense], EnrichmentReport]:
    """Attach reconciled CEFR + frequency decisions to every master sense."""
    report = EnrichmentReport()
    out: list[EnrichedSense] = []

    for sense in senses:
        report.stats.read += 1
        cefr = reconcile_cefr(sense.cefr_evidence, sense.pos_canonical)
        freq = reconcile_frequency(sense.frequency_evidence)
        out.append(EnrichedSense(sense=sense, cefr=cefr, frequency=freq))

        if cefr.level:
            report.cefr_levels[cefr.level] = report.cefr_levels.get(cefr.level, 0) + 1
        else:
            report.cefr_unknown += 1
        if cefr.conflict:
            report.cefr_conflicts += 1
        if freq.rank is None:
            report.frequency_unknown += 1
        report.frequency_duplicates_dropped += freq.duplicates_dropped
        report.stats.processed += 1

    return out, report
