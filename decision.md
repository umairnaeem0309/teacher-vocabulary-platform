# Decision Log

ADR-style log. Decisions are never silently reversed: a superseded decision
stays listed, with the new decision referencing it.

---

# Decision D001

## Date
2026-09-16

## Decision
Use PostgreSQL 17 as the production and development database.

## Reason
The BRD requires PostgreSQL; the platform needs relational integrity,
full-text search and (with pgvector) vector search in one system.

## Alternatives considered
SQLite (construction pipeline only), MongoDB.

## Status
Accepted

---

# Decision D002

## Date
2026-09-16

## Decision
Install PostgreSQL 17 natively on the development machine (Windows) instead
of running it via Docker Compose.

## Reason
Docker is not installed on this machine and WSL is unavailable, so Compose
services cannot run here. Native PostgreSQL 17.11 (EDB build) was installed
via winget and verified running as a Windows service. Docker Compose
configuration is still provided for environments that have Docker.

## Alternatives considered
Docker Desktop (rejected: not installed; WSL missing), WSL2 PostgreSQL
(rejected: WSL not installed).

## Status
Accepted (environment-specific; Compose remains the canonical dev-env config)

---

# Decision D003

## Date
2026-09-16

## Decision
Backend uses a synchronous SQLAlchemy 2 engine with the psycopg3 driver.

## Reason
FastAPI runs sync endpoints on a threadpool; the workload is
database-bound rather than concurrency-bound (single-teacher tool). Sync
SQLAlchemy is simpler, fully supported by Alembic, and avoids async-ORM
pitfalls. Revisit only under measured load.

## Alternatives considered
asyncpg + async ORM (more complexity, weaker Alembic fit), raw psycopg
(no ORM/migrations path).

## Status
Accepted

---

# Decision D004

## Date
2026-09-16

## Decision
pgvector installation is deferred to the point of first need (Phase 12
embeddings). Target: EDB StackBuilder GUI ("Database Extensions → pgvector")
on this machine; fallback: VS Build Tools + source compile.

## Reason
pgvector has no scriptable installer on Windows (StackBuilder is GUI-only
and its download index is not anonymously reachable). It is not required by
any Phase 0–11 deliverable. The health endpoint tests plain PostgreSQL
connectivity, which is what Phase 0 acceptance requires.

## Alternatives considered
Installing VS 2022 Build Tools (~2–6 GB) immediately to compile from source
(rejected: heavy, not needed until Phase 12); switching database technology
(prohibited by master_prompt.md section 121).

## Status
Accepted — OPEN ITEM tracked in current-state.md and plan.md

---

# Decision D005

## Date
2026-09-17

## Decision
All API errors — domain, schema-validation, framework and unhandled — return
one uniform envelope:
`{"error": {"code", "message", "details", "request_id"}}`.
Endpoints whose functionality belongs to a later phase are registered as
honest 501 stubs (code `not_implemented`, with the planned phase in details)
instead of being omitted or faked.

## Reason
Section 55 requires structured, consistent, actionable, safe errors. A single
envelope lets the frontend have one error path (ApiError) and gives users a
correlation ID that matches server logs (section 56). The 501 convention keeps
the API surface complete and self-documenting from Phase 1 while never
claiming unimplemented features work.

## Alternatives considered
RFC 7807 problem+json (viable, but adds negotiation complexity without a
consumer that needs it); per-domain error shapes (rejected: inconsistent,
duplicated client handling); omitting unimplemented endpoints (rejected:
clients and tests cannot distinguish "missing" from "planned").

## Status
Accepted

---

# Decision D006

## Date
2026-09-18

## Decision
Schema identity and integrity model:

1. All primary keys are random UUIDs (application-generated), except
   `vocabulary_sources` (small registry, integer PK).
2. `vocabulary_senses.sense_key` is a stable deterministic string identity
   (format finalized in Phase 6) and UNIQUE - sense-level identity from day
   one (section 9).
