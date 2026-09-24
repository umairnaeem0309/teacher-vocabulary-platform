"""WordNet semantic-relationship integration (Phase 8, sections 16, 84).

Two concerns, kept separate:

**1. Synset catalog** — ``build_synset_catalog`` turns adapter output into
``SynsetCatalog``: a synset id -> (POS, definition, members) index plus the
normalized relation set. Relations are preserved verbatim (§84 "preserve
relationships where useful") but grouped for use:

- ``synonym``      ← ``similar`` (near-synonymy in WordNet)
- ``hypernym``     ← ``hypernym`` + ``instance_hypernym`` (taxonomy up)
- ``hyponym``      ← ``hyponym`` + ``instance_hyponym`` (taxonomy down)
- ``related``      ← part/whole, cause, entailment, derivation, domain —
  useful for retrieval, deliberately *not* surfaced as UI taxonomy (§84:
  do not force every relation into the UI).

Reverse edges (hyponym of hypernym pairs) are already directionally
explicit in the dump, so no mirror rows are invented.

**2. Sense linking** — ``link_senses`` attaches master senses to synsets
via the wordnet_links evidence (lemma + sense id + synset id) that the
normalizer attached per word. Linking is POS-gated (evidence POS must
agree with the sense's canonical POS) and disambiguated by definition
similarity (same token rule as D008 identity clustering), because WordNet
entry links are word-level and a headword usually has many synsets.

Policy (D010): never fabricate a link — when evidence is missing or
ambiguous the sense stays unlinked and the miss is counted for QC.
Ambiguous = two or more candidate synsets tie on the best definition
score; linking would be a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.identity.identity import _significant_tokens
from pipeline.normalize.clean import search_key
from pipeline.normalize.pos import canonical_pos

WORDNET_LINK_VERSION = "wnlink-v1"

# Canonical grouping of WordNet relation types (section 84).
SYNONYM_RELATIONS = ("similar",)
HYPERNYM_RELATIONS = ("hypernym", "instance_hypernym")
HYPONYM_RELATIONS = ("hyponym", "instance_hyponym")
RELATED_RELATIONS = (
    "mero_part", "mero_member", "mero_substance",
    "holo_part", "holo_member", "holo_substance",
    "derivation", "domain_topic", "domain_region",
    "causes", "entails",
)
GROUPED_RELATIONS = frozenset(
    SYNONYM_RELATIONS + HYPERNYM_RELATIONS + HYPONYM_RELATIONS + RELATED_RELATIONS
)


def canonical_pos_of_wn(raw: str) -> str:
    """Canonical POS for a WordNet entry POS key like 'n', 'v', 'n-1'."""
    letter = (raw or "").strip().lower().split("-", 1)[0]
    return canonical_pos(letter)


def relation_group(relation: str) -> str:
    """Group a raw WordNet relation into synonym/hypernym/hyponym/related.

    Unknown relation types stay verbatim (nothing silently dropped, §48).
    """
    if relation in SYNONYM_RELATIONS:
        return "synonym"
    if relation in HYPERNYM_RELATIONS:
        return "hypernym"
    if relation in HYPONYM_RELATIONS:
        return "hyponym"
    if relation in RELATED_RELATIONS:
        return "related"
    return relation


@dataclass
class SynsetEntry:
    """One synset in the catalog."""

    synset_id: str
    part_of_speech: str
    definition: str | None
    examples: list[str]
    members: list[str]
    ili: str | None = None
    definition_tokens: tuple[str, ...] = ()
    definition_stems: tuple[str, ...] = ()
    member_stems: frozenset[str] = frozenset()


@dataclass
class SynsetRelationRow:
    """One normalized relation edge."""

    from_synset_id: str
    to_synset_id: str
    relation: str  # canonical: synonym/hypernym/hyponym/related/<raw>
    source: str = "wordnet2025"


@dataclass
class SynsetCatalog:
    """Index of synsets + relations built from adapter records."""

    synsets: dict[str, SynsetEntry] = field(default_factory=dict)
    relations: list[SynsetRelationRow] = field(default_factory=list)
    duplicates_dropped: int = 0

    def neighbors(self, synset_id: str, group: str) -> list[str]:
        """Targets of a synset's grouped relations (deduped, order kept)."""
        seen: list[str] = []
        for r in self.relations:
            if (
                r.from_synset_id == synset_id
                and r.relation == group
                and r.to_synset_id not in seen
            ):
                seen.append(r.to_synset_id)
        return seen

    def stats(self) -> dict[str, int]:
        by_group: dict[str, int] = {}
        for r in self.relations:
            by_group[r.relation] = by_group.get(r.relation, 0) + 1
        return {"synsets": len(self.synsets), "relations": len(self.relations), **by_group}


