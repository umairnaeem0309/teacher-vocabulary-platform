"""SQLite construction database (sections 44, 84).

NOT the production database — this is the pipeline's local workbench for
dedup debugging, QC and reproducible re-processing (section 44).

Schema is pipeline-private (keyed by sense_key, versioned) and deliberately
simpler than PostgreSQL's normalized schema: it stores what QC needs.
Batched inserts keep memory bounded (sections 48, 125).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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
        return int(cur.lastrowid)

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

    def count_senses(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM master_senses").fetchone()[0])

    def count_translations(self) -> int:
        return int(
            self.conn.execute("SELECT COUNT(*) FROM sense_translations").fetchone()[0]
        )

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
        }
