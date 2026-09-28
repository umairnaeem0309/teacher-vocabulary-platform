"""Phase 13 (section 89): import the construction DB into PostgreSQL.

Loads every construction table, assembles the import payload, and runs
`pipeline.storage.pg_import.import_vocabulary` in ONE transaction. Writes
the full section-89 report to data/construction/phase13_import_report.json.

Usage:
    cd backend
    PYTHONIOENCODING=utf-8 uv run python ../scripts/phase13_import.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.storage.pg_import import IMPORT_VERSION, import_vocabulary  # noqa: E402

SQLITE_PATH = REPO / "data" / "construction" / "construction.sqlite"
REPORT_PATH = REPO / "data" / "construction" / "phase13_import_report.json"
DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/vocab_platform"


def _rows(cur: sqlite3.Cursor) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def load_payload(path: Path) -> dict[str, list[dict]]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    payload = {
        "senses": _rows(cur.execute(
            "SELECT sense_key, key_version, headword_display, headword_search,"
            " pos_canonical, gloss_display, cefr_level, frequency_rank,"
            " tags_json, sources_json, processing_version FROM master_senses"
        )),
        "definitions": _rows(cur.execute(
            "SELECT sense_key, gloss_display FROM master_senses"
        )),
        "translations": _rows(cur.execute(
            "SELECT sense_key, translation, confidence, method FROM sense_translations"
        )),
        "examples": _rows(cur.execute(
            "SELECT sense_key, position, text, source FROM sense_examples"
        )),
        "cefr_evidence": _rows(cur.execute(
            "SELECT sense_key, source, cefr, pos_raw FROM sense_cefr_evidence"
        )),
        "frequency_evidence": _rows(cur.execute(
            "SELECT sense_key, source, rank, freq FROM sense_frequency_evidence"
        )),
        "priorities": _rows(cur.execute(
            "SELECT sense_key, score, level, version, components_json FROM sense_priorities"
        )),
        "categories": _rows(cur.execute(
            "SELECT node_key, name, parent_key, position FROM taxonomy_nodes"
        )),
        "sense_categories": _rows(cur.execute(
            "SELECT sense_key, category_key, subcategory_key, confidence, method"
            " FROM sense_categories"
        )),
        "wordnet_synsets": _rows(cur.execute(
            "SELECT synset_id, part_of_speech, definition, ili FROM wordnet_synsets"
        )),
        "wordnet_relations": _rows(cur.execute(
            "SELECT from_synset_id, to_synset_id, relation FROM wordnet_relations"
        )),
        "wordnet_links": _rows(cur.execute(
            "SELECT sense_key, synset_id, confidence FROM sense_wordnet_links"
        )),
    }
    con.close()
    return payload


def main() -> int:
    from sqlalchemy import create_engine

    payload = load_payload(SQLITE_PATH)
    sizes = {k: len(v) for k, v in payload.items()}
    print(f"payload (import {IMPORT_VERSION}): {json.dumps(sizes, sort_keys=True)}")

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn, conn.begin():
        report = import_vocabulary(conn, payload)
    engine.dispose()

    REPORT_PATH.write_text(report.as_json() + "\n", encoding="utf-8")
    print(f"report: {report.summary()}")
    print(f"detail: {json.dumps(report.detail, sort_keys=True)}")
    for w in report.warnings[:15]:
        print(f"  warn: {w}")
    if len(report.warnings) > 15:
        print(f"  ... and {len(report.warnings) - 15} more (see {REPORT_PATH.name})")
    print(f"full report written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