def build_synset_catalog(
    synsets: list,
    relations: list,
) -> SynsetCatalog:
    """Index adapter records (SourceSynset / SourceSynsetRelation)."""
    catalog = SynsetCatalog()
    for rec in synsets:
        if rec.synset_id in catalog.synsets:
            catalog.duplicates_dropped += 1
            continue
        def_tokens = _significant_tokens(search_key(rec.definition or ""))
        catalog.synsets[rec.synset_id] = SynsetEntry(
            synset_id=rec.synset_id,
            part_of_speech=rec.part_of_speech,
            definition=rec.definition,
            examples=list(rec.examples),
            members=list(rec.members),
            ili=rec.ili,
            definition_tokens=def_tokens,
            definition_stems=tuple(stem_token(t) for t in def_tokens),
            # WordNet's own synonym list for the synset; glosses often
            # enumerate synonyms, so members are link evidence too.
            member_stems=frozenset(
                stem_token(t) for t in search_key(" ".join(rec.members)).split()
            ),
        )
    seen_edges: set[tuple[str, str, str]] = set()
    for rec in relations:
        edge = (rec.from_synset_id, rec.to_synset_id, rec.relation)
        if edge in seen_edges:
            catalog.duplicates_dropped += 1
            continue
        seen_edges.add(edge)
        catalog.relations.append(
            SynsetRelationRow(
                from_synset_id=rec.from_synset_id,
                to_synset_id=rec.to_synset_id,
                relation=relation_group(rec.relation),
            )
        )
    return catalog


@dataclass
class WordnetEvidence:
    """Word-level entry evidence for one headword.

    ``synsets_by_pos`` maps the WordNet POS letter (n/v/a/s/r) to the
    synset ids WordNet's entries index assigns to that lemma;
    ``sense_ids`` maps synset id -> WordNet sense id (provenance).
    """

    lemma: str
    synsets_by_pos: dict[str, list[str]] = field(default_factory=dict)
    sense_ids: dict[str, str] = field(default_factory=dict)


def build_wordnet_evidence(links: list) -> dict[str, WordnetEvidence]:
    """Group SourceWordnetLink records by lemma search key."""
    by_lemma: dict[str, WordnetEvidence] = {}
    for rec in links:
        key = search_key(rec.lemma)
        ev = by_lemma.get(key)
        if ev is None:
            ev = WordnetEvidence(lemma=key)
            by_lemma[key] = ev
        letter = (rec.pos_raw or "").strip().lower().split("-", 1)[0]
        synsets = ev.synsets_by_pos.setdefault(letter, [])
        if rec.synset_id not in synsets:
            synsets.append(rec.synset_id)
        ev.sense_ids.setdefault(rec.synset_id, rec.sense_id)
    return by_lemma


@dataclass
class SenseWordnetLink:
    """A resolved sense -> synset link (stored in the construction DB)."""

    sense_key: str
    synset_id: str
    confidence: float
    method: str        # "sense-id" | "definition-match"
    wn_sense_id: str   # WordNet's own sense id for provenance


@dataclass
class SenseLinkReport:
    """QC counters for the linking pass (§126; never invented)."""

    senses_total: int = 0
    senses_linked: int = 0
    links_created: int = 0
    no_evidence: int = 0        # no wordnet entry evidence for the headword
    pos_mismatch: int = 0       # evidence exists, but none for this POS
    ambiguous: int = 0          # tied best candidates -> left unlinked
    weak_definition: int = 0    # best definition score below threshold
    multi_synset_senses: int = 0
    link_version: str = WORDNET_LINK_VERSION

    def as_dict(self) -> dict[str, int | str]:
        return {
            "senses_total": self.senses_total,
            "senses_linked": self.senses_linked,
            "links_created": self.links_created,
            "no_evidence": self.no_evidence,
            "pos_mismatch": self.pos_mismatch,
            "ambiguous": self.ambiguous,
            "weak_definition": self.weak_definition,
            "multi_synset_senses": self.multi_synset_senses,
            "link_version": self.link_version,
        }


