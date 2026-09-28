"""Embeddings (Phase 12, section 88).

Generates and stores a BGE-M3 embedding per sense (emb-v1). Rules from
the spec:

- **One text recipe** for every sense (``embed_text``): headword + POS +
  gloss + up to 2 examples. Only meaning-bearing content — no arbitrary
  metadata is embedded (section 88): no CEFR/frequency/tags/categories/
  priority, no source identifiers.
- **Batch generation** on CPU (this machine has no GPU): configurable
  batch size, sorted sense order for determinism.
- **Checkpointing + resume**: a checkpoint (last completed sense_key) is
  persisted by the caller; a killed run resumes after it. Already-
  embedded senses are skipped via ``text_sha256`` comparison, so a sense
  whose recipe text changed is re-embedded even if a row exists.
- **Versioning**: every row records model_name, model_version, dims and
  embedding_version (emb-v1). A recipe or model change bumps the version
  and re-generates; storage keeps one current version (embeddings are
  regenerable — the evidence tables are the history).

Storage target: PostgreSQL ``sense_embeddings`` (pgvector, HNSW cosine),
written by pipeline/storage/pg_store.py.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

EMBEDDINGS_VERSION = "emb-v1"
MODEL_NAME = "BAAI/bge-m3"
DIMS = 1024
DEFAULT_BATCH_SIZE = 32
MAX_EXAMPLES = 2

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_CACHE = _REPO_ROOT / "data" / "models"


def embed_text(headword: str, pos: str, gloss: str, examples: list[str]) -> str:
    """The deterministic text recipe for one sense (section 88).

    Only meaning-bearing content: headword, POS, gloss, up to 2 examples.
    No arbitrary metadata (CEFR, frequency, tags, categories, priority,
    provenance) is embedded.
    """
    parts = [headword.strip(), pos.strip(), gloss.strip()]
    parts += [e.strip() for e in (examples or [])[:MAX_EXAMPLES] if e and e.strip()]
    return " | ".join(p for p in parts if p)


def text_sha256(text: str) -> str:
    """Hash of the embedded text — the resume guard (section 88)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class EmbeddingRecord:
    """One sense embedding, ready for pgvector storage."""

    sense_key: str
    embedding: list[float]
    model_name: str = MODEL_NAME
    model_version: str = ""
    dims: int = DIMS
    embedding_version: str = EMBEDDINGS_VERSION
    text_sha256: str = ""

    def as_row(self) -> tuple:
        return (
            self.sense_key,
            self.embedding,
            self.model_name,
            self.model_version,
            len(self.embedding),
            self.embedding_version,
            self.text_sha256,
        )


@dataclass
class EmbeddingsReport:
    """QC summary for an embedding run (section 126)."""

    senses_total: int = 0
    generated: int = 0
    skipped_unchanged: int = 0
    reembedded_changed: int = 0
    failed: int = 0
    batches: int = 0
    version: str = EMBEDDINGS_VERSION

    def as_dict(self) -> dict:
        return {
            "senses_total": self.senses_total,
            "generated": self.generated,
            "skipped_unchanged": self.skipped_unchanged,
            "reembedded_changed": self.reembedded_changed,
            "failed": self.failed,
            "batches": self.batches,
            "version": self.version,
        }


@dataclass
class Checkpoint:
    """Resume state persisted between runs (section 88)."""

    version: str = EMBEDDINGS_VERSION
    last_sense_key: str | None = None
    batches_done: int = 0

    def as_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "last_sense_key": self.last_sense_key,
                "batches_done": self.batches_done,
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str | None) -> Checkpoint:
        if not raw:
            return cls()
        d = json.loads(raw)
        return cls(
            version=d.get("version", EMBEDDINGS_VERSION),
            last_sense_key=d.get("last_sense_key"),
            batches_done=int(d.get("batches_done", 0)),
        )


class EmbeddingModel:
    """Lazy BGE-M3 encoder; loads on first use (heavy), cached thereafter."""

    _shared: ClassVar[EmbeddingModel | None] = None

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        device: str | None = None,
        cache_folder: Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.cache_folder = Path(cache_folder) if cache_folder else DEFAULT_MODEL_CACHE
        self._model: Any = None

    def _ensure(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self.cache_folder.mkdir(parents=True, exist_ok=True)
            self._model = SentenceTransformer(
                self.model_name,
                device=self.device,
                cache_folder=str(self.cache_folder),
            )
        return self._model

    def encode(self, texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE) -> list[list[float]]:
        """Normalized dense vectors, one per input text."""
        model = self._ensure()
        vectors = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [v.tolist() for v in vectors]

    def model_version(self) -> str:
        """Version tag of the weights (the model name; BGE-M3 has one
        canonical release — a model upgrade means a new embedding version)."""
        return self.model_name[:40]

    @classmethod
    def shared(cls) -> EmbeddingModel:
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared


def generate_embeddings(
    rows: list,
    existing_shas: dict[str, str] | None = None,
    model: EmbeddingModel | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    checkpoint: Checkpoint | None = None,
    checkpoint_cb: Callable[[Checkpoint], None] | None = None,
) -> tuple[list[EmbeddingRecord], EmbeddingsReport]:
    """Generate embeddings for rows, skipping unchanged senses.

    ``rows``: each needs sense_key, headword, pos, gloss, examples (list).
    ``existing_shas``: sense_key -> text_sha256 of stored rows for the
    current version (from pg_store.existing_embedding_shas). Senses whose
    sha matches are skipped; others are (re-)embedded.
    ``checkpoint``/``checkpoint_cb``: after each batch the updated
    Checkpoint is passed to checkpoint_cb for persistence (section 88).
    """
    model = model or EmbeddingModel.shared()
    existing = existing_shas or {}
    start_after = (checkpoint.last_sense_key if checkpoint else None)

    report = EmbeddingsReport()
    report.senses_total = len(rows)

    texts: dict[str, str] = {}
    for row in rows:
        get = row.get if isinstance(row, dict) else lambda k, _r=row: getattr(_r, k)
        texts[str(get("sense_key"))] = embed_text(
            str(get("headword") or ""),
            str(get("pos") or ""),
            str(get("gloss") or ""),
            list(get("examples") or []),
        )

    pending: list[str] = []
    for key in sorted(texts):
        sha = text_sha256(texts[key])
        if existing.get(key) == sha:
            report.skipped_unchanged += 1
        else:
            pending.append(key)
    if start_after is not None:
        pending = [k for k in pending if k > start_after]

    records: list[EmbeddingRecord] = []
    model_version = model.model_version()
    for start in range(0, len(pending), batch_size):
        batch_keys = pending[start:start + batch_size]
        try:
            vectors = model.encode([texts[k] for k in batch_keys], batch_size=batch_size)
        except Exception:  # noqa: BLE001 - a failed batch is counted, not fatal
            report.failed += len(batch_keys)
            continue
        for key, vec in zip(batch_keys, vectors, strict=True):
            records.append(
                EmbeddingRecord(
                    sense_key=key,
                    embedding=vec,
                    model_version=model_version,
                    text_sha256=text_sha256(texts[key]),
                )
            )
            if key in existing:
                report.reembedded_changed += 1
        report.generated += len(batch_keys)
        report.batches += 1
        if checkpoint_cb is not None:
            checkpoint = checkpoint or Checkpoint()
            checkpoint.last_sense_key = batch_keys[-1]
            checkpoint.batches_done += 1
            # immutable snapshot: the callback may store it (resume guard)
            checkpoint_cb(replace(checkpoint))
    return records, report
