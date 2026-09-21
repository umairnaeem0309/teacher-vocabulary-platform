"""Main normalizer (Phase 5): merge adapter records into NormalizedSense.

This produces the *normalized intermediate model* (section 81) that Phase 6
(sense identity) consumes. Merging rules here are deliberately conservative:

- Wiktextract entries contribute candidate senses (gloss + examples + tags).
- CEFR evidence (CEFR-J/Octanove) is attached at WORD level for now; sense
  matching happens in Phase 6/7 once sense identity exists — the evidence is
  never thrown away (section 14).
- NGSL frequency attaches at lemma level (word-level evidence, section 15).
- Display vs search values are computed here once (section 81).
- Every record carries processing provenance and version.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.normalize.align import (
    ALIGNMENT_VERSION,
    AlignedTranslation,
    AlignmentInput,
    align_translations,
    extract_inline_polish,
)
from pipeline.normalize.clean import clean_display, clean_gloss, search_key
from pipeline.normalize.pos import canonical_pos
from pipeline.records import AdapterRun, RecordStats
from pipeline.sources.cefrj_adapter import SourceCefrRecord
from pipeline.sources.ngsl_adapter import SourceFrequencyRecord
from pipeline.sources.octanove_adapter import SourceOctanoveRecord
from pipeline.sources.wiktextract_adapter import SourceLexicalRecord
from pipeline.sources.wordnet_adapter import SourceWordnetLink

PROCESSING_VERSION = "norm-v1"


@dataclass
class NormalizedSenseCandidate:
    """One candidate sense for a word, before identity resolution (Phase 6)."""

    # Word level
    headword_display: str
    headword_search: str
    pos_canonical: str
    pos_raw: str

    # Sense level
    gloss_display: str
    gloss_search: str
    examples_display: list[str]
    tags: list[str]

    # Word-level Polish translations aligned to THIS sense (D007)
    translations: list[AlignedTranslation]
    alignment_version: str = ALIGNMENT_VERSION

    # Word-level evidence attached for later phases
    cefr_evidence: list[dict] = field(default_factory=list)   # {source, cefr, pos_raw}
    frequency_evidence: list[dict] = field(default_factory=list)  # {source, rank, freq}
    wordnet_links: list[dict] = field(default_factory=list)   # {lemma, pos, sense_id, synset}

    # Provenance
    sources: list[str] = field(default_factory=list)
    source_record_ids: list[str] = field(default_factory=list)
    processing_version: str = PROCESSING_VERSION


def _align_word(
    rec: SourceLexicalRecord,
) -> list[list[AlignedTranslation]]:
    glosses = [clean_gloss(s.gloss) for s in rec.senses]
    inline = [extract_inline_polish(s.gloss) for s in rec.senses]
    return align_translations(
        AlignmentInput(
            word=rec.word,
            glosses=glosses,
            word_level_translations=rec.polish_translations,
            senses_with_inline=inline,
        )
    )


def normalize_wiktextract(
    run: AdapterRun,
    cefrj: list[SourceCefrRecord] | None = None,
    octanove: list[SourceOctanoveRecord] | None = None,
    ngsl: list[SourceFrequencyRecord] | None = None,
    wordnet_links: list[SourceWordnetLink] | None = None,
) -> tuple[list[NormalizedSenseCandidate], RecordStats]:
    """Produce normalized sense candidates from a Wiktextract adapter run.

    CEFR/frequency/WordNet evidence is grouped by word (search key) and
    attached to every candidate sense of that word (word-level evidence;
    sense-level reconciliation is Phase 6/7's job, sections 14-15).
    """
    stats = RecordStats()
    cefrj = cefrj or []
    octanove = octanove or []
    ngsl = ngsl or []
    wordnet_links = wordnet_links or []

    # Word-level evidence indexes.
    cefr_by_word: dict[str, list[dict]] = {}
    for rec in cefrj:
        cefr_by_word.setdefault(search_key(rec.headword), []).append(
            {"source": rec.source, "cefr": rec.cefr, "pos_raw": rec.pos_raw}
        )
    for rec in octanove:
        cefr_by_word.setdefault(search_key(rec.headword), []).append(
            {"source": rec.source, "cefr": rec.cefr, "pos_raw": rec.pos_raw}
        )
    freq_by_word: dict[str, list[dict]] = {}
    for rec in ngsl:
        freq_by_word.setdefault(search_key(rec.lemma), []).append(
            {"source": rec.source, "rank": rec.rank, "freq": rec.frequency_per_million}
        )
    wn_by_word: dict[str, list[dict]] = {}
    for rec in wordnet_links:
        wn_by_word.setdefault(search_key(rec.lemma), []).append(
            {
                "lemma": rec.lemma,
                "pos_raw": rec.pos_raw,
                "sense_id": rec.sense_id,
                "synset": rec.synset_id,
            }
        )

    candidates: list[NormalizedSenseCandidate] = []

    for rec in run.records:
        if not isinstance(rec, SourceLexicalRecord):
            continue
        stats.read += 1
        word_display = clean_display(rec.word)
        word_search = search_key(rec.word)
        pos_can = canonical_pos(rec.pos_raw)
        alignment = _align_word(rec)
        word_cefr = cefr_by_word.get(word_search, [])
        word_freq = freq_by_word.get(word_search, [])
        word_wn = wn_by_word.get(word_search, [])

        for sense_idx, sense in enumerate(rec.senses):
            gloss_display = clean_gloss(sense.gloss)
            if not gloss_display:
                stats.skipped += 1
                continue
            candidates.append(
                NormalizedSenseCandidate(
                    headword_display=word_display,
                    headword_search=word_search,
                    pos_canonical=pos_can,
                    pos_raw=sense.tags[0] if sense.tags and not rec.pos_raw else rec.pos_raw,
                    gloss_display=gloss_display,
                    gloss_search=search_key(gloss_display),
                    examples_display=[clean_display(e) for e in sense.examples],
                    tags=list(sense.tags),
                    translations=alignment[sense_idx]
                    if sense_idx < len(alignment)
                    else [],
                    cefr_evidence=list(word_cefr),
                    frequency_evidence=list(word_freq),
                    wordnet_links=list(word_wn),
                    sources=[rec.source],
                    source_record_ids=[rec.source_record_id],
                )
            )
            stats.processed += 1

    return candidates, stats