3. Duplicate prevention is enforced by a real database constraint:
   `UNIQUE(student_id, sense_id)` on `student_vocabulary` (section 28).
4. Evidence tables (`cefr_evidence`, `frequency_evidence`) are UNIQUE per
   (sense, source) so sources never overwrite each other (sections 14-15).
5. Enums are stored as readable strings via SQLAlchemy non-native enums
   (portable rows; no PG enum migration pain).
6. Deletion is soft (`is_active`, `StudentStatus`) for students and senses;
   historical learning records are never destroyed (section 27).

## Reason
UUID PKs avoid sequential-ID enumeration and merge cleanly across
environments; named constraints keep autogenerate deterministic.
UNIQUE(student, sense) is the core duplicate-prevention guarantee and is
proven by database-level tests, not only application code.

## Alternatives considered
BigInteger autoincrement PKs (simpler, but leaks record counts and
complicates multi-environment merges); PG native enums (harder to extend);
application-level duplicate checks only (prohibited by section 28).

## Status
Accepted

---

# Decision D007

## Date
2026-09-21

## Decision
Word-level Polish translations are aligned to senses with a deterministic
four-tier heuristic (`align-v1`, pipeline/normalize/align.py, documented in
docs/translation-alignment.md):

1. inline gloss match (`(pl: ...)` in the gloss) - confidence 0.95
2. cognate/common form (translation == headword) -> all senses - 0.50
3. token evidence vs a sense's inline Polish hints - 0.70
4. position fallback, round-robin, max 3 per sense - 0.35

Every assignment stores its confidence and method. Leftovers beyond caps
stay word-level on the entry; nothing is discarded silently.

## Reason
Phase 3 proved Wiktextract translations are word-level while the platform
requires sense-level Polish (sections 9, 42). The heuristic is cheap,
deterministic, LLM-free (sections 50, 139) and honest: low-confidence
assignments are marked as such, and a future embedding-based re-assignment
(Phase 12+) can supersede `align-v1` under a new version without touching
sense identity.

## Alternatives considered
- Attach all translations to all senses (rejected: corrupts search/UI).
- LLM classification per sense (rejected: prohibited scale, section 50).
- Embedding similarity now (deferred: embeddings do not exist until
  Phase 12; the heuristic is the documented interim mechanism).

## Status
Accepted

---

# Decision D008

## Date
2026-09-22

## Decision
Sense identity model (`sensekey-v1`, pipeline/identity/identity.py):

1. Identity groups are (headword_search, pos_canonical); meaning is
   resolved within the group by gloss comparison - never by spelling
   alone (section 9).
2. Two glosses denote the same sense when their significant-token sets
   (stopwords removed, synonyms canonicalized) are equal, in a
   subset relation (smaller side >= 2 tokens), or Jaccard >= 0.75
   (0.6 with equal counts). Bias: never over-merge - all other cases
   stay distinct senses.
3. sense_key = `{word}|{pos}|{digest12}` with a 48-bit blake2b digest of
   the sorted token tuple. Measured: 41,686 senses -> 0 collisions.
   Residual collisions (probabilistically ~0.04% at 500k senses) are
   eliminated by deterministic `-2`, `-3`... suffixing at resolution
   time, so keys are always unique.
4. Merged senses union provenance, translations (best confidence wins),
   CEFR/frequency evidence and WordNet links, deduped.

## Reason
Sections 82 and 25-26 require the same sense found through any source,
search or category to resolve to one master record while genuinely
different senses stay separate. Gloss-token similarity is deterministic,
cheap and observable; the subset rule reflects how real dictionaries
restate the same gloss at different lengths.

## Alternatives considered
- WordNet synset as primary identity (insufficient coverage; Wiktextract
  senses often have no synset match).
- Embedding similarity clustering now (deferred: embeddings arrive in
  Phase 12; current rule is deterministic and testable first).
