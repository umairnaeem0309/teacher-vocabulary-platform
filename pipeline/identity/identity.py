"""Sense identity (Phase 6, section 82).

Deterministic resolution of normalized sense candidates into master senses.

Identity rules (D008):

1. Senses are per (headword_search, pos_canonical, meaning) — never spelling
   alone (section 9).
2. Two candidates of the same word+POS are the SAME sense when one gloss is
   a subset of the other's significant tokens (e.g. "run" vs "run quickly")
   — Jaccard >= 0.75, or >= 0.6 with equal token counts.
3. Everything else stays a distinct sense. Bias: never merge genuinely
   different meanings (BANK-financial vs BANK-river must never collapse).
4. Cross-source duplicates merge; provenance lists union; translations,
   evidence and WordNet links union with dedup.

Stable key: ``sense_key = {word}|{pos}|{gloss8}`` where gloss8 is an 8-hex
blake2b digest of the sorted significant-token tuple of the cluster's
*earliest-created* gloss (insertion order = deterministic given the same
input order). The key is stable across re-runs with the same input; format
version lives in ``KEY_VERSION``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from pipeline.normalize.clean import search_key
from pipeline.normalize.normalizer import NormalizedSenseCandidate
from pipeline.normalize.pos import canonical_pos
from pipeline.records import RecordStats

KEY_VERSION = "sensekey-v1"

# Meaningless in glosses for identity purposes (very common English words).
_STOPWORD_LIST = [
    "a", "an", "the", "of", "to", "in", "for", "with", "on", "at", "by",
    "from", "as", "into", "like", "over", "after", "between", "under",
    "above", "behind", "during", "without", "within", "upon", "about",
    "against", "among", "through", "and", "or", "but", "nor", "so", "yet",
    "not", "no", "something", "someone", "one", "who", "that", "which",
    "is", "are", "was", "were", "be", "been", "being", "his", "her",
    "its", "their", "your", "our", "my", "this", "these", "those",
    "other", "another", "such", "very", "more", "most", "less", "least",
    "often", "usually", "typically", "generally", "particularly", "used",
]
_STOPWORDS = frozenset(_STOPWORD_LIST)

# Synonym pairs collapsing to one token (glosses vary by word choice).
_SYNONYM_PAIRS = [
    ("kid", "child"),
    ("ill", "sick"),
    ("illness", "sickness"),
    ("movie", "film"),
    ("couch", "sofa"),
    ("tiny", "small"),
    ("huge", "large"),
    ("big", "large"),
    ("highway", "road"),
    ("assist", "help"),
    ("buy", "purchase"),
    ("begin", "start"),
    ("end", "finish"),
    ("cottage", "house"),
    ("physician", "doctor"),
]


# Canonical representative per synonym group (alphabetically smallest).
_CANON: dict[str, str] = {}
for _a, _b in _SYNONYM_PAIRS:
    _canon = min(_a, _b)
    _CANON[_a] = _canon
    _CANON[_b] = _canon


@dataclass
class MasterSense:
    """A deduplicated master vocabulary sense (identity layer output)."""

    headword_display: str
    headword_search: str
    pos_canonical: str
    sense_key: str
    gloss_display: str
    gloss_search: str
    key_version: str = KEY_VERSION
    examples_display: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    translations: list = field(default_factory=list)  # AlignedTranslation
    cefr_evidence: list[dict] = field(default_factory=list)
    frequency_evidence: list[dict] = field(default_factory=list)
    wordnet_links: list[dict] = field(default_factory=list)

    sources: list[str] = field(default_factory=list)
    source_record_ids: list[str] = field(default_factory=list)

    processing_version: str = ""


def _significant_tokens(gloss_search: str) -> tuple[str, ...]:
    """Content tokens of a search-keyed gloss, sorted, synonyms canonicalized."""
    raw = [t for t in gloss_search.split() if len(t) >= 3 and t not in _STOPWORDS]
    collapsed = {_CANON.get(t, t) for t in raw}
    return tuple(sorted(collapsed))


def _jaccard(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union


def _same_meaning(tokens_a: tuple[str, ...], tokens_b: tuple[str, ...]) -> bool:
    """Subset/Jaccard rule (D008)."""
    if not tokens_a or not tokens_b:
        return False
    if tokens_a == tokens_b:
        return True
    sa, sb = set(tokens_a), set(tokens_b)
    # Subset rule: one gloss's content tokens fully contain the other's,
    # with the smaller set holding at least 2 tokens (guards against
    # degenerate one-token subsets over-merging broad senses).
    smaller = min(len(sa), len(sb))
    if smaller >= 2 and (sa <= sb or sb <= sa):
        return True
    ja = _jaccard(tokens_a, tokens_b)
    if ja >= 0.75:
        return True
    return len(tokens_a) == len(tokens_b) and ja >= 0.6


def _gloss_digest(tokens: tuple[str, ...]) -> str:
    """12-hex (48-bit) digest of the gloss tokens.

    Sizing: at ~500k senses the birthday collision probability is
    ~0.04%; remaining collisions are resolved by the two-pass logic in
    ``resolve_identities`` (guaranteed unique keys, section 82)."""
    payload = " ".join(tokens).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=6).hexdigest()


def make_sense_key(headword_search: str, pos_canonical: str, gloss_search: str) -> str:
    """Stable identity key for a sense (format documented in D008)."""
    tokens = _significant_tokens(gloss_search)
    return f"{headword_search}|{pos_canonical}|{_gloss_digest(tokens)}"


@dataclass
class _Cluster:
    """Accumulating group of candidates that are the same meaning."""

    tokens: tuple[str, ...]
    members: list = field(default_factory=list)

    def matches(self, tokens: tuple[str, ...]) -> bool:
        return _same_meaning(self.tokens, tokens)


def build_sense_key_for_candidate(candidate: NormalizedSenseCandidate) -> str:
    """Convenience: key for a NormalizedSenseCandidate (display unchanged)."""
    return make_sense_key(
        candidate.headword_search, candidate.pos_canonical, candidate.gloss_search
    )


def resolve_identities(candidates: list) -> tuple[list[MasterSense], RecordStats]:
    """Cluster candidates into master senses; deterministic given input order.

    Input order: callers must sort candidates deterministically
    (headword_search, pos_canonical, gloss_search, source_record_id).
    """
    stats = RecordStats()
    clusters: dict[tuple[str, str], list[_Cluster]] = {}
    masters: list[MasterSense] = []

    for cand in candidates:
        stats.read += 1
        group_key = (cand.headword_search, cand.pos_canonical)
        tokens = _significant_tokens(cand.gloss_search)
        bucket = clusters.setdefault(group_key, [])

        target = next((c for c in bucket if c.matches(tokens)), None)
        if target is None:
            target = _Cluster(tokens=tokens)
            bucket.append(target)

        if target.members:
            stats.processed += 1  # merged into existing sense
        else:
            stats.processed += 1
        target.members.append(cand)

    seen_keys: dict[str, int] = {}
    for (word_search, pos_can), bucket in clusters.items():
        for cluster in bucket:
            first = cluster.members[0]
            glosses = sorted({m.gloss_display for m in cluster.members})
            base_key = make_sense_key(word_search, pos_can, first.gloss_search)
            # Digest collisions are probabilistically tiny (48-bit) but must
            # be impossible (section 82): disambiguate deterministically.
            n = seen_keys.get(base_key, 0) + 1
            seen_keys[base_key] = n
            sense_key = base_key if n == 1 else f"{base_key}-{n}"
            master = MasterSense(
                headword_display=first.headword_display,
                headword_search=word_search,
                pos_canonical=pos_can,
                sense_key=sense_key,
                gloss_display=glosses[0],
                gloss_search=first.gloss_search,
                examples_display=sorted(
                    {ex for m in cluster.members for ex in m.examples_display}
                ),
                tags=sorted({t for m in cluster.members for t in m.tags}),
                translations=_merge_translations(cluster.members),
                cefr_evidence=_merge_dicts(cluster.members, "cefr_evidence"),
                frequency_evidence=_merge_dicts(cluster.members, "frequency_evidence"),
                wordnet_links=_merge_dicts(cluster.members, "wordnet_links"),
                sources=_merge_scalar(cluster.members, "sources"),
                source_record_ids=_merge_scalar(cluster.members, "source_record_ids"),
                processing_version=first.processing_version,
            )
            masters.append(master)
            stats.processed += 0  # output counting handled above
    stats.processed = len(masters)
    stats.warning = 0
    return masters, stats


def _merge_translations(members: list) -> list:
    """Union aligned translations across merged candidates, best confidence wins."""
    best: dict[tuple[str, str], Any] = {}
    for m in members:
        for t in m.translations:
            key = (search_key(t.text), t.method)
            existing = best.get(key)
            if existing is None or t.confidence > existing.confidence:
                best[key] = t
    return sorted(best.values(), key=lambda t: (-t.confidence, t.text))


def _merge_dicts(members: list, attr: str) -> list[dict]:
    """Union evidence dicts; dedup on their JSON-ish content."""
    seen: set[str] = set()
    out: list[dict] = []
    for m in members:
        for item in getattr(m, attr):
            key = "|".join(f"{k}={item.get(k)}" for k in sorted(item))
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out


def _merge_scalar(members: list, attr: str) -> list[str]:
    out: set[str] = set()
    for m in members:
        out.update(getattr(m, attr))
    return sorted(out)


def canonical_pos_of(raw: str) -> str:
    """Re-exported for callers; single import point."""
    return canonical_pos(raw)
