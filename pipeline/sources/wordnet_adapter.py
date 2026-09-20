"""Open English WordNet 2025 adapter (Phase 4).

Produces three record types:

- ``SourceSynset``: synset id, POS, definition, examples, ILI, members;
- ``SourceSynsetRelation``: typed relation between two synset ids;
- ``SourceWordnetLink``: lemma -> sense id -> synset (from entries-*.json).

Policy: files load one at a time (70 MB total, section 48); relation types
outside the curated set are still captured verbatim — nothing silently
dropped; entries files are optional (adapter works with synsets alone).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.records import AdapterRun

SOURCE_KEY = "wordnet2025"

# Relations captured from synset files. Keys map dump key -> canonical name.
RELATION_KEYS = {
    "hypernym": "hypernym",
    "instance_hypernym": "instance_hypernym",
    "hyponym": "hyponym",
    "instance_hyponym": "instance_hyponym",
    "similar": "similar",
    "mero_part": "mero_part",
    "mero_member": "mero_member",
    "mero_substance": "mero_substance",
    "holo_part": "holo_part",
    "holo_member": "holo_member",
    "holo_substance": "holo_substance",
    "derivation": "derivation",
    "domain_topic": "domain_topic",
    "domain_region": "domain_region",
    "causes": "causes",
    "entails": "entails",
}


@dataclass
class SourceSynset:
    """One WordNet synset."""

    synset_id: str
    part_of_speech: str
    definition: str | None
    examples: list[str]
    ili: str | None
    members: list[str]
    source: str = SOURCE_KEY
    source_record_id: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class SourceSynsetRelation:
    """One typed relation between synsets."""

    from_synset_id: str
    to_synset_id: str
    relation: str
    source: str = SOURCE_KEY


@dataclass
class SourceWordnetLink:
    """Lemma/sense to synset link from the entries index."""

    lemma: str
    pos_raw: str
    sense_id: str
    synset_id: str
    source: str = SOURCE_KEY


_POS_BY_GROUP = {"noun": "n", "verb": "v", "adj": "a", "adv": "r"}


def adapt_wordnet_dir(wordnet_dir: Path) -> AdapterRun:
    """Parse all synset files and entry indexes in the WordNet directory."""
    run = AdapterRun(source=SOURCE_KEY)
    synset_files = sorted(
        p for p in wordnet_dir.glob("*.json")
        if p.name != "frames.json" and not p.name.startswith("entries-")
    )
    entry_files = sorted(wordnet_dir.glob("entries-*.json"))

    for path in synset_files:
        pos_group = path.name.split(".")[0]
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, dict] = json.load(f)
        for synset_id, payload in data.items():
            run.stats.read += 1
            definition = payload.get("definition")
            if isinstance(definition, list):
                definition = definition[0] if definition else None
            members = [m for m in payload.get("members") or [] if m]
            if not members:
                run.stats.warning += 1
                run.add_warning(f"{SOURCE_KEY}:{synset_id}", "synset_without_members")
            run.records.append(
                SourceSynset(
                    synset_id=synset_id,
                    part_of_speech=payload.get("partOfSpeech") or _POS_BY_GROUP.get(pos_group, ""),
                    definition=definition,
                    examples=[e for e in payload.get("example") or [] if e],
                    ili=payload.get("ili"),
                    members=members,
                    source_record_id=f"{SOURCE_KEY}:{synset_id}",
                )
            )
            run.stats.processed += 1
            # Relations are extra records emitted alongside the synset.
            for raw_key, canonical in RELATION_KEYS.items():
                targets = payload.get(raw_key) or []
                for target in targets:
                    run.records.append(
                        SourceSynsetRelation(
                            from_synset_id=synset_id,
                            to_synset_id=target,
                            relation=canonical,
                        )
                    )

    for path in entry_files:
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, dict] = json.load(f)
        for lemma, pos_map in data.items():
            run.stats.read += 1
            for pos_raw, payload in pos_map.items():
                for sense in payload.get("sense") or []:
                    synset = sense.get("synset")
                    sense_id = sense.get("id")
                    if not synset or not sense_id:
                        run.stats.failed += 1
                        run.add_error(
                            f"{SOURCE_KEY}:entry:{lemma}",
                            "sense link missing synset or id",
                        )
                        continue
                    run.records.append(
                        SourceWordnetLink(
                            lemma=lemma,
                            pos_raw=pos_raw,
                            sense_id=sense_id,
                            synset_id=synset,
                        )
                    )
            run.stats.processed += 1

    return run