# Light deterministic stemmer for definition matching (v1): strips
# English inflection suffixes only — no dictionary, no guessing.
_STEM_SUFFIXES = (
    ("ies", "y"),    # countries -> country
    ("sses", "ss"),  # buses -> bus
    ("ches", "ch"),  # churches -> church
    ("shes", "sh"),  # dishes -> dish
    ("xes", "x"),    # boxes -> box
    ("zes", "z"),    # sizes -> size
    ("ing", ""),     # banking -> bank
    ("edly", ""),
    ("ed", ""),      # deposited -> deposit
    ("ly", ""),      # rapidly -> rapid
    ("ers", "er"),   # players -> player
    ("or's", "or"),
    ("er's", "er"),
    ("'s", ""),      # possessives
    ("ers", "er"),
    ("ees", "ee"),
    ("oes", "o"),    # heroes -> hero
    ("s", ""),       # deposits -> deposit (last: most general)
    ("e", ""),       # reserve -> reserv (aligns with reserving)
    ("y", "i"),      # safety -> safeti (aligns with safeties)
)


def stem_token(token: str) -> str:
    """Deterministic light stem (English inflection only).

    Rules are applied repeatedly until a fixed point so inflection chains
    converge (``reserves`` → ``reserve`` → ``reserv`` matches ``reserve``).
    Both sides of every comparison stem identically, so over-stripping is
    consistent rather than wrong.
    """
    t = token
    if len(t) <= 3:
        return t
    for _ in range(4):
        for suffix, replacement in _STEM_SUFFIXES:
            if t.endswith(suffix) and len(t) - len(suffix) >= 2:
                t = t[: len(t) - len(suffix)] + replacement
                break
        else:
            break
    return t


# Definition similarity thresholds (same spirit as D008's bias against
# over-merging: when unsure, do not link).
_DEF_FULL_MATCH = 0.95      # all significant tokens equal
_DEF_SUBSET_MIN = 2         # subset rule needs the smaller side >= 2 tokens
_DEF_SUBSET_SCORE = 0.90
_DEF_JACCARD_MIN = 0.75
_WEAK_THRESHOLD = 0.60      # best score below this -> leave unlinked
_MONOSEMOUS_FLOOR = 0.80    # confidence for WordNet's own single-synset assertion
_MIN_SHARED_TOKENS = 2      # second tier: >= 2 shared significant tokens
_SHARED_TIER_SCORE = 0.70


def _definition_similarity(
    sense_tokens: tuple[str, ...],
    synset_tokens: tuple[str, ...],
) -> float:
    """Score in [0, 1] mirroring D008's gloss clustering rule."""
    if not sense_tokens or not synset_tokens:
        return 0.0
    if sense_tokens == synset_tokens:
        return _DEF_FULL_MATCH
    sa, sb = set(sense_tokens), set(synset_tokens)
    if sa <= sb or sb <= sa:
        smaller = min(len(sa), len(sb))
        if smaller >= _DEF_SUBSET_MIN:
            return _DEF_SUBSET_SCORE
    j = len(sa & sb) / len(sa | sb)
    return j if j >= _DEF_JACCARD_MIN else j * 0.5


def link_senses(
    senses: list,
    catalog: SynsetCatalog,
    evidence: dict[str, WordnetEvidence],
) -> tuple[dict[str, list[SenseWordnetLink]], SenseLinkReport]:
    """Resolve sense -> synset links for every master sense.

    Returns ``{sense_key: [links]}`` (only senses with >= 1 link) and a
    QC report.
    """
    report = SenseLinkReport()
    out: dict[str, list[SenseWordnetLink]] = {}

    for sense in senses:
        report.senses_total += 1
        links = _link_one(sense, evidence, catalog, report)
        if links:
            out[sense.sense_key] = links
            report.senses_linked += 1
            report.links_created += len(links)
            if len(links) > 1:
                report.multi_synset_senses += 1

    return out, report


