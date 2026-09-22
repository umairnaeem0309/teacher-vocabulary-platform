# Sense Identity (D008, Phase 6)

Implementation: `pipeline/identity/identity.py` · key version `sensekey-v1`

## Identity rules

1. **Group** candidates by `(headword_search, pos_canonical)`.
   `headword_search` is the casefolded, diacritic-stripped form (so
   `Łódź`-style entries group correctly); POS is canonical
   (noun/verb/adjective/adverb/phrase/other).
2. **Compare glosses** within a group using significant tokens:
   - drop stopwords and tokens shorter than 3 chars;
   - canonicalize synonym pairs (`kid`→`child`, `movie`→`film`, …).
3. **Same meaning** iff token sets are:
   - equal, or
   - in a subset relation with the smaller side ≥ 2 tokens, or
   - Jaccard ≥ 0.75 (or ≥ 0.6 with equal set sizes).
4. **Everything else stays a distinct sense.** The bias is deliberately
   against over-merging: BANK-financial and BANK-river must never collapse
   (sections 9, 25–26, 60).

## Key format

```text
sense_key = {headword_search}|{pos_canonical}|{digest12}
digest12  = blake2b-48bit of the space-joined sorted token tuple
```

- Stable for identical input; deterministic across runs (tested).
- 48 bits: measured **0 collisions** on 41,686 senses (150k-line sample);
  expected ~0.04% at 500k senses.
- Residual collisions are eliminated by deterministic `-2`, `-3`… suffixes
  during resolution, so uniqueness is guaranteed, not probabilistic.

## Merging

When candidates merge into one `MasterSense`:

- provenance (`sources`, `source_record_ids`) unions;
- translations union with best-confidence-wins per (text, method);
- CEFR/frequency/WordNet evidence unions deduped;
- examples and tags union;
- the alphabetically-first gloss becomes the display gloss.

## Measured results (150k-line Wiktextract sample, 2026-09-22)

| Metric | Value |
|---|---|
| Normalized candidates in | 47,327 |
| Master senses out | 41,686 (11.9% dedup) |
| Unique sense keys | 41,686 (0 collisions) |
| BANK (noun) senses | 28 — financial & river both present, separate |

## Limitations

- Gloss-similarity clustering is lexical; it cannot catch paraphrases with
  disjoint vocabularies. Those become separate senses (safe direction);
  Phase 8 (WordNet links) and Phase 12 (embeddings) can later merge them
  under a new key version if justified.
- Stopword/synonym lists are curated, not exhaustive; they are versioned
  with the code and changes re-run the whole pipeline deterministically.
