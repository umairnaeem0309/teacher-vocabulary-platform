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
2026-09-16 (resolved 2026-09-27)

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
Superseded 2026-09-27 — resolved differently, see addendum below

## D004 addendum (2026-09-27): resolved with a community prebuilt

Docker was ruled out by the user (local-only development). Resolution
investigation found the documented install paths are all dead ends on this
machine:

1. **StackBuilder no longer offers pgvector** — the live StackBuilder v2
   catalog (postgresql.org/applications-v2.xml, the exact URL embedded in
   the local stackbuilder.exe) lists 76 applications for Windows (PostGIS,
   Bluefin, pgAgent, PEM…) and none is pgvector. The original D004 target
   does not exist anymore.
2. **EDB PostgreSQL binaries zip** (postgresql-17.11-1-windows-x64-\
   binaries.zip, 325 MB): its central directory was inspected remotely
   (2.5 MB range download, all 21,903 entries parsed) — no pgvector
   inside, so downloading it would have been pointless.
3. **conda-forge pgvector win-64** (0.8.6): exists but is built against
   conda-forge's PostgreSQL 16 (`libpq <17` dependency); installing its
   vector.dll into EDB's PostgreSQL 17 failed with "procedure could not be
   found" (ABI mismatch) — confirmed, then removed.
4. **pgvector upstream** publishes no Windows binaries and this machine has
   no MSVC compiler, so the D004 fallback (source compile) would require
   installing VS Build Tools (~2–6 GB).

**Resolution:** the user approved using a community prebuilt —
`andreiramani/pgvector_pgsql_windows` release `0.8.6_17`
(vector.v0.8.6-pg17.zip, natively MSVC-compiled for PostgreSQL 17 Windows;
214★, active, self-described "unofficial release"). Files installed:
`lib/vector.dll`, `share/extension/vector*.sql` + `vector.control`,
`include/server/extension/vector/*.h`. PostgreSQL service restarted,
`CREATE EXTENSION vector` succeeded in `vocab_platform` (extension version
0.8.6). Verified: vector round-trip, `<->` distance operators, HNSW index
creation + nearest-neighbor query via psql, and the backend stack
(SQLAlchemy/psycopg3 via app.db.session) reading the extension and running
a distance query.

Risk accepted: the DLL is an unsigned community build running inside the
server process on a local-only development machine. Production deployment
(Phase 28) must replace it with a trusted build — noted in current-state.md
known issues.

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

## D012 audit addendum (2026-09-27)

A programmatic + stratified-sample audit of the first real-data run
(`scripts/phase10_priority_audit.py`, seed 42; same methodology as the D011
addendum) surfaced two precision gaps, fixed in **prio-v1.1** (one version
bump, recorded here, not silently):

1. **Slur-class tags were not penalized.** The very-high sample contained
   `brown` "dark-skinned" (tags: slur, ethnic, informal) at 0.7412 — a slur
   sense of a common word sitting in the top teaching band. `derogatory`,
   `offensive` and `slur` joined the hard markers (× 0.5, set semantics),
   alongside the existing obsolete/archaic/historical/rare class. Measured:
   322 slur-class senses in the sample, 0 at VERY HIGH after the fix.
