"""SQLite construction database (sections 44, 84).

NOT the production database — this is the pipeline's local workbench for
dedup debugging, QC and reproducible re-processing (section 44).

Schema is pipeline-private (keyed by sense_key, versioned) and deliberately
simpler than PostgreSQL's normalized schema: it stores what QC needs.
Batched inserts keep memory bounded (sections 48, 125).

Phase 8 adds the WordNet catalog (synsets + grouped relations) and the
resolved sense→synset links; ids are WordNet's own so the PostgreSQL
import can join back to the same source of truth (D010). Phase 11 adds
integrated examples (sense_examples, ex-v1) and the section-87 quality
indicators (sense_quality, qual-v1).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS master_senses (
    sense_key        TEXT PRIMARY KEY,
    key_version      TEXT NOT NULL,
    headword_display TEXT NOT NULL,
    headword_search  TEXT NOT NULL,
    pos_canonical    TEXT NOT NULL,
    gloss_display    TEXT NOT NULL,
    gloss_search     TEXT NOT NULL,
    cefr_level       TEXT,
    cefr_confidence  REAL,
    cefr_conflict    INTEGER NOT NULL DEFAULT 0,
    frequency_rank   INTEGER,
    frequency_band   TEXT,
    examples_json    TEXT,
    tags_json        TEXT,
    sources_json     TEXT,
    processing_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ms_headword ON master_senses(headword_search);
CREATE INDEX IF NOT EXISTS ix_ms_cefr ON master_senses(cefr_level);

CREATE TABLE IF NOT EXISTS sense_translations (
    sense_key  TEXT NOT NULL REFERENCES master_senses(sense_key) ON DELETE CASCADE,
    translation TEXT NOT NULL,
    confidence REAL NOT NULL,
    method     TEXT NOT NULL,
    PRIMARY KEY (sense_key, translation, method)
);

CREATE TABLE IF NOT EXISTS sense_cefr_evidence (
    sense_key TEXT NOT NULL REFERENCES master_senses(sense_key) ON DELETE CASCADE,
    source    TEXT NOT NULL,
    cefr      TEXT NOT NULL,
    pos_raw   TEXT,
    PRIMARY KEY (sense_key, source, cefr)
);

CREATE TABLE IF NOT EXISTS sense_frequency_evidence (
    sense_key TEXT NOT NULL REFERENCES master_senses(sense_key) ON DELETE CASCADE,
    source    TEXT NOT NULL,
    rank      INTEGER,
    freq      REAL,
    PRIMARY KEY (sense_key, source)
);

CREATE TABLE IF NOT EXISTS wordnet_synsets (
    synset_id  TEXT PRIMARY KEY,
    part_of_speech TEXT NOT NULL,
    definition TEXT,
    ili        TEXT,
    examples_json TEXT
);

CREATE TABLE IF NOT EXISTS wordnet_relations (
    from_synset_id TEXT NOT NULL REFERENCES wordnet_synsets(synset_id) ON DELETE CASCADE,
    to_synset_id   TEXT NOT NULL REFERENCES wordnet_synsets(synset_id) ON DELETE CASCADE,
    relation   TEXT NOT NULL,
    PRIMARY KEY (from_synset_id, to_synset_id, relation)
);
CREATE INDEX IF NOT EXISTS ix_wn_rel_from ON wordnet_relations(from_synset_id);
CREATE INDEX IF NOT EXISTS ix_wn_rel_to   ON wordnet_relations(to_synset_id);

CREATE TABLE IF NOT EXISTS sense_wordnet_links (
    sense_key  TEXT NOT NULL REFERENCES master_senses(sense_key) ON DELETE CASCADE,
    synset_id  TEXT NOT NULL REFERENCES wordnet_synsets(synset_id) ON DELETE CASCADE,
    confidence REAL NOT NULL,
    method     TEXT NOT NULL,
    wn_sense_id TEXT,
    PRIMARY KEY (sense_key, synset_id)
);
CREATE INDEX IF NOT EXISTS ix_swl_synset ON sense_wordnet_links(synset_id);

CREATE TABLE IF NOT EXISTS taxonomy_nodes (
    node_key   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    parent_key TEXT,
    position   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sense_categories (
    sense_key  TEXT NOT NULL REFERENCES master_senses(sense_key) ON DELETE CASCADE,
    category_key  TEXT NOT NULL REFERENCES taxonomy_nodes(node_key) ON DELETE CASCADE,
    subcategory_key TEXT,
    confidence REAL NOT NULL,
    method     TEXT NOT NULL,
    PRIMARY KEY (sense_key, category_key, subcategory_key)
);
CREATE INDEX IF NOT EXISTS ix_sc_category ON sense_categories(category_key);

CREATE TABLE IF NOT EXISTS sense_priorities (
    sense_key  TEXT NOT NULL REFERENCES master_senses(sense_key) ON DELETE CASCADE,
    score      REAL NOT NULL,
    level      TEXT NOT NULL,
    version    TEXT NOT NULL,
    components_json TEXT,
    PRIMARY KEY (sense_key, version)
);
CREATE INDEX IF NOT EXISTS ix_sp_level ON sense_priorities(level);

CREATE TABLE IF NOT EXISTS sense_examples (
    sense_key  TEXT NOT NULL REFERENCES master_senses(sense_key) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    text       TEXT NOT NULL,
    source     TEXT NOT NULL,
    PRIMARY KEY (sense_key, position)
);
CREATE INDEX IF NOT EXISTS ix_se_source ON sense_examples(source);

CREATE TABLE IF NOT EXISTS sense_quality (
    sense_key  TEXT PRIMARY KEY REFERENCES master_senses(sense_key) ON DELETE CASCADE,
    translation_available INTEGER NOT NULL,
    translation_confidence REAL NOT NULL,
    definition_available INTEGER NOT NULL,
    example_available INTEGER NOT NULL,
    cefr_available INTEGER NOT NULL,
    frequency_available INTEGER NOT NULL,
    category_confidence REAL NOT NULL,
    sense_confidence REAL NOT NULL,
    version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sq_conf ON sense_quality(sense_confidence);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    processing_version TEXT NOT NULL,
    stats_json TEXT
);
"""


