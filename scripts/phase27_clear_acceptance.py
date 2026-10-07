"""Remove the §27/E2E acceptance fixtures from the development database.

`pnpm exec playwright test` seeds its own teacher (`acceptance@example.com`)
and student `John` via `scripts/phase27_seed_acceptance.py` and the suite
writes rows for them (assignments, FSRS states, review events, sets). The
handoff dump is taken from a database *without* those fixtures, so a restore
check against the live development database only matches after they are
removed again. The developer account is never touched: every delete here is
scoped to the acceptance teacher.

    backend/.venv/Scripts/python.exe scripts/phase27_clear_acceptance.py

(the seed script's RESET_TABLES is reused as the single source of truth for
the dependency-ordered table list, so the two can never drift).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend"))

from sqlalchemy import text

from scripts.phase27_seed_acceptance import EMAIL, RESET_TABLES


def main() -> int:
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        tid = conn.execute(
            text("SELECT id FROM teachers WHERE email = :email"), {"email": EMAIL}
        ).scalar()
        if tid is None:
            print(f"nothing to do: no teacher {EMAIL!r}")
            return 0
        for clause in RESET_TABLES:
            n = conn.execute(text(f"DELETE FROM {clause}"), {"tid": tid}).rowcount
            if n:
                print(f"  deleted {n:>4} from {clause.split(' WHERE')[0]}")
        n = conn.execute(
            text("DELETE FROM teachers WHERE id = :tid"), {"tid": tid}
        ).rowcount
        print(f"  deleted {n:>4} from teachers ({EMAIL})")
    print("acceptance fixtures cleared; the development database matches the "
          "dump again")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
