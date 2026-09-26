# Vocabulary Priority Scoring (prio-v1)

Phase 10 deliverable (master_prompt.md sections 15–17, 86; decision D012).
The priority answers one question: **which senses should a teacher see and
assign first?** It is deterministic, reproducible and explainable — the same
construction DB always produces the same scores, and every score ships with
its full component breakdown.

## Design rules from the spec

| Rule | Source | How prio-v1 satisfies it |
| --- | --- | --- |
| Never CEFR alone | §86 | CEFR is one of four components, weight 0.15 |
| Never raw frequency alone | §15–16, §86 | rank is curved and capped at 0.35 weight; raw rank is never the score |
| Multiple signals combined | §86 | frequency + learner + polish + quality, plus a flag penalty |
| Lexical quality/flags matter | §86 | obsolete/archaic/rare/etc. multiply the score down |
| Reproducible | §86 | pure function of stored evidence; no randomness, no LLM |
| Explainable | §16 | `components_json` stores every component, weight and raw input |
| Versioned | §86, §12 | every row stores `priority_version`; changes bump `prio-vN` |
| Raw score not primary UI | §16 | UI shows levels VERY HIGH…VERY LOW; score is a tie-break |
| Higher CEFR ≠ lower usefulness | §14 | learner component floors at 0.55 for C2 — never disqualifying |
| Missing evidence ≠ useless | §127 | missing frequency/CEFR/Polish evidence is neutral 0.5, not a penalty |

## Formula

```text
score = ( w_f · frequency
        + w_l · learner
        + w_p · polish
        + w_q · quality ) × penalty

w_f = 0.35   w_l = 0.15   w_p = 0.20   w_q = 0.30   (sum = 1.0)
score clamped to [0, 1], rounded to 4 decimals
```

The penalty is applied **directly** (not blended), so lexical-quality flags
can move a sense across level bands and VERY LOW is actually reachable.

## Components

### 1. Frequency (weight 0.35)

Best (lowest) NGSL rank of the headword, mapped by a power curve tuned to
NGSL's actual range (2,801 lemmas — a generic 50k-rank curve would compress
everything into 0.95–1.0):

```text
frequency = rank^-0.07            (rank >= 50,000 -> 0.30 floor)
frequency = 0.5                   (no rank evidence — neutral)
```

Anchor points: rank 1 → 1.0 · 10 → 0.8511 · 100 → 0.7244 · 1000 → 0.6166 ·
2801 (NGSL end) → 0.5737 · 50,000+ → 0.30.

### 2. Learner relevance (weight 0.15)

CEFR enters as a **mild learner-relevance prior, not a difficulty measure**
(§14: a C2 word is never disqualified — it just loses the beginner bonus):

| CEFR | A1 | A2 | B1 | B2 | C1 | C2 | missing |
| --- | --- | --- | --- | --- | --- | --- | --- |
| value | 1.0 | 0.9 | 0.78 | 0.68 | 0.60 | 0.55 | 0.5 |

### 3. Polish usefulness (weight 0.20)

Mean D007 alignment confidence of the sense's Polish translations.
**Missing Polish evidence is neutral (0.5), not zero** (§127): translation
coverage grows with the full dump, and absence of evidence is not evidence
of uselessness — scoring it 0 would condemn ~68% of senses by coverage
alone.

### 4. Sense quality (weight 0.30)

Cheap, objective richness indicators (presence-based — there is no neutral:
quality is positive evidence):

| Indicator | Points |
| --- | --- |
| has ≥ 1 example | 0.4 |
| gloss ≥ 3 tokens | 0.3 |
| gloss ≥ 1 token | 0.15 |
| WordNet link present (Phase 8) | 0.3 |

Maximum 1.0. Because quality has no neutral, an all-neutral sense scores
**0.35 (LOW)** — the honest floor. VERY LOW is reserved for senses the
penalty pushes below LOW; nothing is EVER LOW just for lacking evidence.

### Penalty (lexical quality markers, multiplicative)

Marker tags from Phase 4/7 Wiktextract extraction, checked as a set:

- **Hard** markers (strong marginality): `obsolete`, `archaic`,
  `historical`, `rare`, `rare-sense` → factor × **0.5** (set semantics:
  several hard markers do not stack);
- **Soft** markers (context-dependent): `technical`, `specialized`,
  `slang`, `vulgar`, `internet`, `alt-of`, `initialism`, `abbreviation`,
  `misspelling`, `pronunciation-spelling`, `obsolete-sense`,
  `archaic-sense` → × **0.75 each**;
- combined multiplicatively, **floored at 0.25** — even a heavily flagged
  sense stays reachable (§14).

Example: `obsolete + slang + technical` → 0.5 × 0.75 × 0.75 = **0.28125**.

## Levels

Fixed thresholds on the final score — part of the version, quantile-free
(so levels never silently shift as the corpus grows):

| Score | Level |
| --- | --- |
| ≥ 0.70 | VERY HIGH |
| ≥ 0.55 | HIGH |
| ≥ 0.40 | MEDIUM |
| ≥ 0.25 | LOW |
| < 0.25 | VERY LOW |

## Explainability

Every sense stores its component breakdown; `components_json` is sorted,
`ensure_ascii=False` JSON, round-tripping into PostgreSQL in Phase 13:

```json
{
  "frequency": 0.6795,
  "inputs": {"cefr_level": "A2", "examples": 2, "frequency_rank": 250,
             "gloss_tokens": 3, "tags": [], "translations": 1,
             "wordnet_linked": true},
  "learner": 0.9,
  "penalty_factor": 1.0,
  "polish": 0.9,
  "quality": 1.0,
  "weights": {"frequency": 0.35, "learner": 0.15, "polish": 0.2, "quality": 0.3}
}
```

→ score 0.8528, VERY HIGH (`bank|noun|t` "financial institution").

## Versioning policy

`PRIORITY_VERSION = "prio-v1"`. Any change to weights, curves, thresholds,
marker sets or neutral values **bumps the version** and re-runs the pass.
`sense_priorities` is keyed `(sense_key, version)`: new versions add rows
and never overwrite, so historical assignments and teacher overrides stay
explainable against the formula that produced them (§12, §86). Teacher
priority overrides (§17) are a separate DB feature layered on top in a
later phase — the pipeline never mutates a teacher's choice.

## Real-data results (41,690-sense construction sample)

Smoke: `scripts/phase10_priority_smoke.py` (idempotent; re-running replaces
prio-v1 rows).

| Level | Senses |
| --- | --- |
| VERY HIGH | 3,828 |
| HIGH | 17,219 |
| MEDIUM | 11,985 |
| LOW | 5,147 |
| VERY LOW | 3,511 |

Sanity checks:

- Per-CEFR gradient runs the right way without being deterministic (§14):
  A1 → 2,302 VERY HIGH / 90 VERY LOW; C2 → 0 VERY HIGH / 22 VERY LOW, but
  C2 still has 209 HIGH;
- top of the scale: `have` (0.853); bottom: junk entries (`aa`, `aaa`,
  0.110) — obsolete/short tokens with no quality evidence;
- top 3,828 (VERY HIGH) ≈ the plausible "teach first" head of the corpus.