class ConstructionStore:
    """Thin SQLite wrapper for the construction database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.conn.close()

    def begin_run(self, processing_version: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO pipeline_runs (started_at, processing_version) "
            "VALUES (datetime('now'), ?)",
            (processing_version,),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def finish_run(self, run_id: int, stats: dict) -> None:
        self.conn.execute(
            "UPDATE pipeline_runs SET finished_at = datetime('now'), stats_json = ? "
            "WHERE id = ?",
            (json.dumps(stats), run_id),
        )
        self.conn.commit()

    def upsert_senses(self, enriched: list, batch_size: int = 2000) -> int:
        """Batched idempotent insert of enriched senses; returns row count."""
        total = 0
        for start in range(0, len(enriched), batch_size):
            batch = enriched[start:start + batch_size]
            rows = []
            translation_rows = []
            cefr_rows = []
            freq_rows = []
            for e in batch:
                s = e.sense
                rows.append((
                    s.sense_key, s.key_version, s.headword_display,
                    s.headword_search, s.pos_canonical, s.gloss_display,
                    s.gloss_search, e.cefr_level, e.cefr_confidence,
                    int(e.cefr_conflict), e.frequency_rank, e.frequency_band,
                    json.dumps(s.examples_display, ensure_ascii=False),
                    json.dumps(s.tags, ensure_ascii=False),
                    json.dumps(s.sources, ensure_ascii=False),
                    s.processing_version,
                ))
                for t in s.translations:
                    translation_rows.append((
                        s.sense_key, t.text, t.confidence, t.method,
                    ))
                for ev in s.cefr_evidence:
                    cefr_rows.append((
                        s.sense_key, ev.get("source", "?"), ev.get("cefr", ""),
                        ev.get("pos_raw", ""),
                    ))
                for ev in s.frequency_evidence:
                    freq_rows.append((
                        s.sense_key, ev.get("source", "?"), ev.get("rank"),
                        ev.get("freq"),
                    ))
            self.conn.executemany(
                "INSERT OR REPLACE INTO master_senses "
                "(sense_key, key_version, headword_display, headword_search, "
                " pos_canonical, gloss_display, gloss_search, cefr_level, "
                " cefr_confidence, cefr_conflict, frequency_rank, frequency_band, "
                " examples_json, tags_json, sources_json, processing_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO sense_translations VALUES (?,?,?,?)",
                translation_rows,
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO sense_cefr_evidence VALUES (?,?,?,?)",
                cefr_rows,
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO sense_frequency_evidence VALUES (?,?,?,?)",
                freq_rows,
            )
            self.conn.commit()
            total += len(batch)
        return total

    def upsert_wordnet(
        self,
        catalog: Any,
        links: dict[str, list],
        batch_size: int = 5000,
    ) -> int:
        """Store the synset catalog + resolved sense links.

        Idempotent: replaces synset rows and relation edges on conflict;
        sense links accumulate with INSERT OR IGNORE. Returns total rows
        written (synsets + relations + links).
        """
        total = 0
        synsets = sorted(catalog.synsets.values(), key=lambda s: s.synset_id)
        for start in range(0, len(synsets), batch_size):
            batch = synsets[start:start + batch_size]
            self.conn.executemany(
                "INSERT OR REPLACE INTO wordnet_synsets "
                "(synset_id, part_of_speech, definition, ili, examples_json) "
                "VALUES (?,?,?,?,?)",
                [
                    (
                        s.synset_id, s.part_of_speech, s.definition, s.ili,
                        json.dumps(s.examples, ensure_ascii=False),
                    )
                    for s in batch
                ],
            )
            self.conn.commit()
            total += len(batch)

        self.conn.executemany(
            "INSERT OR IGNORE INTO wordnet_relations "
            "(from_synset_id, to_synset_id, relation) VALUES (?,?,?)",
            [
                (r.from_synset_id, r.to_synset_id, r.relation)
                for r in catalog.relations
            ],
        )
        self.conn.commit()
        total += len(catalog.relations)

        link_rows = [
            (link.sense_key, link.synset_id, link.confidence, link.method,
             link.wn_sense_id)
            for links in links.values() for link in links
        ]
        for start in range(0, len(link_rows), batch_size):
            batch = link_rows[start:start + batch_size]
            self.conn.executemany(
                "INSERT OR IGNORE INTO sense_wordnet_links "
                "(sense_key, synset_id, confidence, method, wn_sense_id) "
                "VALUES (?,?,?,?,?)",
                batch,
            )
            self.conn.commit()
            total += len(batch)
        return total

    def upsert_taxonomy_nodes(self, nodes: list, batch_size: int = 5000) -> int:
        """Replace taxonomy node rows (fixed hierarchy, idempotent)."""
        self.conn.execute("DELETE FROM taxonomy_nodes")
        self.conn.executemany(
            "INSERT INTO taxonomy_nodes (node_key, name, parent_key, position) "
            "VALUES (?,?,?,?)",
            [
                (n["key"], n["name"], n["parent_key"], n["position"])
                for n in nodes
            ],
        )
        self.conn.commit()
        return len(nodes)

    def upsert_categories(
        self,
        assignments: dict,
        batch_size: int = 5000,
    ) -> int:
        """Store sense->category assignments as a full refresh.

        ``assignments`` is this run's complete classification, so previous
        rows are deleted first — INSERT OR REPLACE cannot match top-level
        rows whose subcategory_key is NULL (SQLite NULLs are distinct in
        unique keys).
        """
        self.conn.execute("DELETE FROM sense_categories")
        rows = [
            (sense_key, a.category_key, a.subcategory_key, a.confidence, a.method)
            for sense_key, assigns in assignments.items()
            for a in assigns
        ]
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            self.conn.executemany(
                "INSERT INTO sense_categories "
                "(sense_key, category_key, subcategory_key, confidence, method) "
                "VALUES (?,?,?,?,?)",
                batch,
            )
            self.conn.commit()
        return len(rows)

    def upsert_priorities(self, results: list, batch_size: int = 5000) -> int:
        """Store priority results; keyed by (sense_key, version) so a new
        formula version adds rows instead of destroying history (§86)."""
        total = 0
        rows = [
            (r.sense_key, r.score, r.level, r.version, r.components_json())
            for r in results
        ]
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            self.conn.executemany(
                "INSERT OR REPLACE INTO sense_priorities "
                "(sense_key, score, level, version, components_json) "
                "VALUES (?,?,?,?,?)",
                batch,
            )
            self.conn.commit()
            total += len(batch)
        return total

    def count_priorities(self) -> dict:
        q = lambda sql: int(self.conn.execute(sql).fetchone()[0])  # noqa: E731
        return {
            "rows": q("SELECT COUNT(*) FROM sense_priorities"),
            "senses": q("SELECT COUNT(DISTINCT sense_key) FROM sense_priorities"),
            "versions": q("SELECT COUNT(DISTINCT version) FROM sense_priorities"),
        }

    def count_taxonomy(self) -> dict:
        """Row counts for taxonomy tables (QC, §126)."""
        q = lambda sql: int(self.conn.execute(sql).fetchone()[0])  # noqa: E731
        return {
            "nodes": q("SELECT COUNT(*) FROM taxonomy_nodes"),
            "assignments": q("SELECT COUNT(*) FROM sense_categories"),
            "categorized_senses": q(
                "SELECT COUNT(DISTINCT sense_key) FROM sense_categories"
            ),
        }

    def count_senses(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM master_senses").fetchone()[0])

    def count_wordnet(self) -> dict:
        """Row counts for the WordNet tables (QC, §126)."""
        q = lambda sql: int(self.conn.execute(sql).fetchone()[0])  # noqa: E731
        return {
            "synsets": q("SELECT COUNT(*) FROM wordnet_synsets"),
            "relations": q("SELECT COUNT(*) FROM wordnet_relations"),
            "sense_links": q("SELECT COUNT(*) FROM sense_wordnet_links"),
            "linked_senses": q(
                "SELECT COUNT(DISTINCT sense_key) FROM sense_wordnet_links"
            ),
        }

    def count_translations(self) -> int:
        return int(
            self.conn.execute("SELECT COUNT(*) FROM sense_translations").fetchone()[0]
        )

    def upsert_examples(self, records: list, batch_size: int = 5000) -> int:
        """Store integrated examples as a full refresh (ex-v1).

        ``records`` is this run's complete integration, so previous rows
        are deleted first — the result is a pure function of the inputs.
        """
        self.conn.execute("DELETE FROM sense_examples")
        rows = [
            (r.sense_key, r.position, r.text, r.source)
            for r in records
        ]
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            self.conn.executemany(
                "INSERT INTO sense_examples (sense_key, position, text, source) "
                "VALUES (?,?,?,?)",
                batch,
            )
            self.conn.commit()
        return len(rows)

    def upsert_quality(self, indicators: list, batch_size: int = 5000) -> int:
        """Store quality indicators; one current row per sense plus its
        version (older indicator versions are replaced — indicators are
        derived views, the evidence they summarize is never touched)."""
        total = 0
        for start in range(0, len(indicators), batch_size):
            batch = indicators[start:start + batch_size]
            self.conn.executemany(
                "INSERT OR REPLACE INTO sense_quality "
                "(sense_key, translation_available, translation_confidence, "
                " definition_available, example_available, cefr_available, "
                " frequency_available, category_confidence, sense_confidence, "
                " version) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [ind.as_row() for ind in batch],
            )
            self.conn.commit()
            total += len(batch)
        return total

    def count_examples(self) -> dict:
        """Row counts for the examples table (QC, §126)."""
        q = lambda sql: int(self.conn.execute(sql).fetchone()[0])  # noqa: E731
        return {
            "records": q("SELECT COUNT(*) FROM sense_examples"),
            "senses": q("SELECT COUNT(DISTINCT sense_key) FROM sense_examples"),
            "from_wiktextract": q(
                "SELECT COUNT(*) FROM sense_examples WHERE source='wiktextract'"
            ),
            "from_wordnet": q(
                "SELECT COUNT(*) FROM sense_examples WHERE source='wordnet'"
            ),
        }

    def count_quality(self) -> dict:
        """Row counts + indicator means for sense_quality (QC, §126)."""
        q = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        total = int(q("SELECT COUNT(*) FROM sense_quality"))
        return {
            "senses": total,
            "version": q("SELECT version FROM sense_quality LIMIT 1") if total else "",
            "mean_sense_confidence": round(
                float(q("SELECT AVG(sense_confidence) FROM sense_quality") or 0.0), 4
            ),
        }

    def qc_summary(self) -> dict:
        """Coverage counts computed from stored data (never invented, §127)."""
        total = self.count_senses()
        q = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "total_senses": total,
            "with_polish": q(
                "SELECT COUNT(DISTINCT sense_key) FROM sense_translations"
            ),
            "with_cefr": q("SELECT COUNT(*) FROM master_senses WHERE cefr_level IS NOT NULL"),
            "cefr_conflicts": q("SELECT COUNT(*) FROM master_senses WHERE cefr_conflict = 1"),
            "with_frequency": q(
                "SELECT COUNT(*) FROM master_senses WHERE frequency_rank IS NOT NULL"
            ),
            "with_examples": q(
                "SELECT COUNT(*) FROM master_senses WHERE examples_json != '[]'"
            ),
            "with_examples_integrated": q(
                "SELECT COUNT(DISTINCT sense_key) FROM sense_examples"
            ),
            "with_quality": q("SELECT COUNT(*) FROM sense_quality"),
            "with_wordnet": q(
                "SELECT COUNT(DISTINCT sense_key) FROM sense_wordnet_links"
            ),
            "with_categories": q(
                "SELECT COUNT(DISTINCT sense_key) FROM sense_categories"
            ),
        }