- One digest per gloss text instead of token set (rejected: would not
  merge synonym-restated glosses).

## Status
Accepted

---

# Decision D009

## Date
2026-09-23

## Decision
CEFR and frequency reconciliation (pipeline/enrich/):

1. CEFR evidence is POS-aware: evidence whose POS maps to the sense's
   canonical POS drives the normalized value; mismatched evidence is
   downgraded but kept.
2. Agreement: single source -> 0.85, unanimous multi-source -> 0.95.
   Conflict -> higher level wins with confidence 0.50 and
   cefr_conflict = 1 (visible, never discarded - section 14).
3. No evidence -> NULL with confidence 0 (never invented, section 108).
4. Frequency: best (lowest) NGSL rank wins; duplicates counted in the
   report. frequency_band (top1000/top2000/top3000/beyond) is display
   metadata only - never the priority score (sections 15-16).
5. Results persist to the SQLite construction DB (pipeline/storage/) with
   idempotent batched upserts and a QC summary computed from stored rows.

## Reason
Section 14 demands source evidence be preserved and normalized values only
where defensible; picking the higher level on conflict is the safe teaching
direction (overestimating difficulty delays a word; underestimating it
teaches it too early) while the conflict flag keeps the disagreement
auditable. Frequency stays separate from priority by design.

## Alternatives considered
- Weighted-average CEFR mapping (rejected: invents levels that exist in no
  source, violates section 14).
- Lower level wins on conflict (rejected: wrong teaching direction).
- Store bands only, drop raw ranks (rejected: rank is objective evidence).

## Status
Accepted

# Decision D010

**Title:** WordNet sense linking policy (wnlink-v1)

**Date:** 2026-09-24

## Context

Phase 8 (sections 16, 84) requires integrating the supplied WordNet 2025
data: preserve relationships where useful (synonym, hypernym, hyponym,
related concept) and link master senses to synsets, without forcing every
relation into the UI. WordNet entry links are word-level (lemma, POS,
synset), while our senses are sense-level — linking must disambiguate.

## Decision

1. Relations are normalized into four groups for use: synonym (from
   `similar`), hypernym (+ instance hypernym), hyponym (+ instance
   hyponym), related (part/whole, derivation, cause, entailment, domain).
   Unknown relation types are preserved verbatim (nothing silently
   dropped, section 48). Reverse edges are not invented.
2. The full catalog (107,519 synsets, 125,249 relations) is stored in the
   construction DB keyed by WordNet's own synset ids, so the PostgreSQL
   import (Phase 13) can join back to the same source of truth.
3. Sense→synset linking is POS-gated and deterministic (wnlink-v1):
   - exactly one candidate synset for (lemma, POS): WordNet's own
     assertion carries the link (`monosemous`, 0.80; `sense-id`, 0.85 if
     the synset body is absent);
   - several candidates: definition similarity (D008 token rules + light
     English inflection stemmer), unique best >= 0.60 links
     (`definition-match`, score as confidence);
   - otherwise: unique argmax with >= 2 shared significant tokens
     (definition or WordNet members, headword excluded) links as
     `shared-tokens` (0.70).
4. Never fabricate a link: missing evidence, POS mismatch, ambiguity
   (tied best candidates) and weak signal all leave the sense unlinked
   and are counted in the QC report. Confidence < 0.80 marks heuristic
   links; the retrieval phase may weight or ignore them.

## Reason

WordNet's own entry assertion is strong when unambiguous; gloss overlap
alone is too weak across sources (Wiktionary wording vs WordNet wording),
so synonym-enumeration glosses are matched against WordNet members too.
The bias against over-merging (D008 spirit) applies to linking: a guessed
link is worse than no link, and every miss is counted, not hidden.

## Alternatives considered

- Link every sense to all entry synsets of the headword (rejected:
  destroys sense-level precision; a teacher showing "bank finances" the
  river-bank taxonomy is wrong).
