# Embedding Generation (emb-v1)

Phase 12 (§88). This document is the operational reference for generating,
storing and using sense embeddings. It reflects what is implemented, not
intent.

## Purpose

Semantic search (Phase 14) embeds only the teacher's query at request time;
every vocabulary sense is embedded ahead of time during construction and
stored in pgvector. This keeps the API search path cheap and deterministic.

## Model

| Property | Value |
| --- | --- |
| Model | `BAAI/bge-m3` (locked in D014; multi-lingual, strong on EN/PL) |
| Dimensions | 1024 |
| Normalization | L2-normalized embeddings (`normalize_embeddings=True`) |
| Similarity | cosine (HNSW `vector_cosine_ops`) |
| Runtime | sentence-transformers 6.1.0, torch CPU build |
| Local cache | `data/models/` (HF cache layout) |

The model is downloaded automatically on first use (~2.3 GB) into
`data/models/`. No network access is needed after that.

## Input recipe (what is embedded)

```
headword | pos | gloss | ex1 | ex2
```

- Up to 2 examples (`MAX_EXAMPLES = 2`), ordered, from `sense_examples`.
- No arbitrary metadata is embedded (§88): no IDs, versions, ranks,
  categories, priorities or provenance go into the text.
- The exact text is hashed (`text_sha256`, SHA-256) and stored per row; it
  is the resume/change guard.

## Storage (PostgreSQL)

Table `sense_embeddings` (migration `7b2c91a4e8f5`):

- `sense_id UUID` PK (FK → `vocabulary_senses` ON DELETE CASCADE),
- `embedding vector(1024) NOT NULL`,
- `model_name`, `model_version`, `dims`, `embedding_version`,
- `text_sha256`, `created_at`,
- `UNIQUE (sense_id, embedding_version)`,
- btree index on `embedding_version`,
- HNSW index `ix_sense_embeddings_hnsw` (`vector_cosine_ops`).

The current version is `emb-v1`. One version is kept at a time
(`delete_other_versions`); the sense evidence tables remain the source of
truth — embeddings are a derived, fully rebuildable view.

## Generation pipeline

Code: `pipeline/enrich/embeddings.py` + `pipeline/storage/pg_store.py`.

`generate_embeddings(rows, existing_shas, model, batch_size=32,
checkpoint=None, checkpoint_cb=None)`:

1. Rows are processed in sorted `sense_key` order (deterministic).
2. Skip if stored `text_sha256` matches the recomputed hash for the
   current recipe/model (unchanged senses are never re-encoded).
3. Batch-encode with the model, upsert into `sense_embeddings`
   (`ON CONFLICT (sense_id, embedding_version) DO UPDATE`).
4. Periodically persist a checkpoint (`Checkpoint.as_json`) so an
   interrupted run resumes with `k > last_sense_key` (string compare).
5. The checkpoint callback receives an immutable snapshot
   (`dataclasses.replace`) — the stored checkpoint always reflects exactly
   the state at save time.
6. `batch_cb` (optional): each batch's records are passed to it BEFORE
   the checkpoint advances, so the caller can persist to pgvector per
   batch — the checkpoint never claims unstored work (resume is
   lossless; D014 addendum). The full-run script does exactly this;
   the end-of-run upsert is an idempotent safety net.

`EmbeddingModel` is a lazy singleton (`shared()`); `model_version()` is
the model name truncated to 40 chars, matching the DB column.

## How to run

Smoke/limited run (lowest frequency ranks, default 96 senses):

```bash
cd backend
PYTHONIOENCODING=utf-8 uv run python ../scripts/phase12_embeddings_smoke.py \
  --limit 96 --probes
```

Full generation over all 41,690 senses (CPU; on this workstation the
measured rate is ~0.75 senses/s on real texts → ≈ 15 hours; the run is
checkpointed and safe to interrupt — rerun the same command to resume):

```bash
cd backend
PYTHONIOENCODING=utf-8 uv run python ../scripts/phase12_embeddings_smoke.py \
  --full --batch-size 32 --resume
```

- `--resume` continues from `data/construction/emb-v1_checkpoint.json`
  (restart-safe: completed batches are already committed to PG).
- `--limit N` / `--full` choose the input set; `--batch-size` tunes
  throughput; `--probes` prints nearest-sense checks
  (bank-money / bank-river / football).

### Running detached on Windows

Interactive `uv run` invocations die with their parent terminal. The
working pattern is a PowerShell `Start-Process` launcher with unbuffered
output and offline env (see `data/construction/phase12_launch.ps1`,
git-ignored): `python -u` + `-RedirectStandardOutput/-RedirectStandardError`
into `data/construction/phase12_full.log`, `WorkingDirectory backend/`,
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`. Live progress: the checkpoint
file `data/construction/emb-v1_checkpoint.json` (`last_sense_key`,
`batches_done`). Do not use a one-shot `schtasks` trigger for a long run
(it double-fires at its scheduled time).

## Model download notes (Windows, this workstation)

The HF CDN connection from this network stalls on large files. The
weights (`pytorch_model.bin`, 2,271,145,830 bytes) were downloaded from
the official BAAI mirror `modelscope.cn` with a resumable loop into the
HF cache blob path. The blob name is the file's sha256
(`b5e0ce34…daad38`); `sentence-transformers` verifies the digest on load,
so integrity is checked automatically on first use. After the blob is
complete, remove the `.incomplete` suffix by letting any `huggingface_hub`
call finish (it renames the file and creates the snapshot symlink); or
delete `data/models/models--BAAI--bge-m3` and re-run to let HF fetch the
remaining small tokenizer files itself.

## Tests

`backend/tests/test_embeddings.py` (13 tests): recipe construction and
sha stability, skip-unchanged, re-embed-on-change, resume ordering,
checkpoint immutability/snapshots, deterministic FakeModel vectors, plus
2 PostgreSQL tests (roundtrip + `nearest_senses` self-similarity ≈ 0,
`delete_other_versions`) using the `emb-test:` sense_key prefix with
cleanup. `backend/tests/test_migrations.py` includes
`sense_embeddings` in `EXPECTED_TABLES`.

## Versioning rules

- Changing the recipe, model, or normalization ⇒ new `embedding_version`
  (e.g. `emb-v2`): new code version, regenerate, then
  `delete_other_versions` keeps exactly one current version.
- `text_sha256` mismatch after an upgrade ⇒ sense is re-embedded on the
  next run; unchanged senses are skipped.
- Priorities kept history (prio-v1); embeddings deliberately do not —
  they are rebuildable from evidence tables in one deterministic pass.
