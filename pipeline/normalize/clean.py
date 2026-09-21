"""Lexical normalization primitives (section 81).

Two value classes are kept separate everywhere:

- **display values**: original casing and Polish diacritics preserved
  (`Bank`, `Łódź`) — what the teacher sees;
- **search keys**: Unicode NFC, casefolded, whitespace-collapsed,
  diacritic-stripped for Polish (`łódź` -> `lodz`) — what queries match.

Destructive lowercasing of display values is prohibited (section 81);
stripping diacritics only ever happens on the search key.
"""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
# characters that carry no search meaning once separated
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)

# NFD cannot decompose precomposed strokes/ligatures (ł, ø, đ, ß...).
# Explicit map for letters that matter to our data (Polish + common borrowings).
_MANUAL_FOLD = str.maketrans({
    "ł": "l", "Ł": "L",
    "ø": "o", "Ø": "O",
    "đ": "d", "Đ": "D",
    "ß": "ss",
    "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE",
    "þ": "th", "Þ": "TH",
    "ð": "d", "Ð": "D",
})


def clean_display(value: str) -> str:
    """Normalize to NFC and collapse whitespace; preserve case/diacritics."""
    value = unicodedata.normalize("NFC", value or "")
    return _WS_RE.sub(" ", value).strip()


def strip_diacritics(value: str) -> str:
    """Remove combining marks (ó->o) and precomposed strokes (ł->l).

    Never mutates display values; used only for search keys.
    """
    value = value.translate(_MANUAL_FOLD)
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def search_key(value: str) -> str:
    """Deterministic search/identity key from any string.

    NFC -> casefold -> strip diacritics -> drop punctuation -> collapse
    whitespace -> NFC again (post-strip may compose differently).
    """
    value = unicodedata.normalize("NFC", value or "").casefold()
    value = strip_diacritics(value)
    value = _PUNCT_RE.sub(" ", value)
    value = _WS_RE.sub(" ", value).strip()
    return unicodedata.normalize("NFC", value)


def clean_gloss(gloss: str) -> str:
    """Clean a definition/gloss for storage and embedding use.

    - NFC + whitespace collapse;
    - drop leading "(...)" qualifier parentheses blocks, e.g. "(esp. of dogs) "
      — Wiktextract puts usage qualifiers there; the remainder is the gloss;
    - drop trailing sense-number markers like "; 2." produced by sources.
    """
    value = clean_display(gloss)
    # leading parenthetical qualifier(s)
    while value.startswith("("):
        close = value.find(")")
        if close == -1:
            break
        value = value[close + 1:].strip()
    # trailing "; 2." / "; 3." style markers
    value = re.sub(r"[;,]?\s*\d+\.$", "", value).strip()
    return value


def pick_american_spelling(value: str) -> str:
    """Prefer American spelling variants (section 51) in display text.

    Conservative: only the small set below, to avoid false positives.
    """
    replacements = {
        "colour": "color",
        "centre": "center",
        "metre": "meter",
        "organisation": "organization",
        "recognise": "recognize",
        "realise": "realize",
    }
    out = value
    for uk, us in replacements.items():
        out = re.sub(rf"\b{uk}\b", us, out)
        out = re.sub(rf"\b{uk.capitalize()}\b", us.capitalize(), out)
    return out
