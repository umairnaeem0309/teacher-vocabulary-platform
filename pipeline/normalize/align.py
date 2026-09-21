"""Translation sense-alignment heuristic (Decision D007).

Problem (from Phase 3 inventory): Wiktextract stores translations at WORD
level — `bank -> [bank, brzeg, skarpa, brzeg rzeki, ...]` — while our
vocabulary identity is SENSE-level. Assigning every Polish translation to
every sense would poison search and the review UI.

Heuristic (deterministic, no LLM — sections 50, 139):

For sense S of word W with gloss G and candidate translations T1..Tn:

1. **Exact gloss match** (strongest): Wiktextract sense entries sometimes
   carry inline Polish glosses containing `pl:` — those belong to that sense.
2. **Cognate/common-form**: if a translation equals the English word itself
   (loanword, `bank -> bank`), attach it to ALL senses of the word (weakest
   evidence, always true for the spelling but ambiguous for meaning — it
   stays word-level and is copied to each sense with low confidence).
3. **Semantic similarity**: embed-free scoring — a translation is attached
   to the sense if ANY significant token of the translation appears in a
   small Polish hint vocabulary extracted from the entry's own sense
   glosses (`(pl: ...)`), e.g. inline `brzeg rzeki` makes bare `brzeg`
   attach to the river sense via the shared token `brzeg`.
4. **Fallback — position with cap**: remaining translations attach to
   senses in gloss order, but each sense receives at most `max_per_sense`
   (default 3) translations from this bucket, and every position-assigned
   translation carries reduced confidence.

Confidence values (recorded on every assignment, section 12):
  inline gloss match: 0.95 · cognate: 0.5 · token evidence: 0.7 ·
  position fallback: 0.35

The heuristic is deterministic: same input -> same assignment. It is
recorded as D007 and versioned (`ALIGNMENT_VERSION = "align-v1"`) so
reprocessing can invalidate old assignments cleanly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.normalize.clean import search_key

ALIGNMENT_VERSION = "align-v1"

INLINE_PL_RE = re.compile(r"\((?:płsk\.|pl:|Polish:\s*)([^)]+)\)", re.IGNORECASE)

CONF_INLINE = 0.95
CONF_COGNATE = 0.50
CONF_TOKEN = 0.70
CONF_POSITION = 0.35


@dataclass
class AlignedTranslation:
    """A Polish translation assigned to one sense with confidence."""

    text: str
    confidence: float
    method: str  # inline | cognate | token | position


@dataclass
class AlignmentInput:
    """One word's senses and its word-level Polish translations."""

    word: str
    glosses: list[str]
    word_level_translations: list[str]
    senses_with_inline: list[list[str]] = field(default_factory=list)
    # Pre-extracted inline Polish per sense (parallel to glosses) if any.


def extract_inline_polish(gloss: str) -> list[str]:
    """Pull `pl:` / `płsk:` hints out of a single gloss."""
    return [p.strip() for p in INLINE_PL_RE.findall(gloss or "") if p.strip()]


def align_translations(
    inp: AlignmentInput, max_per_sense: int = 3
) -> list[list[AlignedTranslation]]:
    """Return, per sense index, the Polish translations assigned to it.

    Deterministic; pure function of the input.
    """
    n_senses = max(len(inp.glosses), len(inp.senses_with_inline))
    if n_senses == 0:
        return []

    result: list[list[AlignedTranslation]] = [[] for _ in range(n_senses)]
    used: set[str] = set()

    # 1. Inline gloss matches (strongest evidence).
    for idx in range(n_senses):
        inline = inp.senses_with_inline[idx] if idx < len(inp.senses_with_inline) else []
        for text in inline:
            result[idx].append(AlignedTranslation(text, CONF_INLINE, "inline"))
            used.add(search_key(text))

    word_key = search_key(inp.word)

    # 2. Cognate/common form: translation == the English word.
    for t in inp.word_level_translations:
        if search_key(t) == word_key and not any(
            any(a.method == "cognate" for a in bucket) for bucket in result
        ):
            for bucket in result:
                bucket.append(AlignedTranslation(t, CONF_COGNATE, "cognate"))
            used.add(search_key(t))

    # 3. Token evidence: distinctive Polish token from the translation appears
    #    in another translation's context... Implementation: build a Polish
    #    token set from the word's own inline Polish hints across senses; if a
    #    candidate shares a token with a sense's inline set, attach there.
    inline_token_sets: list[set[str]] = []
    for idx in range(n_senses):
        tokens: set[str] = set()
        for a in result[idx]:
            if a.method == "inline":
                tokens.update(t for t in search_key(a.text).split() if len(t) >= 3)
        inline_token_sets.append(tokens)

    for t in inp.word_level_translations:
        t_key = search_key(t)
        if t_key in used or not t_key:
            continue
        t_tokens = {tok for tok in t_key.split() if len(tok) >= 3}
        best_idx = -1
        best_overlap = 0
        for idx in range(n_senses):
            overlap = len(t_tokens & inline_token_sets[idx])
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = idx
        if best_idx >= 0 and best_overlap > 0:
            result[best_idx].append(AlignedTranslation(t, CONF_TOKEN, "token"))
            used.add(t_key)

    # 4. Position fallback for the remainder, capped per sense.
    remaining = [t for t in inp.word_level_translations if search_key(t) not in used]
    # Round-robin assignment avoids dumping everything on sense 0.
    pos_counts = [0] * n_senses
    t_i = 0
    total_slots = sum(max_per_sense - c for c in pos_counts)
    progress = True
    slots_left = any(c < max_per_sense for c in pos_counts)
    while remaining and progress and slots_left and t_i < len(remaining) + total_slots:
        progress = False
        for idx in range(n_senses):
            if t_i >= len(remaining):
                break
            if pos_counts[idx] >= max_per_sense:
                continue
            t = remaining[t_i]
            t_i += 1
            result[idx].append(AlignedTranslation(t, CONF_POSITION, "position"))
            pos_counts[idx] += 1
            progress = True

    # Deterministic ordering within each bucket.
    return [
        sorted(bucket, key=lambda a: (-a.confidence, a.text))
        for bucket in result
    ]
