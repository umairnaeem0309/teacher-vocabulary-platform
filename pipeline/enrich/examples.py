"""Example integration (Phase 11, section 87).

Wiktextract sense examples arrive through the identity layer as
``MasterSense.examples_display`` (stored as ``examples_json``). WordNet
synsets carry their own examples, reachable through the Phase 8 sense
links. This module integrates both into one deduplicated, capped, ordered
list per sense (ex-v1):

- cleaning: whitespace collapse, length bounds (3..300), must contain an
  alphanumeric character;
- deduplication: casefolded text, first occurrence wins;
- source order: Wiktextract sense examples first (they illustrate the
  actual sense), then WordNet synset examples via the link;
- cap: 5 examples per sense (display economics for the teacher UI);
- provenance: every record keeps its source, nothing silently merged.

Integration is a full refresh: re-running replaces all rows (the result
is a pure function of the inputs, like taxonomy assignments).
"""

from __future__ import annotations

from dataclasses import dataclass

EXAMPLES_VERSION = "ex-v1"

_MIN_LEN = 3
_MAX_LEN = 300
_CAP = 5

_SOURCE_WIKT = "wiktextract"
_SOURCE_WORDNET = "wordnet"


@dataclass
class ExampleRecord:
    """One integrated example for one sense (position is 1-based)."""

    sense_key: str
    position: int
    text: str
    source: str


@dataclass
class ExamplesReport:
    """QC summary for the integration pass (§126)."""

    senses_in_input: int = 0
    records: int = 0
    senses_with_examples: int = 0
    dropped_unclean: int = 0
    dropped_duplicate: int = 0
    dropped_over_cap: int = 0
    version: str = EXAMPLES_VERSION

    def as_dict(self) -> dict:
        return {
            "senses_in_input": self.senses_in_input,
            "records": self.records,
            "senses_with_examples": self.senses_with_examples,
            "dropped_unclean": self.dropped_unclean,
            "dropped_duplicate": self.dropped_duplicate,
            "dropped_over_cap": self.dropped_over_cap,
            "version": self.version,
        }


def clean_example(text: object) -> str | None:
    """Normalize one example string; None when unusable (never raises)."""
    if text is None:
        return None
    collapsed = " ".join(str(text).split())
    if len(collapsed) < _MIN_LEN or len(collapsed) > _MAX_LEN:
        return None
    if not any(ch.isalnum() for ch in collapsed):
        return None
    return collapsed


def integrate_examples(
    wikt_examples: dict[str, list],
    wordnet_examples: dict[str, list] | None = None,
) -> tuple[list[ExampleRecord], ExamplesReport]:
    """Merge per-sense example lists into ordered ExampleRecords.

    ``wikt_examples`` / ``wordnet_examples`` map sense_key -> list of raw
    example texts (wordnet via the sense's linked synsets, in link order).
    Deterministic: senses processed in sorted key order, sources in the
    fixed order above, first occurrence wins.
    """
    report = ExamplesReport()
    records: list[ExampleRecord] = []
    wordnet_examples = wordnet_examples or {}
    keys = sorted(set(wikt_examples) | set(wordnet_examples))
    report.senses_in_input = len(keys)

    for sense_key in keys:
        seen: set[str] = set()
        position = 0
        for source, texts in (
            (_SOURCE_WIKT, wikt_examples.get(sense_key) or []),
            (_SOURCE_WORDNET, wordnet_examples.get(sense_key) or []),
        ):
            for raw in texts:
                cleaned = clean_example(raw)
                if cleaned is None:
                    report.dropped_unclean += 1
                    continue
                folded = cleaned.casefold()
                if folded in seen:
                    report.dropped_duplicate += 1
                    continue
                if position >= _CAP:
                    report.dropped_over_cap += 1
                    continue
                position += 1
                seen.add(folded)
                records.append(
                    ExampleRecord(
                        sense_key=sense_key,
                        position=position,
                        text=cleaned,
                        source=source,
                    )
                )
        if position:
            report.senses_with_examples += 1
    report.records = len(records)
    return records, report
