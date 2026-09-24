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
