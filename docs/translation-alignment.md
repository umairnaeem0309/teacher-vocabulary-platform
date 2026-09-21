# Translation Sense-Alignment Heuristic (D007)

Version: `align-v1` · Phase 5 · deterministic · no LLM (sections 50, 139)

## Problem

Wiktextract stores Polish translations at **word level**:

```json
{"word": "bank",
 "senses": [{"glosses": ["financial institution ..."]},
            {"glosses": ["land beside a river"]}],
 "translations": [{"code": "pl", "word": "bank"},
                  {"code": "pl", "word": "brzeg"},
                  {"code": "pl", "word": "brzeg rzeki"}]}
```

But platform identity is **sense-level** (section 9). Attaching all three
translations to both senses would corrupt search, the review UI and
copy-to-student output.

## Heuristic (pipeline/normalize/align.py)

For each sense (gloss G) of word W with word-level Polish translations T:

1. **Inline gloss match — confidence 0.95.** Wiktextract glosses sometimes
   embed Polish inline: `(pl: brzeg rzeki)` / `(płsk. kasa)`. These belong
   to that sense with highest confidence.
2. **Cognate/common form — confidence 0.50.** If a translation equals the
   English headword (`bank -> bank`, `hotel -> hotel`) it is attached to
   every sense of the word: true for the form, ambiguous for meaning.
3. **Token evidence — confidence 0.70.** A translation sharing a
   distinctive token (≥3 chars, search-keyed) with a sense's inline Polish
   hints attaches to that sense (e.g. inline `brzeg rzeki` makes bare
   `brzeg` attach to the river sense via shared token `brzeg`).
4. **Position fallback — confidence 0.35, capped 3/sense.** Remaining
   translations are distributed round-robin in gloss order. Every
   position-assigned translation carries reduced confidence.

Leftover translations beyond the caps are kept at word level on the entry —
never discarded silently (section 108).

## Properties

- **Deterministic**: same input → same assignment (unit-tested).
- **Confidence recorded** on every assignment (section 12) and stored in
  `sense_translations.confidence` at import.
- **Versioned**: `ALIGNMENT_VERSION = "align-v1"`; reprocessing with a new
  version invalidates old alignments explicitly.
- **Cheap**: no network, no LLM; O(senses × translations).

## Known limitations (honest, section 119)

- The position fallback *will* misassign some translations for polysemous
  words; confidence 0.35 marks them for teachers and for later improvement.
- A future refinement (optional, Phase 12+) can score sense↔translation
  with BGE-M3 cosine similarity and re-assign under a new version without
  touching identities.
