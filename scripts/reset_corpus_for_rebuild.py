"""Retire corpus senses that are no longer in the construction DB.

Companion to `scripts/reset_teachers.sql` (which clears teacher-owned rows and
explicitly leaves the corpus alone). This one does the opposite: after a corpus
rebuild, any sense in PostgreSQL whose `sense_key` is absent from the current
construction database belongs to the *previous* corpus and must go, because a
later `phase13_import.py` only upserts — it never deletes.

Two tables reference `vocabulary_senses` with ON DELETE RESTRICT, so they are
cleared first for the retiring set only:

    review_events        RESTRICT   (review history of the retired senses)
    student_vocabulary   RESTRICT   (assignments of the retired senses)

Everything else (definitions, translations, evidence, categories, examples,
priorities, flags, forms, embeddings, set items, priority overrides) cascades.
Teacher accounts, students and sessions are never touched. Retired assignments
are unavoidable: the sense identity they pointed at no longer exists.

Usage:
    backend/.venv/Scripts/python.exe scripts/reset_corpus_for_rebuild.py --dry-run
    backend/.venv/Scripts/python.exe scripts/reset_corpus_for_rebuild.py --confirm
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from sqlalchemy import create_engine, text  # noqa: E402

DB_PATH = REPO / "data" / "construction" / "construction.sqlite"
BATCH = 5000


def _new_keys(path: Path) -> list[str]:
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT sense_key FROM master_senses")]
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually delete (without it the run only reports)",
    )
    args = parser.parse_args()

    keys = _new_keys(args.db)
    print(f"construction DB holds {len(keys)} senses")

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set")
        return 1
    engine = create_engine(url, pool_pre_ping=True)

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE IF NOT EXISTS new_sense_keys "
                "(sense_key text PRIMARY KEY) ON COMMIT DROP"
            )
        )
        for start in range(0, len(keys), BATCH):
            conn.execute(
                text("INSERT INTO new_sense_keys (sense_key) VALUES (:k) ON CONFLICT DO NOTHING"),
                [{"k": k} for k in keys[start : start + BATCH]],
            )

        stale = conn.execute(
            text(
                "SELECT count(*) FROM vocabulary_senses "
                "WHERE sense_key NOT IN (SELECT sense_key FROM new_sense_keys)"
            )
        ).scalar()
        total = conn.execute(text("SELECT count(*) FROM vocabulary_senses")).scalar()
        keep = total - stale
        print(f"postgres holds {total} senses; retiring {stale}, keeping/upserting {keep}")

        for table, column in (
            ("review_events", "sense_id"),
            ("student_vocabulary", "sense_id"),
        ):
            n = conn.execute(
                text(
                    f"SELECT count(*) FROM {table} WHERE {column} IN ("
                    "SELECT id FROM vocabulary_senses WHERE sense_key NOT IN ("
                    "SELECT sense_key FROM new_sense_keys))"
                )
            ).scalar()
            print(f"  {table}: {n} row(s) reference retiring senses")

        if not args.confirm:
            print("dry run — pass --confirm to delete")
            return 0

        for table, column in (
            ("review_events", "sense_id"),
            ("student_vocabulary", "sense_id"),
        ):
            conn.execute(
                text(
                    f"DELETE FROM {table} WHERE {column} IN ("
                    "SELECT id FROM vocabulary_senses WHERE sense_key NOT IN ("
                    "SELECT sense_key FROM new_sense_keys))"
                )
            )

        result = conn.execute(
            text(
                "DELETE FROM vocabulary_senses WHERE sense_key NOT IN "
                "(SELECT sense_key FROM new_sense_keys)"
            )
        )
        print(f"deleted {result.rowcount} stale sense(s); cascades applied")

    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
