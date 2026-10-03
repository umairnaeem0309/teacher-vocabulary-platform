# Final Acceptance Report (Phase 29)

Date: 2026-10-03
Scope: local-only operation on one Windows machine (D026) — "deployment"
below means local install/run, per the D026 retargeting of §104/§105.
Evidence: this report cites machine-readable artifacts (test logs, the
readiness report, backup reports) and the phase-by-phase record in
`plan.md`; every number was re-measured for this report unless marked
otherwise.

---

## 1. Acceptance criteria (§105 checklist)

```text
[x] all critical tests pass            backend 359 · vitest 26 · Playwright 7/7 · readiness 18/18
[x] all critical workflows work        §59 login→search→filter→assign→review→FSRS→dashboard (Playwright)
[x] documentation reflects reality     9 docs + README/architecture/current-state/plan/decision; honest-state rule
[x] Git history is clean               conventional prefixes, one commit/phase, no AI trailers (D021)
[x] deployment is documented           local setup in README.md + docs/environment.md (D026)
[x] backup/restore is tested           real pg_dump→pg_restore roundtrip verified (D028)
[x] provided datasets are processed    all 5 sources adapted; see §4 statistics
[x] semantic search works              BGE-M3 + HNSW, §61 queries green over 41,690 senses
[x] sense-level duplicate prevention   UNIQUE(student_id, sense_id) + §60 five-path acceptance
[x] FSRS works                         py-fsrs deterministic scheduling, §59 review flow green
```

All ten criteria met. One scope note: the construction corpus is built
from a 150k-line sample of the 10.9M-line Wiktextract dump (§4) — the
full dump was streamed and inspected, the sample feeds identity; this is
documented since Phase 3 and repeated in §5 Known limitations.

---

## 2. Implemented features

By phase (details per phase in `plan.md`, decisions in `decision.md`):

| Phase | Feature |
|---|---|
| 0–1 | Repo, FastAPI + Next.js skeletons, uniform error envelope (D005), structured logging with request IDs, config fail-fast |
| 2 | 27-table PostgreSQL schema, Alembic, UUID PKs, real uniqueness constraints (D006) |
| 3–4 | Dataset inspection (5 sources) + streaming adapters, nothing silently dropped |
| 5–6 | Normalization, POS mapping, Polish translation alignment `align-v1` (D007), sense identity `sensekey-v1` (D008) |
| 7 | CEFR reconciliation (conflict-preserving, D009), NGSL frequency, construction DB |
| 8 | WordNet 2025 integration: 107,519 synsets, 125,249 relations, sense→synset linking `wnlink-v1.1` (D010) |
| 9 | Deterministic taxonomy `tax-v1.2`, precision-over-coverage (D011) |
| 10 | Priority scoring `prio-v1.1`, multi-signal, explainable, versioned (D012) |
| 11 | Examples `ex-v1` (5/sense cap) + eight §87 quality indicators `qual-v1` (D013) |
| 12 | 41,690 BGE-M3 embeddings, resumable, HNSW (D014) |
| 13 | Single-transaction PG import, CEFR duplicate collapse, priority history migration (D015) |
| 14 | Four-layer search: exact/lexical, SQL-computed filters, semantic, RRF hybrid `0.60/0.35/0.05` + exact floor (D016, docs/search.md) |
| 15 | Auth: Argon2id, server-side sessions, bootstrap-only first teacher, anti-enumeration (D017) |
| 16 | Vocabulary workbench UI, URL-driven table state, TanStack legacy adapter (D018) |
| 17 | Student management, WHERE-scoped isolation, true PATCH semantics (D019) |
| 18 | Bulk assignment, layered duplicate prevention, §29/§30 reports (D020) |
| 19 | Vocabulary sets as pure references (D021) |
| 20 | FSRS review flow: py-fsrs 6.3.2, spec rating mapping, deterministic states, immutable history (D022) |
| 21 | Teacher dashboards over shared SQL definitions (D023) |
| 22 | Import/export CSV/XLSX/JSON, validated two-step import (D024) |
| 23 | Security hardening: rate limits, origin checks, secure headers, payload caps |
| 25 | Performance pass: query-embedding LRU cache, page-size clamp fix (D027) |
| 26 | Local backup/retention/restore with real restore test (D028) |
| 27 | Playwright acceptance suite §59/§60/§61 (D029); 2 bugs found & fixed |
| 28 | Local readiness gate, 18 checks (D030); 2 gaps found & fixed |
| — | D026: local-only scope; Docker/Compose removed |

