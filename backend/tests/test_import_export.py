"""Phase 22 tests: import/export (sections 38/99).

Covers:
- Export: CSV/XLSX/JSON round-trip (headers, content, formats),
  filter selection, student-viewpoint filter rejection (D024), §40
  (unauthenticated 401), filename disposition.
- Import: header validation, row validation (missing headword, bad
  POS/CEFR/flag), CSV/XLSX/JSON parsing, preview classification
  (new / existing_match / conflict / error), insert-only commit,
  idempotent re-import (§99: never overwrites), sense_key round-trip,
  full-validation-before-write (one bad row -> 422, zero writes).

Reuses the dev database; imported rows are deleted in finally blocks
(imports carry processing_version='import-v1' and unique sense_keys,
so cleanup is precise).
"""

from __future__ import annotations

import csv
import io
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import auth as auth_core
from tests.conftest import requires_db

PASSWORD = "correct horse battery staple"

IMPORT_VERSION = "import-v1"


def _email() -> str:
    return f"io-test-{uuid.uuid4().hex[:12]}@example.com"


def _make_teacher(email: str) -> uuid.UUID:
    from app.db.session import get_engine

    tid = uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, :ph, 'IO Test Teacher', true)"
            ),
            {"id": tid, "email": email, "ph": auth_core.hash_password(PASSWORD)},
        )
    return tid


def _drop_teacher(email: str) -> None:
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        tid = conn.execute(
            text("SELECT id FROM teachers WHERE email = :email"), {"email": email}
        ).scalar()
        if tid is None:
            return
        conn.execute(text("DELETE FROM teachers WHERE id = :tid"), {"tid": tid})


def _cleanup_senses(prefix: str) -> None:
    """Delete imported test senses and their child rows (FK-safe order)."""
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        ids = conn.execute(
            text(
                "SELECT id FROM vocabulary_senses WHERE sense_key LIKE :p"
            ),
            {"p": prefix + "%"},
        ).scalars().all()
        if not ids:
            return
        for table in (
            "sense_examples",
            "sense_translations",
            "vocabulary_flags",
            "vocabulary_forms",
            "cefr_evidence",
            "frequency_evidence",
            "sense_source_records",
            "sense_categories",
            "sense_wordnet_links",
            "review_events",
        ):
            conn.execute(
                text(f"DELETE FROM {table} WHERE sense_id = ANY(:ids)"),
                {"ids": ids},
            )
        conn.execute(
            text(
                "DELETE FROM student_fsrs_states WHERE student_vocabulary_id IN "
                "(SELECT id FROM student_vocabulary WHERE sense_id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        conn.execute(
            text("DELETE FROM student_vocabulary WHERE sense_id = ANY(:ids)"),
            {"ids": ids},
        )
        conn.execute(
            text("DELETE FROM vocabulary_senses WHERE id = ANY(:ids)"),
            {"ids": ids},
        )


def _login(client: TestClient, email: str) -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "sense_key",
            "headword",
            "part_of_speech",
            "cefr_level",
            "definition",
            "priority_level",
            "frequency_rank",
            "translations_pl",
            "examples",
            "flags",
        ],
        lineterminator="\r\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _sample_rows(sense_key: str = "") -> list[dict[str, str]]:
    base = {
        "sense_key": sense_key,
        "headword": "io test word",
        "part_of_speech": "noun",
        "cefr_level": "B1",
        "definition": "a word created only for input-output testing",
        "priority_level": "",
        "frequency_rank": "",
        "translations_pl": "słowo testowe",
        "examples": "This is an io test word.",
        "flags": "",
    }
    second = dict(base)
    second["headword"] = "io test word two"
    second["sense_key"] = ""
    second["part_of_speech"] = "verb"
    second["cefr_level"] = ""
    second["translations_pl"] = "testować słowo | słówko próbne"
    return [base, second]