- Embedding-based similarity (rejected for this phase: deterministic,
  reproducible and cheap was the goal; embeddings arrive in Phase 12 and
  may refine linking later as a new version).
- Drop `shared-tokens` tier (rejected: 3,954 additional valid links at a
  marked 0.70 confidence; the near-field sibling risk is documented and
  weighted at retrieval time).

## Status

Accepted

# Decision D011

**Title:** Deterministic thematic taxonomy (tax-v1)

**Date:** 2026-09-25

## Context

Phase 9 (sections 18, 50, 85) requires a hierarchical taxonomy with
categories, subcategories, mapping rules and confidence, allowing multiple
categories per sense, classified deterministically without an LLM (§50),
and never a prerequisite for semantic search.

## Decision

1. Fixed versioned hierarchy (``tax-v1``): 24 top categories + subcate-
   gories per section 18's minimum list (170 nodes total), stored as rows
   (key, name, parent_key, position) so the UI and the PostgreSQL import
   share one definition.
2. Three deterministic evidence tiers, best per (category, subcategory)
   wins:
   - ``headword`` (0.90): the headword itself is a domain keyword
     ("airport", "salary") — highest precision;
   - ``wordnet-chain`` (0.85): the Phase 8 linked synset, or its hypernym
     ancestors (bounded walk, depth 5), has a definition containing the
     category's domain tokens ("dog" -> ... -> "animal" -> nature);
   - ``gloss`` (0.60-0.80): keyword stems in the gloss; >= 2 distinct
     keyword hits 0.80 (sub) / 0.70 (top), single hit 0.65 (sub) /
     0.60 (top).
3. A subcategory hit also assigns its parent top (retrieval can filter by
   top or sub). Multiple categories per sense are expected and counted.
4. Uncategorized senses are normal and counted (60% coverage on the
   construction sample). Keyword tables are pipeline data; changing them
   means bumping ``tax-v1`` so historical assignments stay explainable
   (sections 12, 127). Categories are retrieval/filtering aids only
   (section 18) — semantic search (Phase 14) must not depend on them.

## Reason

Headword and WordNet evidence are objective; gloss keywords are the
weakest signal and get the lowest confidence. Keyword tables are curated
by hand for the teaching domain (not generated), kept modest in size, and
errors are recoverable: re-running with a bumped version replaces all
assignments (full refresh, not accumulate) because the classifier is a
pure function of sense data + tables.

## Alternatives considered

- LLM classification of every sense (rejected: explicitly prohibited by
  section 50 for the core path; optional isolated enrichment later).
- Embedding clustering (rejected for v1: non-deterministic across model
  versions; embeddings arrive in Phase 12 and may add a new tier then).
- Single category per sense (rejected: section 85 explicitly allows
  multiple; real senses span domains, e.g. "hungry" -> emotions + food).
- Larger keyword tables for higher coverage (rejected for v1: precision
  drops; coverage can grow with evidence-driven additions per version).

## Status

Accepted

## D011 audit addendum (2026-09-25)

A random-sample precision audit of the first real-data run surfaced three
defects, fixed in two version bumps (each recorded here, not silently):

1. **tax-v1.1** — single-keyword gloss hits (0.65 tier) were predominantly
   noise (`hydraulic` -> food-drinks via "water"); removed. Prone
   polysemous keywords (water, flight, score, wake, run, dose) pruned
   from tables. The shared stemmer over-stripped short words
   (`dose` -> `do` colliding with headword tier; `uses` -> `us` not
   matching `use`) — fixed with a >= 3-char stem guard and bumped to
   wnlink-v1.1 (same bug affected WordNet definition matching).
2. **tax-v1.2** — the headword tier (0.90) applied word-level evidence to
   every sense of a polysemous keyword (`fast` "light-sensitive" ->
   food-diets, `train` "intimate terms" -> sport-fitness); the same error
   class D009 fixed for CEFR. Headword hits now require same-category
   gloss corroboration, and the headword's own stem is excluded from that
   corroboration (glosses repeat the headword; self-corroboration is
   circular).