def _link_one(
    sense: Any,
    evidence: dict[str, WordnetEvidence],
    catalog: SynsetCatalog,
    report: SenseLinkReport,
) -> list[SenseWordnetLink]:
    """POS-gated, definition-disambiguated linking for a single sense."""
    ev = evidence.get(sense.headword_search)
    if ev is None:
        report.no_evidence += 1
        return []
    candidates: list[str] = []
    for letter in _pos_letters(sense.pos_canonical):
        candidates.extend(ev.synsets_by_pos.get(letter) or [])
    if not candidates:
        report.pos_mismatch += 1
        return []

    # Dedup, keep WordNet's order.
    deduped: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    candidates = deduped

    sense_tokens = _significant_tokens(sense.gloss_search)
    stemmed = tuple(stem_token(t) for t in sense_tokens)

    # WordNet's own entry assertion: exactly one synset for (lemma, POS).
    if len(candidates) == 1:
        synset_id = candidates[0]
        entry = catalog.synsets.get(synset_id)
        if entry is None:
            # Entry file references a synset we did not load; WordNet's
            # own assertion is still evidence (rare; entries<->synsets
            # are generated together in the same dump).
            return [_make_link(sense, synset_id, 0.85, "sense-id", ev)]
        score = max(
            _definition_similarity(sense_tokens, entry.definition_tokens),
            _definition_similarity(stemmed, entry.definition_stems),
        )
        if score >= _WEAK_THRESHOLD:
            return [_make_link(sense, synset_id, score, "definition-match", ev)]
        # Even with weak gloss overlap, the lemma is monosemous in
        # WordNet for this POS — the entry assertion carries the link.
        return [_make_link(sense, synset_id, _MONOSEMOUS_FLOOR, "monosemous", ev)]

    # Multiple candidates: disambiguate by definition similarity.
    scored: list[tuple[float, str]] = []
    for synset_id in candidates:
        entry = catalog.synsets.get(synset_id)
        if entry is None:
            continue
        scored.append(
            (
                max(
                    _definition_similarity(sense_tokens, entry.definition_tokens),
                    _definition_similarity(stemmed, entry.definition_stems),
                ),
                synset_id,
            )
        )
    if not scored:
        report.weak_definition += 1
        return []
    scored.sort(key=lambda t: (-t[0], t[1]))  # deterministic: score, then id
    best_score, best_id = scored[0]
    if best_score >= _WEAK_THRESHOLD:
        ties = [s for s, _ in scored if s == best_score]
        if len(ties) > 1:
            report.ambiguous += 1
            return []
        return [_make_link(sense, best_id, best_score, "definition-match", ev)]

    # Second tier: unique argmax with >= 2 shared significant tokens
    # (definition overlap + member overlap, headword excluded).
    stem_set = set(stemmed)
    headword_stem = stem_token(sense.headword_search)
    best_shared = -1
    best_shared_id = ""
    shared_ties = 0
    for synset_id in candidates:
        entry = catalog.synsets.get(synset_id)
        if entry is None:
            continue
        members = entry.member_stems - {headword_stem}
        shared = len(stem_set & set(entry.definition_stems)) + len(stem_set & members)
        if shared > best_shared:
            best_shared = shared
            best_shared_id = synset_id
            shared_ties = 1
        elif shared == best_shared:
            shared_ties += 1
    if best_shared >= _MIN_SHARED_TOKENS and shared_ties == 1:
        return [_make_link(sense, best_shared_id, _SHARED_TIER_SCORE, "shared-tokens", ev)]
    if best_shared >= _MIN_SHARED_TOKENS:
        report.ambiguous += 1
    else:
        report.weak_definition += 1
    return []


def _pos_letters(pos_canonical: str) -> list[str]:
    """WordNet POS letters compatible with a canonical POS."""
    return {
        "noun": ["n"],
        "verb": ["v"],
        "adjective": ["a", "s"],
        "adverb": ["r"],
    }.get(pos_canonical, [])


def _make_link(
    sense: Any,
    synset_id: str,
    confidence: float,
    method: str,
    ev: WordnetEvidence,
) -> SenseWordnetLink:
    return SenseWordnetLink(
        sense_key=sense.sense_key,
        synset_id=synset_id,
        confidence=round(confidence, 4),
        method=method,
        wn_sense_id=ev.sense_ids.get(synset_id, ""),
    )
