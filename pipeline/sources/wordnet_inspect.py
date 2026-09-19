"""WordNet 2025 JSON inspectors (Phase 3).

Files: per-POS synset maps (`noun.*.json`, `verb.*.json`, ...) plus
`entries-*.json` lemma -> senses index and `frames.json`.
Synset files can be several MB of JSON; they are loaded one file at a time
(70 MB total, safe) and never the whole directory at once.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

RELATION_KEYS = (
    "hypernym",
    "instance_hypernym",
    "hyponym",
    "similar",
    "mero_part",
    "holo_part",
    "derivation",
    "domain_topic",
    "causes",
    "entails",
)


def inspect_wordnet_dir(wordnet_dir: Path) -> dict[str, Any]:
    """Profile synset files, entry files and relation coverage."""
    synset_files = sorted(
        p for p in wordnet_dir.glob("*.json")
        if p.name not in {"frames.json"} and not p.name.startswith("entries-")
    )
    entry_files = sorted(wordnet_dir.glob("entries-*.json"))

    total_synsets = 0
    synsets_with_definition = 0
    synsets_with_example = 0
    relation_counts: Counter[str] = Counter()
    pos_by_prefix: Counter[str] = Counter()
    members_total = 0
    ili_filled = 0
    per_file: dict[str, Any] = {}

    for path in synset_files:
        prefix = path.name.split(".")[0]
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        file_count = len(data)
        pos_by_prefix[prefix] += file_count
        total_synsets += file_count
        rel_keys_found: set[str] = set()
        for payload in data.values():
            if payload.get("definition"):
                synsets_with_definition += 1
            if payload.get("example"):
                synsets_with_example += 1
            if payload.get("ili"):
                ili_filled += 1
            members_total += len(payload.get("members", []))
            for key in RELATION_KEYS:
                if payload.get(key):
                    relation_counts[key] += len(payload[key])
                    rel_keys_found.add(key)
        per_file[path.name] = {
            "synsets": file_count,
            "relation_keys_present": sorted(rel_keys_found),
        }

    entry_lemmas = 0
    entry_senses = 0
    entry_multi_pos = 0
    for path in entry_files:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        entry_lemmas += len(data)
        for pos_map in data.values():
            if len(pos_map) > 1:
                entry_multi_pos += 1
            for payload in pos_map.values():
                entry_senses += len(payload.get("sense", []))

    frames: dict[str, Any] = {}
    frames_path = wordnet_dir / "frames.json"
    if frames_path.exists():
        with frames_path.open("r", encoding="utf-8") as f:
            frames = json.load(f)

    return {
        "synset_file_count": len(synset_files),
        "entry_file_count": len(entry_files),
        "synset_count_total": total_synsets,
        "synsets_by_pos_group": dict(sorted(pos_by_prefix.items())),
        "synsets_with_definition": synsets_with_definition,
        "synsets_with_example": synsets_with_example,
        "synsets_with_ili": ili_filled,
        "member_words_total": members_total,
        "relation_counts": dict(relation_counts.most_common()),
        "entry_lemma_count": entry_lemmas,
        "entry_sense_links_total": entry_senses,
        "entry_lemmas_with_multiple_pos": entry_multi_pos,
        "verb_frames_count": len(frames),
        "per_file": per_file,
    }