Measured effect on the 41,690-sense sample: categorized senses dropped
60.1% -> 18.5% while sample precision at the sub level rose to near-1.0
for headword/chain rows; coverage returns as keyword tables improve under
future version bumps. Precision over coverage is the standing rule for
teacher-facing filters.

# Decision D012

**Title:** Deterministic vocabulary priority scoring (prio-v1)

**Date:** 2026-09-26

## Context

Phase 10 (sections 15–17, 86) requires a priority for every sense that is
never CEFR alone, never raw frequency alone, accounts for lexical-quality
flags, is reproducible and explainable, and is stored with a version.
Higher CEFR must not mean automatically lower usefulness (section 14), and
missing evidence must not be scored as uselessness (section 127).

## Decision

1. Formula (`prio-v1`, pipeline/enrich/priority.py, documented in
   docs/priority-scoring.md):
   `score = (0.35·frequency + 0.15·learner + 0.20·polish + 0.30·quality)
   × penalty`, clamped to [0, 1].
2. Components: NGSL-tuned frequency curve `rank^-0.07` (rank ≥ 50,000 →
   0.30 floor; missing → neutral 0.5); CEFR as mild learner relevance
   A1 1.0 → C2 0.55 (never disqualifying; missing → 0.5); Polish usefulness
   = mean D007 alignment confidence (missing → neutral 0.5, NOT zero —
   §127); quality = examples 0.4 + gloss depth 0.15/0.3 + WordNet link 0.3
   (presence-based positive evidence, no neutral).
3. Penalty is multiplicative and applied directly (not blended): hard
   markers (obsolete/archaic/historical/rare/rare-sense) × 0.5 (set
   semantics, no stacking), soft markers (technical/slang/alt-of/…) × 0.75
   each, floored at 0.25 — flags can move a sense across level bands.
4. Levels are fixed quantile-free thresholds: VERY HIGH ≥ 0.70, HIGH ≥ 0.55,
   MEDIUM ≥ 0.40, LOW ≥ 0.25, VERY LOW below. With all signals neutral the
   score is the floor 0.35 (LOW) — absence of evidence is never scored as
   VERY LOW.
5. Every row stores score, level, version and a full components JSON
   (§16); the teacher UI shows levels, the raw score is a tie-break
   (§16). `sense_priorities` is keyed (sense_key, version): new formula
   versions add rows and never destroy history (§86). Teacher overrides
   (§17) are a later DB feature layered on top, never mutated by the
   pipeline.

## Reason

A single-signal priority is explicitly prohibited (§86); blending four
normalized signals with a capped frequency curve keeps core vocabulary at
the top while leaving room for evidence quality to differentiate. The
neutral value 0.5 for missing evidence keeps coverage gaps (Polish
translations cover only ~38% of senses in the sample) from condemning
senses by data availability. Presence-based quality has no neutral by
design — an all-neutral sense (0.35, LOW) is the honest floor, and VERY
LOW stays reserved for penalized senses. Quantile-free thresholds keep
levels stable as the corpus grows; the version column keeps historical
assignments explainable.

## Alternatives considered

- Quantile-based levels (rejected: levels would shift silently as the
  corpus grows, breaking reproducibility; §86).
- Missing Polish evidence → 0 (rejected: scores 62% of the sample as
  useless by coverage alone; violates §127).
- CEFR as difficulty penalty (rejected: §14 — C2 words with strong other
  signals stay HIGH/VERY HIGH; measured on the sample).
- Blended penalty `(1 − 0.15·(1−p))` (rejected in review: the worst case
  could only reach 0.31, leaving VERY LOW unreachable and flags
  toothless).
- Raw rank as the score (rejected: raw frequency alone is prohibited;
  §15–16).

## Status

Accepted
