"""Part-of-speech normalization across the four source vocabularies (section 81).

Sources use different POS vocabularies:

- CEFR-J/Octanove: `noun`, `verb`, `adjective`, `adverb`, `preposition`,
  `determiner`, `pronoun`, `conjunction`, `modal auxiliary`, `be-verb`, ...
- Wiktextract: `noun`, `verb`, `adj`, `adv`, `name`, `phrase`, `intj`, ...
- WordNet 2025: single letters `n`, `v`, `a`, `r` (satellite `s` -> `a`).

Canonical targets mirror `app.db.models.vocabulary.PartOfSpeech`:
noun/verb/adjective/adverb/phrase/other. The mapping is total — unknown
values map to `other` with the raw value preserved on the record.
"""

from __future__ import annotations

CANONICAL = ("noun", "verb", "adjective", "adverb", "phrase", "other")

_MAP: dict[str, str] = {}
for v in CANONICAL:
    _MAP[v] = v

_SOURCE_ALIASES = {
    # CEFR-J / Octanove
    "modal auxiliary": "verb",
    "be-verb": "verb",
    "do-verb": "verb",
    "have-verb": "verb",
    "auxiliary verb": "verb",
    "infinitive-to": "other",
    "pronoun": "other",
    "preposition": "other",
    "determiner": "other",
    "conjunction": "other",
    "interjection": "other",
    "number": "other",
    # Wiktextract
    "adj": "adjective",
    "adv": "adverb",
    "name": "other",       # proper names: kept as vocabulary, priority-flagged later
    "intj": "other",
    "prep": "other",
    "prep_phrase": "phrase",
    "pron": "other",
    "conj": "other",
    "det": "other",
    "num": "other",
    "particle": "other",
    "proverb": "phrase",
    "contraction": "other",
    "prefix": "other",
    "suffix": "other",
    "infix": "other",
    "interfix": "other",
    "circumfix": "other",
    "postp": "other",
    "adv_phrase": "phrase",
    "symbol": "other",
    "punct": "other",
    "character": "other",
    "article": "other",
    # WordNet single letters
    "n": "noun",
    "v": "verb",
    "a": "adjective",
    "s": "adjective",      # satellite adjective
    "r": "adverb",
}


def canonical_pos(raw: str) -> str:
    """Map any raw POS string to a canonical value; unknown -> 'other'."""
    key = (raw or "").strip().lower()
    if not key:
        return "other"
    if key in _MAP:
        return _MAP[key]
    return _MAP.get(_SOURCE_ALIASES.get(key, ""), "other")