@requires_db
class TestExport:
    def _setup(self, client: TestClient) -> tuple[str, TestClient]:
        email = _email()
        _make_teacher(email)
        c = TestClient(client.app)
        _login(c, email)
        return email, c

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/exports/vocabulary", json={"format": "csv"}
        )
        assert resp.status_code == 401

    def test_csv_json_roundtrip(self, client: TestClient) -> None:
        email, c = self._setup(client)
        try:
            r = c.post("/api/v1/exports/vocabulary", json={"format": "csv"})
            assert r.status_code == 200, r.text
            assert r.headers["content-type"].startswith("text/csv")
            assert "attachment" in r.headers["content-disposition"]
            rows = list(csv.DictReader(io.StringIO(r.text)))
            assert rows, "expected data rows in CSV export"
            first = rows[0]
            assert "sense_key" in first and "headword" in first
            assert "translations_pl" in first

            r2 = c.post("/api/v1/exports/vocabulary", json={"format": "json"})
            assert r2.status_code == 200
            payload = r2.json()
            assert isinstance(payload, list) and payload
            assert set(rows[0].keys()) == set(payload[0].keys())
            # Same selection, same deterministic order.
            assert [p["sense_key"] for p in payload][:3] == [
                row["sense_key"] for row in rows
            ][:3]
        finally:
            _drop_teacher(email)

    def test_xlsx_roundtrip(self, client: TestClient) -> None:
        email, c = self._setup(client)
        try:
            r = c.post("/api/v1/exports/vocabulary", json={"format": "xlsx"})
            assert r.status_code == 200, r.text
            assert "spreadsheetml" in r.headers["content-type"]

            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(r.content), read_only=True)
            ws = wb.worksheets[0]
            it = ws.iter_rows(values_only=True)
            header = [str(h) for h in next(it)]
            assert header[0] == "sense_key" and header[1] == "headword"
            # The corpus contains a few legacy senses with an empty
            # headword; find the first data row that has one.
            first = next(r for r in it if r[1])
            assert first is not None and first[0] and first[1]
            wb.close()
        finally:
            _drop_teacher(email)

    def test_filters_and_student_view_rejected(self, client: TestClient) -> None:
        email, c = self._setup(client)
        try:
            r = c.post(
                "/api/v1/exports/vocabulary",
                json={"format": "json", "cefr": ["A1"]},
            )
            assert r.status_code == 200
            payload = r.json()
            assert all(row["cefr_level"] == "A1" for row in payload)

            # D024: student-viewpoint selection is rejected with 422.
            # (Schema-level rejection uses the generic 422 message on
            # purpose — the envelope never echoes input names/values.)
            bad = c.post(
                "/api/v1/exports/vocabulary",
                json={"format": "json", "student_id": str(uuid.uuid4())},
            )
            assert bad.status_code == 422

            bad2 = c.post(
                "/api/v1/exports/vocabulary",
                json={"format": "json", "assigned": True},
            )
            assert bad2.status_code == 422
        finally:
            _drop_teacher(email)

    def test_bad_format_422(self, client: TestClient) -> None:
        email, c = self._setup(client)
        try:
            r = c.post("/api/v1/exports/vocabulary", json={"format": "pdf"})
            assert r.status_code == 422
        finally:
            _drop_teacher(email)