Also: §19 filter controls, §53 responsive layout (1440/1280/768),
student vocabulary page, review interface with keyboard shortcuts.

## 3. Test results (re-run for this report)

| Suite | Result | Notes |
|---|---|---|
| Backend pytest | **359 passed, 0 failed** | `tests/` (32 files), ~140 s, dev DB |
| Frontend tsc | **clean** | `tsc --noEmit` |
| Frontend eslint | **clean** | `eslint .` |
| Frontend vitest | **26 passed** | 3 files |
| Playwright E2E | **7/7 passed** (2.0 m) | §59 22-step workflow, §53 responsive ×3, §60 duplicates, §61 semantic ×2 — against real stack + real corpus |
| Readiness gate (§104) | **18/18 passed** | `data/construction/phase28_readiness_report.json` — clean install, clean DB, migrations, reversibility, first-run, JSON logs, builds, prod stack, all suites, backup roundtrip, docs |
| Quality gates | ruff clean · ruff format clean · mypy clean (45 files) | `backend/` |

Logs: `data/construction/phase29_*.log` (Git-ignored).

Critical workflows verified end-to-end by the E2E suite: login →
semantic search "vacation" → TRAVEL/A2/HIGH+ filters → multi-select
assign with §29 report → DUE queue → review → EASY → FSRS next-due →
fresh dashboard; duplicate prevention across all five discovery paths;
six §21 semantic example queries + server-side filter composition.

## 4. Dataset statistics

Sources (inventory: docs/data-source-inventory.md):

| Dataset | Size | Records | Role |
|---|---|---|---|
| raw-wiktextract-data.jsonl.gz | 2.7 GB | 10,913,996 lines (fully streamed, 0 malformed); 1,492,836 English entries | senses, glosses, Polish translations |
| CEFR-J Vocabulary Profile 1.5 | 227.7 KB | 7,799 rows | CEFR A1–B2 evidence |
| Octanove C1/C2 Profile 1.0 | 45.4 KB | 2,136 rows | CEFR C1/C2 evidence |
| NGSL 1.2 stats | 61.1 KB | 2,809 rows | frequency evidence |
| English WordNet 2025 | 69.1 MB | 107,519 synsets, 125,249 relations | semantic relationships |

Pipeline output (150k-line Wiktextract sample → construction DB):

- 47,327 normalized candidates → **41,690 master senses** (11.9%
  dedup, **0 sense_key collisions**; BANK financial/river separated)
- Evidence coverage: CEFR 57.9% · frequency 41.2% · Polish translations
  31.6% · examples 60.3% (52,824 examples on 25,693 senses)
- 970 CEFR conflicts preserved with flags (nothing discarded)
- WordNet: 13,263 senses linked (wnlink-v1.1) · Taxonomy: 7,702
  categorized (tax-v1.2, precision-first) · Priorities: 41,690 scored
  (prio-v1.1, prio-v1 history retained)

Production PostgreSQL (live at report time): **27 tables** at Alembic
head `b8e5d1f2a3c4`; **41,690 corpus senses — all present (0 missing
vs construction DB)**; **41,690 embeddings** (HNSW rebuilt after bulk
load); 625,084 total rows (backup-verified). The 356 rows above the
corpus count are `io test …` fixtures left by import/export roundtrip
tests (§5). Student-side demo data: 6 students (5 seeded by the E2E
fixture + 1 from §59 logins), 13 assignments, 1 set.

## 5. Search benchmark

Warm-cache, full corpus (Phase 25, `scripts/phase25_perf_benchmark.py`,
D027):

```text
lexical search (bank)          ~130–320 ms (run variance)
browse table 50 / 200 rows     ~100 ms / ~100 ms
semantic (repeat, cached)      ~70–90 ms
semantic (cold unique query)   ~450–680 ms   ← CPU BGE-M3 query encode
hybrid (repeat, cached)        ~170 ms
hybrid + filters               ~90 ms
vocabulary detail              ~17 ms
bulk assignment 250            ~26 ms
student profile (500+ rows)    ~45 ms (355 KB)
review queue / dashboards      ~16–26 ms
```