2. **Raw gloss token counting overstated gloss depth.** `split()` counted
   punctuation-only fragments and apostrophe splits ("a lady s maid" → 4
   tokens = full 0.30 depth tier; 656 senses in that zone, e.g. "the digit
   1"). Quality now counts significant tokens (≥ 2 alphanumeric characters,
   mirroring D008's content-token spirit).

The audit script itself was also corrected: its all-neutral check originally
ignored gloss evidence and mislabeled thin-but-real glosses ("the digit 1")
as signal-less. All programmatic checks pass on prio-v1.1: levels match
thresholds, scores recompute exactly from stored components, no ordering
inversions across 421 strata, flagged senses average 0.299 vs 0.589 clean,
CEFR gradient A1 0.612 → C2 0.502, boundary strata reviewed clean (A1VERY LOW entries are abbreviation/alt-of junk senses; C2 `secure`/`commission`
survive at HIGH). Distribution shift v1 → v1.1: VERY HIGH 3,828 → 3,814,
VERY LOW 3,511 → 3,641 — flags and gloss depth now bind.

# Decision D013

**Title:** Example integration and quality indicators (ex-v1, qual-v1)

**Date:** 2026-09-27

## Context

Phase 11 (section 87) requires integrating available examples and
supporting at minimum eight quality indicators: translation available,
translation confidence, definition available, example available, CEFR
available, frequency available, category confidence, sense confidence —
and it explicitly forbids deleting incomplete senses. Examples existed
only as a raw JSON blob on master_senses; WordNet's synset examples were
unused; there was no per-sense view of how much evidence exists.

## Decision

1. **sense_examples (ex-v1**, pipeline/enrich/examples.py**)**: Wiktextract
   sense examples and WordNet synset examples (joined through the Phase 8
   links, highest-confidence first) are cleaned (whitespace collapse,
   length 3–300, ≥ 1 alphanumeric), deduplicated casefold-first-wins,
   source-ordered wiktextract → wordnet, capped at 5 per sense. Every row
   keeps its source; integration is a full refresh (pure function of the
   inputs, like taxonomy assignments).
2. **sense_quality (qual-v1**, pipeline/enrich/quality.py**)**: the §87
   eight indicators, computed deterministically from stored evidence.
   sense_confidence = 0.30·translation (mean D007 confidence) +
   0.25·definition (≥ 1 significant gloss token) + 0.20·example
   (min(1, n/2)) + 0.15·CEFR presence + 0.10·frequency presence.
   Missing evidence is 0.0 — honestly empty, never invented (§108, §127).
3. **sense_confidence is NOT priority**: it answers "how much evidence
   supports this record?" (review queues, import triage); Phase 10's
   priority answers "teach this first?" (§86). Conflating them would
   punish data gaps as uselessness.
4. **Incomplete senses are retained** (§87): a zero-evidence sense stays
   in the platform with its provenance at sense_confidence 0.0.
5. Indicator rows are derived views with replace-on-rerun semantics and
   one current version — unlike priorities, no history is kept, because
   the evidence tables (translations, examples, CEFR/frequency evidence,
   categories) are the source of truth the indicators summarize.

## Reason

A real table makes examples queryable for the PostgreSQL import and the
UI (bounded, ordered, provenance-carrying) instead of an opaque JSON
blob; the indicator row gives the teacher UI and later phases one stable
column set instead of recomputing evidence coverage. Presence-based
indicators with a weighted composite are cheap, deterministic and
explainable; the two views (quality vs priority) stay separated so a
sense with little evidence is visible as such, not silently ranked away.

## Alternatives considered

- Keep the JSON blob (rejected: not queryable, no per-row provenance, no
  dedup/cap; WordNet examples would stay unused).
- Weight sense_confidence by CEFR level (rejected: §14 — a level is not
  evidence quality).
- Delete or hide low-evidence senses (rejected: explicitly prohibited by
  §87; contradicts §127).
- Priority-style version history for indicators (rejected: derived view;
  evidence tables are the history).
- No cap on examples (rejected: unbounded rows per sense hurt import size
  and UI without teaching value; 5 is the documented ex-v1 bound).

## Status

Accepted

# Decision D014

Date: 2026-09-27
Phase: 12 (§88)

## Context

Phase 12 needs 41,690 sense embeddings supporting semantic search (Phase
14). CPU-only workstation (torch 2.14.0+cpu, CUDA unavailable); generation
cost is hours, so the run must be interruptible and resumable. pgvector is
installed (D004). §88 forbids embedding arbitrary metadata.

## Decision

- **Model lock: `BAAI/bge-m3`**, 1024-dim, L2-normalized, cosine
  similarity, via sentence-transformers. CPU-only in dev; the pipeline is
  device-agnostic.
- **Recipe `emb-v1`: `headword | pos | gloss | ex1 | ex2`** — identity
  text plus up to two examples from `sense_examples`. No IDs, ranks,
  categories, priorities, provenance or other metadata are embedded (§88).
- **Change/resume guard: `text_sha256`** stored per row; senses whose
  recomputed hash matches the stored one are skipped, changed ones are
  re-encoded in place (`ON CONFLICT DO UPDATE`).
- **Checkpointing**: sorted sense_key order; periodic
  `emb-v1_checkpoint.json` with `last_sense_key` + `batches_done`; resume
  filter `k > last_sense_key`; the callback receives an immutable
  snapshot (`dataclasses.replace`), not the mutable accumulator.
- **One current version**: `UNIQUE (sense_id, embedding_version)` plus
  `delete_other_versions` — unlike priorities (prio-v1 history kept),
  embeddings keep no history; they are a derived view fully rebuildable
  from the evidence tables, which remain the source of truth.

## Reason

Sorted order + hash-skip + checkpoint makes hours-long CPU generation
interrupt-safe and incremental: re-runs cost seconds when nothing changed.
The recipe keeps multi-lingual BGE-M3 focused on lexical meaning (what a
semantic query can plausibly match), not bookkeeping columns the UI
already exposes as filters. History was rejected because every regeneration
is deterministic from evidence; keeping stale versions would double storage
(41,690 × 1024 floats per version ≈ 170 MB) with no query use.

## Alternatives considered

- Embed full definition + all examples (rejected: much longer inputs,
  CPU cost grows, marginal retrieval gain for a teacher UI).
- Embed metadata (rejected: §88 explicitly; also pollutes similarity —
  two senses with the same category but unrelated meanings would drift
  together).
- Keep embedding history like prio-v1 (rejected above: rebuildable view).
- Random/shuffled processing order (rejected: breaks deterministic
  resume semantics; sorted keys give stable string-compare checkpoints).
- Float16 storage (rejected: pgvector halfvec gains little at 1024 dims
  here and complicates the HNSW ops choice; revisit at Phase 25 if storage
  matters).

## Status

Accepted

### Addendum (2026-09-28, after real-run review)

The first full detached run exposed a resume-loss defect the 96-sense
smoke could not catch: the script accumulated all records in memory and
upserted once at the end, while checkpoints advanced per batch — an
interrupt would have skipped senses checkpointed but never stored
(~1,000 rows at kill time). Fix: `generate_embeddings` gained `batch_cb`,
fired with the batch's records BEFORE the checkpoint callback; the
script persists each batch to pgvector in its own transaction, so
checkpoint state == stored state at batch granularity. A persist
exception aborts without advancing the checkpoint (tested). Final
end-of-run upsert kept as idempotent safety net. Regression tests:
ordering (batch before checkpoint), cumulative coverage, failure-aborts.

# Decision D015

Date: 2026-09-28
Phase: 13 (§89)

## Context

Phase 13 imports the construction DB into PostgreSQL in one transaction.
The construction schema (master_senses + child tables, keys, priorities,
quality, wordnet) differs materially from the PG vocabulary schema, and
real data violates two PG assumptions that the 96-row smoke data could
not surface. Separately, the suite's migration roundtrip test has wiped
the development database twice while long-running jobs were live.

## Decision

- **Importer `pipeline/storage/pg_import.py` (import-v1)**: validated,
  batched, single-transaction import; root `vocabulary_senses` rows are
  upserted by `sense_key` so UUIDs (and therefore `sense_embeddings`
  FKs) survive re-imports; children are delete-refreshed per import;
  orphans, rejected senses, collapsed duplicates and unmapped tags are
  reported, never silently dropped (§89 report).
- **Duplicate CEFR evidence**: construction holds 6,259 (sense, source)
  duplicate statements vs PG's UNIQUE constraint. `collapse_cefr`
  deterministically keeps the lowest (cefr, pos_raw) survivor — the
  lowest CEFR is the conservative pedagogical choice (§14). 6,684 rows
  collapsed on real data.
- **Priority history schema gap**: Phase 2 keyed `sense_priorities` by
  `sense_id` alone, which cannot represent the versioned history D012
  requires. Migration `c3d94a71b6e2` switches the PK to
  `(sense_id, version)`; both prio-v1 and prio-v1.1 import (83,374
  rows). Denormalized `priority_*` columns on `vocabulary_senses` mirror
  the current version (prio-v1.1) via `refresh_priority_columns`; the
  versioned table remains the source of truth (§86).
- **Migration tests are sandboxed**: `test_migrations.py` roundtrip now
  creates a disposable `vocab_scratch_*` database, runs
  upgrade/downgrade/upgrade there, asserts dev data is untouched, and
  drops it. `env.py` accepts a programmatic URL override
  (`config.attributes["sqlalchemy_url"]`, URL object only — `str()`
  masks the password) plus `ALEMBIC_DATABASE_URL`. **Rule: no test or
  script may run `alembic downgrade` against the development database.**
- **Stale checkpoint guard (Phase 12 hardening)**: the embedding script
  now verifies checkpointed senses actually exist in storage before
  resuming (count senses ≤ last_sense_key with a stored sha); on
  mismatch it logs and restarts from scratch instead of resuming into a
  lie. Caught live when the wiped DB and stale checkpoint met.

## Reason

The import only meets PG's constraints if duplicates are resolved
deterministically and history is representable; both gaps were invisible
until real 41,690-row data hit the schema. The sandboxed roundtrip
exists because ``alembic downgrade base`` on the dev DB destroyed data
twice — once killing the embedding worker mid-run with FK violations,
once dropping `sense_embeddings` entirely. Tests must be able to prove
schema correctness without holding production data hostage.

## Alternatives considered

- Import priorities as one flat row per sense (rejected: destroys
  D012's version history; the construction DB already holds two
  versions per sense).
- Keep the roundtrip on the dev DB but snapshot/restore around it
  (rejected: heavyweight, still races concurrent jobs; a scratch DB is
  simpler and fully isolated).
- Propagate `priority_*` columns from the construction row (rejected:
  construction has no such columns — inventing data in the loader would
  hide the true source; the refresh derives from `sense_priorities`).
- Skip CEFR duplicates arbitrarily (rejected: nondeterministic re-runs
  would flip evidence between imports; the conservative survivor is
  stable).

## Status

Accepted

# Decision D016

Date: 2026-09-29
Phase: 14 (§20–22)

## Context

Phase 14 delivers four-layer search (exact/lexical, filters, semantic,
hybrid). Two design areas needed decisions: the ranking blend itself
(§20 demands it be documented and tested), and how §21's topic phrases
("airport problems", "things needed when traveling") can be answered by
a lexical layer that only matches terms actually present.

## Decision

- **Hybrid blend (§20)**: reciprocal-rank fusion with documented
  weights — `score = 0.60·lexical + 0.35·semantic + 0.05·metadata`,
  `rrf(rank) = 1/(60+rank)`, metadata = common (freq ≤ 3000) + high
  priority tie-breaker, plus a 0.25 lexical floor for exact/prefix
  headword hits so an exact hit cannot lose to a thesaurus-style
  semantic hit. Full spec in `docs/search.md`; constants unit-tested
  for determinism in `tests/test_search.py::TestRankingUnits`.
- **Two-stage lexical fallback (§21)**: strict multi-word websearch
  queries (all terms) retry as a loose OR-join when they return
  nothing, so topic phrases answer through partial matches instead of
  returning an empty page. The fallback is deterministic and only
  triggers on zero strict hits.
- **Browse semantics**: empty query (any mode) or non-relevance sorts
  are filtered browses over the FULL set — SQL orders and paginates;
  relevance pages alone re-sort in Python. This fixes a real bug where
  `sort=priority` browses were lex-score-truncated before sorting.
- **HNSW after bulk load (operational, §88/§20)**: an HNSW index built
  empty and grown by incremental inserts had catastrophic recall
  (direct lookup distance 0.0; same sense absent from the index-ordered
  top-50 even at `hnsw.ef_search=200`). Rule: after any bulk embedding
  generation, rebuild `ix_sense_embeddings_hnsw` — automated as
  `phase12_embeddings_smoke.py --reindex`. Documented in
  `docs/search.md` and D014's script.
- **API surface**: `POST /api/v1/vocabulary/search` (request/response
  Pydantic models over `pipeline/search/engine.py`) plus
  `GET /api/v1/vocabulary/search/filters` enumerating filter values.
  §22's student/assignment/state/due filters compose in SQL on both
  lexical and semantic paths (same filter set; never client-side).

## Reason

Search correctness is mostly product semantics: what counts as an
answer. The blend is deliberately simple and documented rather than
learned, so teachers can reason about ordering; the two-stage fallback
keeps §21's promise ("semantically relevant even if the exact phrase
does not occur") without weakening the strict default. The HNSW rule
records a production-grade operational lesson discovered before real
teachers depend on semantic search.

## Alternatives considered

- Learned/ML ranking (rejected: opaque, untestable against the
  documented contract; revisit only with real usage data).
- Loose OR as the default (rejected: pollutes strict single-term
  results; fallback-only preserves precision).
- pgvector full-scan instead of HNSW (deferred: fine at 42k vectors,
  but the index exists and — after rebuild — behaves; revisit at
  Phase 28 load testing).
- Client-side filtering of top-k (rejected: explicitly forbidden by
  §22).

## Status

Accepted

# Decision D017

Date: 2026-09-29
Phase: 15 (§5, §39, §91)

## Context

Phase 15 adds teacher authentication: email + password with Argon2id
hashing, server-side sessions in PostgreSQL behind an HTTP-only cookie,
and a bootstrap procedure because public registration must stay closed
(§91). The Phase 2 `teachers`/`teacher_sessions` schema (opaque token
stored hashed, §56) was already in place and is now activated.

## Decision

- **Password hashing**: Argon2id via argon2-cffi with library defaults
  (64 MiB memory, time_cost 3) — OWASP-aligned; parameter changes
  invalidate old hashes gracefully on next verification attempt.
- **Sessions**: cookie carries only a 32-byte random token
  (`secrets.token_urlsafe`); the DB stores its SHA-256 hash (never the
  token — a DB dump must not yield usable credentials). TTL is 24h.
  Cookie flags: HttpOnly, SameSite=Lax, Secure in production/staging.
- **Bootstrap**: `POST /auth/bootstrap` creates the first teacher and
  logs them in; with ≥1 teacher present it answers 403
  `bootstrap_closed` forever. No public registration endpoint exists.
  Re-bootstrap attempts reveal nothing about password strength or
  existing accounts (closure check precedes credential validation).
- **Login anti-enumeration**: unknown email and wrong password return
  the same 401 message; unknown emails burn a decoy Argon2 hash so both
  paths take comparable time.
- **Lazy pruning**: expired sessions are deleted on first resolve
  attempt (the 401 also cleans up); revocation sets `revoked_at` and is
  idempotent. The resolve path runs in a committing transaction — a
  rolled-back prune was caught live in testing.
- **Authorization**: `GET /auth/session` is the reference
  implementation of the §40 "authenticated teacher" check; protected
  domain endpoints (Phase 17+) will reuse the same dependency.
- **Endpoints**: `POST /auth/bootstrap`, `POST /auth/login`,
  `GET /auth/session`, `POST /auth/logout` — replacing the Phase 4
  501 stubs. `email-validator` enforces EmailStr at the schema layer.

## Reason

Sessions were kept server-side (not JWT) because revocation must be
instant and authoritative (logout, compromised token, deactivated
teacher) and the platform already requires PostgreSQL for every
request. Hashing the token at rest costs nothing and removes the
session table from the "what a dump leaks" list. The bootstrap window
is the simplest honest bootstrap: one command, no installer, no
temporary passwords to transmit.

## Alternatives considered

- JWT/stateless sessions (rejected: revocation requires a denylist,
  reintroducing server state; token payload inspection is useless —
  one teacher role).
- Registration endpoints with an invite/activation flow (rejected for
  now: single-teacher deployments are the norm at this stage; revisit
  with multi-teacher support in a later phase).
- Argon2 via passlib (rejected: passlib's argon2 backend is unmaintained
  against current argon2-cffi; use argon2-cffi directly).
- Store the plaintext token for "logout everywhere" by token id
  (rejected: unnecessary — sessions are revocable by hash lookup).

## Status

Accepted