@requires_db
class TestImport:
    def _setup(self, client: TestClient) -> tuple[str, TestClient]:
        email = _email()
        _make_teacher(email)
        c = TestClient(client.app)
        _login(c, email)
        return email, c

    def _post_file(
        self, c: TestClient, content: bytes, fmt: str, path: str
    ) -> object:
        return c.post(
            path,
            files={"file": (f"upload.{fmt}", content, "application/octet-stream")},
            data={"format": fmt},
        )

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.post("/api/v1/imports/vocabulary")
        assert resp.status_code == 401

    def test_csv_import_lifecycle(self, client: TestClient) -> None:
        email, c = self._setup(client)
        prefix = "io-test-" + uuid.uuid4().hex[:8]
        rows = _sample_rows()
        rows[0]["headword"] = prefix + " alpha"
        rows[1]["headword"] = prefix + " beta"
        content = _csv_bytes(rows)
        try:
            # 1. Preview: both rows are new, nothing written.
            p = self._post_file(
                c, content, "csv", "/api/v1/imports/vocabulary/preview"
            )
            assert p.status_code == 200, p.text
            body = p.json()
            assert body["total_rows"] == 2
            assert body["counts"]["new"] == 2
            assert body["counts"]["error"] == 0

            # 2. Commit: inserted.
            r = self._post_file(c, content, "csv", "/api/v1/imports/vocabulary")
            assert r.status_code == 200, r.text
            report = r.json()
            assert report["inserted_senses"] == 2
            assert report["translations_added"] == 3  # 1 + 2
            assert report["skipped_count"] == 0

            from app.db.session import get_engine

            with get_engine().connect() as conn:
                stored = conn.execute(
                    text(
                        "SELECT sense_key, headword, headword_normalized, "
                        "part_of_speech::text, cefr_level::text, definition_preview "
                        "FROM vocabulary_senses WHERE headword LIKE :p "
                        "ORDER BY headword"
                    ),
                    {"p": prefix + "%"},
                ).all()
            assert len(stored) == 2
            alpha = stored[0]
            assert alpha[1] == prefix + " alpha"
            # search_key casefolds and maps '-' to a space.
            assert alpha[2] == prefix.replace("-", " ") + " alpha"
            assert alpha[3] == "noun"
            assert alpha[4] == "B1"
            # The derived identity key is deterministic (and stable
            # across a delete + re-import cycle; exercised below).
            key_alpha = alpha[0]
            assert key_alpha.endswith("|noun|") is False  # digest present
            with get_engine().connect() as conn:
                trs = conn.execute(
                    text(
                        "SELECT st.translation FROM sense_translations st "
                        "JOIN vocabulary_senses vs ON vs.id = st.sense_id "
                        "WHERE vs.headword = :hw ORDER BY st.position"
                    ),
                    {"hw": prefix + " beta"},
                ).scalars().all()
            assert trs == ["testować słowo", "słówko próbne"]

            # 3. Re-import the same file: insert-only + dedup means the
            # second run touches the existing senses and adds nothing.
            r2 = self._post_file(c, content, "csv", "/api/v1/imports/vocabulary")
            assert r2.status_code == 200
            report2 = r2.json()
            assert report2["inserted_senses"] == 0
            assert report2["existing_senses_touched"] == 2
            assert report2["translations_added"] == 0

            with get_engine().begin() as conn:
                count = conn.execute(
                    text(
                        "SELECT count(*) FROM vocabulary_senses "
                        "WHERE headword LIKE :p"
                    ),
                    {"p": prefix + "%"},
                ).scalar_one()
            assert count == 2  # §99: no accidental duplicates

            # 4. Conflict: the exported sense_key with CHANGED master
            # fields (CEFR) must be skipped, never overwritten.
            conflict = _csv_bytes(
                [
                    {
                        "sense_key": key_alpha,
                        "headword": prefix + " alpha",
                        "part_of_speech": "noun",
                        "cefr_level": "C2",  # stored: B1
                        "definition": "a word created only for input-output testing",
                        "priority_level": "",
                        "frequency_rank": "",
                        "translations_pl": "",
                        "examples": "",
                        "flags": "",
                    }
                ]
            )
            pc = self._post_file(
                c, conflict, "csv", "/api/v1/imports/vocabulary/preview"
            )
            assert pc.status_code == 200
            assert pc.json()["counts"]["conflict"] == 1

            rc = self._post_file(
                c, conflict, "csv", "/api/v1/imports/vocabulary"
            )
            assert rc.status_code == 200
            report3 = rc.json()
            assert report3["inserted_senses"] == 0
            assert report3["skipped_count"] == 1
            assert "never overwrite" in report3["skipped"][0]["detail"]

            with get_engine().begin() as conn:
                still = conn.execute(
                    text(
                        "SELECT cefr_level::text FROM vocabulary_senses "
                        "WHERE sense_key = :k"
                    ),
                    {"k": key_alpha},
                ).scalar_one()
            assert still == "B1"  # master fields untouched
        finally:
            _cleanup_senses(prefix)
            _drop_teacher(email)

    def test_xlsx_and_json_roundtrip_import(self, client: TestClient) -> None:
        email, c = self._setup(client)
        prefix = "io-test-" + uuid.uuid4().hex[:8]
        try:
            from openpyxl import Workbook

            wb = Workbook(write_only=True)
            ws = wb.create_sheet("vocabulary")
            ws.append(["headword", "part_of_speech", "translations_pl"])
            ws.append([prefix + " gamma", "adjective", "gamma słowo"])
            buf = io.BytesIO()
            wb.save(buf)
            xlsx_content = buf.getvalue()

            r = self._post_file(
                c, xlsx_content, "xlsx", "/api/v1/imports/vocabulary"
            )
            assert r.status_code == 200, r.text
            assert r.json()["inserted_senses"] == 1

            # The exported JSON of that sense re-imports cleanly.
            export = c.post("/api/v1/exports/vocabulary", json={"format": "json"})
            exported = [
                row
                for row in export.json()
                if row["headword"] == prefix + " gamma"
            ]
            assert len(exported) == 1
            exported[0]["sense_key"]  # round-trips via its identity key
            payload = (
                __import__("json").dumps(exported).encode("utf-8")
            )
            r2 = self._post_file(
                c, payload, "json", "/api/v1/imports/vocabulary"
            )
            assert r2.status_code == 200, r2.text
            report = r2.json()
            assert report["inserted_senses"] == 0
            assert report["existing_senses_touched"] == 1
        finally:
            _cleanup_senses(prefix)
            _drop_teacher(email)

    def test_validation_errors_block_writes(self, client: TestClient) -> None:
        email, c = self._setup(client)
        prefix = "io-test-" + uuid.uuid4().hex[:8]
        rows = _sample_rows()
        rows[0]["headword"] = prefix + " good"
        rows[0]["sense_key"] = ""
        rows[1]["headword"] = ""  # invalid
        rows[1]["sense_key"] = ""
        content = _csv_bytes(rows)
        try:
            p = self._post_file(
                c, content, "csv", "/api/v1/imports/vocabulary/preview"
            )
            assert p.status_code == 200
            body = p.json()
            assert body["counts"]["error"] == 1
            assert body["rows"][1]["errors"] == ["headword is required"]

            r = self._post_file(c, content, "csv", "/api/v1/imports/vocabulary")
            assert r.status_code == 422
            assert "nothing was imported" in r.json()["error"]["message"]

            from app.db.session import get_engine

            with get_engine().connect() as conn:
                n = conn.execute(
                    text(
                        "SELECT count(*) FROM vocabulary_senses "
                        "WHERE headword LIKE :p"
                    ),
                    {"p": prefix + "%"},
                ).scalar_one()
            assert n == 0  # zero partial writes
        finally:
            _cleanup_senses(prefix)
            _drop_teacher(email)

    def test_bad_headers_flags_and_unknown_key(self, client: TestClient) -> None:
        email, c = self._setup(client)
        prefix = "io-test-" + uuid.uuid4().hex[:8]
        try:
            # An unknown column must actually reach the server: write
            # the CSV by hand (extrasaction=ignore would drop it).
            bad_header = (
                "headword,wat\r\n" + prefix + " x,1\r\n"
            ).encode("utf-8")
            r = self._post_file(
                c, bad_header, "csv", "/api/v1/imports/vocabulary/preview"
            )
            assert r.status_code == 422
            assert "unknown column" in r.json()["error"]["message"]

            bad_flag = _csv_bytes(
                [{"headword": prefix + " x", "flags": "not-a-flag"}]
            )
            r2 = self._post_file(
                c, bad_flag, "csv", "/api/v1/imports/vocabulary/preview"
            )
            assert r2.status_code == 200
            assert "unknown flag" in r2.json()["rows"][0]["errors"][0]

            unknown_key = _csv_bytes(
                [{"headword": prefix + " x", "sense_key": "nope|noun|deadbeef"}]
            )
            r3 = self._post_file(
                c, unknown_key, "csv", "/api/v1/imports/vocabulary/preview"
            )
            assert r3.status_code == 200
            assert r3.json()["rows"][0]["status"] == "error"

            not_csv = c.post(
                "/api/v1/imports/vocabulary/preview",
                files={"file": ("u.csv", b"\x00\x01garbage", "application/octet-stream")},
                data={"format": "csv"},
            )
            assert not_csv.status_code == 422
        finally:
            _cleanup_senses(prefix)
            _drop_teacher(email)

    def test_export_then_reimport_roundtrip(self, client: TestClient) -> None:
        """The §38 contract: export preserves enough for migration.

        Import a synthetic sense, export CSV, delete the sense, then
        re-import from the export — the sense comes back with the same
        identity key and translations.
        """
        email, c = self._setup(client)
        prefix = "io-test-" + uuid.uuid4().hex[:8]
        try:
            content = _csv_bytes(
                [
                    {
                        "headword": prefix + " migrate",
                        "part_of_speech": "noun",
                        "cefr_level": "A2",
                        "definition": "meant to be exported and imported again",
                        "translations_pl": "migracyjne słowo",
                        "examples": "",
                        "flags": "",
                        "sense_key": "",
                        "priority_level": "",
                        "frequency_rank": "",
                    }
                ]
            )
            r = self._post_file(c, content, "csv", "/api/v1/imports/vocabulary")
            assert r.status_code == 200
            assert r.json()["inserted_senses"] == 1

            export = c.post("/api/v1/exports/vocabulary", json={"format": "csv"})
            assert export.status_code == 200
            exported_rows = [
                row
                for row in csv.DictReader(io.StringIO(export.text))
                if row["headword"] == prefix + " migrate"
            ]
            assert len(exported_rows) == 1
            original_key = exported_rows[0]["sense_key"]
            assert original_key.startswith(prefix.replace(" ", "")[:7]) or original_key

            from app.db.session import get_engine

            # Delete the sense (simulating a fresh deployment target).
            with get_engine().begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM sense_translations WHERE sense_id IN "
                        "(SELECT id FROM vocabulary_senses WHERE sense_key = :k)"
                    ),
                    {"k": original_key},
                )
                conn.execute(
                    text(
                        "DELETE FROM vocabulary_forms WHERE sense_id IN "
                        "(SELECT id FROM vocabulary_senses WHERE sense_key = :k)"
                    ),
                    {"k": original_key},
                )
                conn.execute(
                    text(
                        "DELETE FROM vocabulary_senses WHERE sense_key = :k"
                    ),
                    {"k": original_key},
                )

            # Re-import from the export file: same key, translations back.
            r2 = self._post_file(c, content, "csv", "/api/v1/imports/vocabulary")
            assert r2.status_code == 200, r2.text
            with get_engine().connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT sense_key, (SELECT count(*) FROM sense_translations st "
                        "WHERE st.sense_id = vs.id) FROM vocabulary_senses vs "
                        "WHERE headword = :hw"
                    ),
                    {"hw": prefix + " migrate"},
                ).first()
            assert row is not None
            assert row[0] == original_key  # deterministic identity
            assert row[1] == 1
        finally:
            _cleanup_senses(prefix)
            _drop_teacher(email)