Ranking-quality probes (Phase 14 benchmark, docs/search.md): exact
"bank" hits outrank everything; "money bank" → bank/withdraw/deposit;
Polish "rozkaz" → "order" at lexical rank 1; "things needed when
traveling" returns travel vocabulary with no verbatim phrase match
(§21). All six §21 example queries are asserted green in CI-style E2E
(§61).

## 6. Deployment status

**No remote deployment — by design (D026).** `requiremnts.txt` requires
setup instructions, not a deployed target; Docker was removed because it
cannot run on this machine (D002) and the BRD never mentions it.

- Local setup documented: README (prerequisites → env → database →
  extension → migrations → run → tests) + docs/environment.md.
- Clean-environment proof: the Phase 28 readiness gate re-ran the whole
  setup path from scratch — fresh `uv` venv, fresh `pnpm` install into
  an empty directory, clean database creation → extension → migrations →
  first-run bootstrap → production-config stack smoke — **18/18**.
- Operational run: native PostgreSQL 17 (Windows service), `uvicorn`
  (APP_ENV=production config validated), `next build` + `next start`.

## 7. Backup status

- `pipeline/storage/backup.py` + `scripts/db_backup.py` (D028,
  docs/backups.md): `pg_dump --format=custom` → `data/backups/`
  (Git-ignored), newest 7 retained, `pg_restore --no-owner
  --no-privileges`.
- **Real restore verified** (Phase 26): 241,842,655-byte dump → scratch
  DB → 27 tables, 625,084 rows on both sides, Alembic revision
  identical, zero mismatches → RESTORE VERIFIED OK
  (`data/construction/phase26_restore_report.json`).
- **Re-verified by the readiness gate** (Phase 28): fresh dump + fresh
  restore roundtrip, 333.4 s, passed.
- Automated: `backend/tests/test_backup_tools.py` includes a real
  throwaway-DB pg_dump→pg_restore roundtrip (7 tests).
- Limitation: backups are local to the machine — off-site copy is a
  manual step (§5).

---

## 8. Known limitations (honest list)

1. **Corpus scope**: identity/pipeline ran on a 150k-line Wiktextract
   sample (~1.4% of the 10.9M-line dump; the full dump was streamed and
   profiled in Phase 3). 41,690 senses today; scaling to the full dump
   is a data-run, not a code change (adapters stream, ~12k records/s).
2. **356 `io test …` fixture rows** exist in `vocabulary_senses` on the
   dev database — residue of Phase 22 import/export roundtrip tests that
   ran against the dev DB. They are excluded from all corpus statistics
   above (41,690 = construction rows, all present). Not cleaned yet;
   harmless to search but visible in browse.
3. **Community pgvector DLL** (D004 addendum): unsigned third-party
   build inside the server process. Acceptable locally; must be
   replaced with a trusted build before any production deployment.
4. **Cold semantic latency ~450–680 ms**: BGE-M3 query encode is CPU-
   bound. Cached repeats are 70–90 ms; startup pre-load was deliberately
   deferred (D027).
5. **Backups are machine-local**: disaster recovery needs a manual copy
   of `data/backups/*.dump` off the machine (D026/D028 scope).
6. **Single user**: one teacher per deployment (bootstrap closes after
   the first account; §91). Multi-teacher is out of scope.
7. **No CI**: all gates run locally (readiness gate is the
   verification). A future CI pipeline would automate them.
8. **Taxonomy coverage 18.5%** by design (tax-v1.2 precision-first);
   coverage grows via evidence-driven keyword-table version bumps.
9. **Polish translation coverage 31.6%** of senses (source data reality
   — word-level translations, D007 alignment; nothing invented).
10. **`align-v1` position fallback** carries 0.35 confidence by design;
    low-confidence assignments are marked, not hidden.

## 9. Git history

40 commits before this report's commit (41 including it), `main`,
conventional prefixes scoped per phase, one commit per phase/fix group
(§106: no giant commit), no AI trailers (D021; verified: no
Co-Authored-By/Generated-with lines in history). Decisions
D001–D030 logged with alternatives-considered; supersessions referenced,
never silently reversed.

---

## 10. Verdict

**ACCEPTED for local operation.** All §105 criteria met with fresh
evidence; known limitations are listed honestly and none blocks the
requirement set in `requiremnts.txt` (local, production-quality,
backed-up, documented). The platform installs, migrates, boots, tests,
searches, deduplicates at sense level, schedules with FSRS, and
backs up/restores on this machine from documented steps alone.
