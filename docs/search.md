# Search Architecture (Phase 14, sections 20–22)

Four layers behind one endpoint: `POST /api/v1/vocabulary/search`.

```
Layer 1  exact/text     prefix match on headword + forms (LIKE)
Layer 1  lexical FTS    websearch_to_tsquery('simple', q) over weighted tsvectors
                        (vocabulary_senses.fts A-weighted headword,
                         B-weighted definition preview; sense_translations.fts;
                         sense_definitions.fts)
Layer 2  filters        CEFR, POS, priority, category subtree, frequency bands,
                        flags, student assignment/state — composed IN SQL (§22:
                        never client-side filtering of a truncated list)
Layer 3  semantic       query embedded once (BGE-M3, same model as the corpus);
                        pgvector HNSW cosine against precomputed sense
                        embeddings; rows are never embedded at search time
Layer 4  hybrid         deterministic weighted blend of layers 1 and 3 (below)
```

## Hybrid ranking (documented and unit-tested, §20)

Each layer produces a best-first candidate list; ranks feed reciprocal-rank
fusion, then the documented weights apply:

```
rrf(rank)          = 1 / (60 + rank)          # RRF_K = 60
metadata(f, p)     = 0.5·[freq_rank ≤ 3000] + 0.5·[priority ∈ {VERY HIGH, HIGH}]
score              = 0.60·(rrf(lex_rank) + 0.25·[is_prefix])
                   + 0.35·rrf(sem_rank)
                   + 0.05·metadata
```

- `is_prefix`: the query is a prefix of the headword or a word form
  (Layer 1 exact/text). The `0.25` floor (PREFIX_BONUS) guarantees an exact
  headword hit outranks thesaurus-style semantic hits in normal queries.
- Ties break deterministically: headword, then sense_key.
- The blend, constants and determinism are unit-tested in
  `backend/tests/test_search.py::TestRankingUnits`.
- Multi-word lexical queries are strict (all terms, websearch syntax).
  If a strict ranked query returns nothing, the engine retries with the
  loose OR-join of the terms — §21 topic phrases ("airport problems")
  must answer even when the phrase never co-occurs in one item. The
  fallback is reported through the matching `total`.

## Modes and sorts

- `mode`: `hybrid` (default), `lexical`, `semantic`.
- `sort`: `relevance` (default, score order), `headword`, `priority`,
  `frequency` (SQL-ordered browses over the FULL filtered set — no top-k
  truncation before pagination; `_finalize` re-sorts only relevance pages).
- Empty query = filtered browse (any mode); deterministic order:
  priority DESC, then headword.

## Semantic layer mechanics

- Query embedded with the same BGE-M3 model and recipe family as the
  corpus (emb-v1); embeddings were generated offline in Phase 12.
- Distance is cosine (`<=>`) over `ix_sense_embeddings_hnsw`; per-hit
  `semantic_distance` is returned to the client.
- Both lexical and semantic signals are computed against the SAME base
  filter set (§22: filtering is not applied after the fact to a truncated
  candidate list).

## Filter facets

`GET /api/v1/vocabulary/search/filters` enumerates the filter values the
UI table needs (categories incl. descendants, POS, CEFR, priority levels,
frequency bands, flags) — filters are useless if the client cannot
enumerate them.

## Performance (dev machine, concurrent embedding load)

Measured with `scripts/phase14_search_benchmark.py` (3 repeats each;
latencies are inflated ~2x because the Phase 12 bulk generator was
running on the same box; no tuning was attempted at this stage):

| probe                    | mode     | total   | p50 ms | max ms   |
|--------------------------|----------|---------|--------|----------|
| exact headword "bank"    | lexical  | 74      | 239    | 744      |
| "money bank"             | lexical  | 8       | 216    | 231      |
| "rozkaz" (translation)   | lexical  | 1       | 221    | 229      |
| browse A2+HIGH           | lexical  | 2,499   | 81     | 133      |
| topic (semantic)         | semantic | 24,032  | 883    | 75,232*  |
| "rozkaz" (hybrid)        | hybrid   | 24,032  | 1,244  | 1,411    |
| topic (hybrid)           | hybrid   | 24,032  | 2,193  | 3,519    |

\* max includes the one-off model load in the measurement window.

Ranking quality (top-3s in the benchmark output): exact "bank" hits
outrank everything; "money bank" surfaces bank/withdraw/deposit; Polish
"rozkaz" hits "order" at lexical rank 1 plus semantic neighbors;
"things needed when traveling" returns travel vocabulary
(get/case/bus...) even though the phrase occurs nowhere verbatim (§21).

## Performance (Phase 25, D027)

End-to-end HTTP p50 over the full development DB (41,687 senses,
embeddings loaded), measured by `scripts/phase25_perf_benchmark.py`
(5 repeats, warm caches, report in
`data/construction/phase25_perf_report.json`):

```text
lexical search (bank)             ~130–320 ms (run variance)
browse table 50 / 200 rows        ~100 ms / ~100 ms
semantic (repeat, cached)         ~70–90 ms
semantic (cold unique query)      ~450–680 ms
hybrid (repeat, cached)           ~170 ms
hybrid + filters                  ~90 ms
vocabulary detail (1 sense)       ~17 ms
bulk assignment 250 new/already   ~26 / ~27 ms
student profile (500+ rows)       ~45 ms, ~355 KB payload
per-student dashboard             ~26 ms
review queue                      ~25 ms
dashboard rollup                  ~16 ms
students list                     ~13 ms
```

Interpretation:

- **Cold semantic latency is the CPU query embedding** (~260 ms of the
  ~450–680 ms), not the vector search: HNSW returns 50 neighbors in
  ~5 ms. The `count(*)` for pagination totals costs ~50–90 ms.
- **Repeated queries are memoized** (`embed_query`, bounded LRU of 256),
  so the common teacher pattern of re-running a topic query across
  students costs ~70–90 ms instead of ~830 ms.
- The HNSW vector search itself is not the bottleneck at this corpus
  size; the index is used as intended (no per-row embedding at search
  time).
- The workbench is server-paginated and capped at the API `MAX_LIMIT`
  (200 rows), which bounds both payload and render work.

## Operational notes

- The HNSW index MUST be rebuilt after bulk embedding loads
  (`scripts/phase12_embeddings_smoke.py --reindex`). An index built empty
  and grown by incremental inserts had severely degraded recall during
  Phase 14 diagnosis: a direct vector lookup returned distance 0.0 while
  the same sense was absent from the index-ordered top-50 even at
  `hnsw.ef_search=200`. Rebuilding the index over the loaded rows fixed
  it (self at rank 1, distance 0.0000).
- When filtering by student/assignment, `student_id` must accompany the
  `assigned`/state/due/difficulty filters (they join on that student).
- Relevance pages re-sort in Python after fetch; browse pages are
  SQL-paginated. `total` is always the full filtered-set count.
