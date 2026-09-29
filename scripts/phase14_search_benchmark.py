"""Phase 14 benchmark: latency + recall probes for the four-layer search.

Measures end-to-end latency (HTTP, includes query embedding for
semantic/hybrid) across the §20 modes and probe queries, and prints a
top-k sanity view for the documented probes. Run against the dev API:

    cd backend
    PYTHONPATH=.. PYTHONIOENCODING=utf-8 uv run python ../scripts/phase14_search_benchmark.py

Semantic/hybrid probes load BGE-M3 on first use (~10s CPU) and query
the HNSW index (§88). Lexical probes are pure PostgreSQL FTS.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Offline-safe: the model is already cached under data/models.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PROBES: list[tuple[str, dict]] = [
    ("exact headword", {"mode": "lexical", "query": "bank", "limit": 20}),
    ("multi-word lexical", {"mode": "lexical", "query": "money bank", "limit": 20}),
    ("polish translation", {"mode": "lexical", "query": "rozkaz", "limit": 20}),
    ("browse filtered", {
        "mode": "lexical", "query": "",
        "filters": {"cefr": ["A2"], "priority_levels": ["HIGH"]}, "limit": 50,
    }),
    ("semantic topic", {"mode": "semantic", "query": "things needed when traveling", "limit": 20}),
    ("hybrid polish", {"mode": "hybrid", "query": "rozkaz", "limit": 20}),
    ("hybrid topic", {"mode": "hybrid", "query": "describing personality", "limit": 20}),
]
REPEATS = 3


def main() -> int:
    client = TestClient(app)
    results: list[dict] = []
    for name, payload in PROBES:
        # Warm-up (loads model once if needed, warms PG caches).
        t0 = time.perf_counter()
        resp = client.post("/api/v1/vocabulary/search", json=payload)
        warmup = time.perf_counter() - t0
        if resp.status_code != 200:
            print(f"FAIL {name}: HTTP {resp.status_code}")
            return 1
        body = resp.json()
        latencies = [warmup]
        for _ in range(REPEATS - 1):
            t0 = time.perf_counter()
            resp = client.post("/api/v1/vocabulary/search", json=payload)
            latencies.append(time.perf_counter() - t0)
            assert resp.status_code == 200
        results.append({
            "probe": name,
            "mode": body["mode"],
            "total": body["total"],
            "p50_ms": round(statistics.median(latencies) * 1000, 1),
            "max_ms": round(max(latencies) * 1000, 1),
            "top3": [h["headword"] for h in body["hits"][:3]],
        })
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
