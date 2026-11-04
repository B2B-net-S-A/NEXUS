"""Data wgrania pliku z Traffita zamiast daty importu (29.09.2026).

Pliki z Traffita pokazywały „dodano 05.05.2026” — dzień importu. Lista
``/employees/{id}/files`` niesie tylko ``id`` i ``name`` (fixture
``employee_files_list.json``, ``docs/traffit-discovery.md``), a prawdziwą datę
wgrania ma detal osoby: ``files: [{filename, file_uploaded}]`` — bez id pliku,
więc plik łączymy z datą po NAZWIE. Czas Traffita bez strefy to
Europe/Warsaw (ta sama reguła co ``_parse_traffit_datetime``).

Bez bazy: czyste funkcje, plan naprawy i faza plików na atrapach.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.services.object_storage as object_storage_mod
from app.services import traffit_file_dates_repair as repair
from app.services.traffit.importer import TraffitImporter
from app.services.traffit.mappers import (
    employee_files_from_detail,
    traffit_file_upload_date,
    traffit_file_upload_dates,
)

UTC = timezone.utc

# Zima (CET, UTC+1) i lato (CEST, UTC+2) — przesunięcie zależy od daty.
WINTER = "2026-02-19 15:32:00"
WINTER_UTC = datetime(2026, 2, 19, 14, 32, tzinfo=UTC)
SUMMER = "2025-07-10 09:00:00"
SUMMER_UTC = datetime(2025, 7, 10, 7, 0, tzinfo=UTC)
IMPORTED_AT = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)


# ── Czyste funkcje ───────────────────────────────────────────────────────────


def test_upload_dates_are_warsaw_time_including_dst() -> None:
    dates = traffit_file_upload_dates(
        [
            {"filename": "CV Jan.pdf", "file_uploaded": WINTER},
            {"filename": "list.docx", "file_uploaded": SUMMER},
        ]
    )

    assert traffit_file_upload_date("CV Jan.pdf", dates) == WINTER_UTC
    assert traffit_file_upload_date("list.docx", dates) == SUMMER_UTC


def test_name_match_ignores_case_and_surrounding_spaces() -> None:
    dates = traffit_file_upload_dates(
        [{"filename": " CV Jan.PDF ", "file_uploaded": WINTER}]
    )

    assert traffit_file_upload_date("cv jan.pdf", dates) == WINTER_UTC


def test_same_name_with_different_dates_is_not_guessed() -> None:
    dates = traffit_file_upload_dates(
        [
            {"filename": "cv.pdf", "file_uploaded": WINTER},
            {"filename": "cv.pdf", "file_uploaded": SUMMER},
        ]
    )

    assert "cv.pdf" in dates
    assert traffit_file_upload_date("cv.pdf", dates) is None


def test_same_name_with_the_same_date_keeps_the_date() -> None:
    dates = traffit_file_upload_dates(
        [
            {"filename": "cv.pdf", "file_uploaded": WINTER},
            {"filename": "cv.pdf", "file_uploaded": WINTER},
        ]
    )

    assert traffit_file_upload_date("cv.pdf", dates) == WINTER_UTC


def test_missing_or_broken_values_give_no_date() -> None:
    dates = traffit_file_upload_dates(
        [
            {"filename": "a.pdf", "file_uploaded": "nie-data"},
            {"filename": "b.pdf"},
            {"file_uploaded": WINTER},
            "śmieć",
        ]
    )

    assert traffit_file_upload_date("a.pdf", dates) is None
    assert traffit_file_upload_date("b.pdf", dates) is None
    assert traffit_file_upload_date("c.pdf", dates) is None
    assert traffit_file_upload_dates(None) == {}


def test_detail_payload_shapes() -> None:
    files = [{"filename": "a.pdf", "file_uploaded": WINTER}]

    assert employee_files_from_detail({"id": 1, "files": files}) == files
    assert employee_files_from_detail([{"id": 1, "files": files}]) == files
    assert employee_files_from_detail([]) == []
    assert employee_files_from_detail({"id": 1}) == []


# ── Plan naprawy (czysta funkcja) ────────────────────────────────────────────


def test_plan_sets_the_traffit_date_and_counts_the_rest() -> None:
    dates = traffit_file_upload_dates(
        [
            {"filename": "cv.pdf", "file_uploaded": WINTER},
            {"filename": "ok.pdf", "file_uploaded": SUMMER},
            {"filename": "dwa.pdf", "file_uploaded": WINTER},
            {"filename": "dwa.pdf", "file_uploaded": SUMMER},
        ]
    )
    docs = [
        repair.DocRow(doc_id=1, filename="cv.pdf", uploaded_at=None),
        repair.DocRow(doc_id=2, filename="ok.pdf", uploaded_at=SUMMER_UTC),
        repair.DocRow(doc_id=3, filename="dwa.pdf", uploaded_at=None),
        repair.DocRow(doc_id=4, filename="file-99", uploaded_at=IMPORTED_AT),
    ]

    changes, counts = repair.plan_documents(docs, dates)

    assert [(c.doc_id, c.old, c.new) for c in changes] == [(1, None, WINTER_UTC)]
    assert counts == {"changed": 1, "unchanged": 1, "no_date": 1, "no_match": 1}


def test_plan_overwrites_an_import_time_value() -> None:
    dates = traffit_file_upload_dates([{"filename": "cv.pdf", "file_uploaded": WINTER}])

    changes, _ = repair.plan_documents(
        [repair.DocRow(doc_id=7, filename="cv.pdf", uploaded_at=IMPORTED_AT)], dates
    )

    assert [(c.doc_id, c.old, c.new) for c in changes] == [(7, IMPORTED_AT, WINTER_UTC)]


# ── Faza plików importu (atrapy) ─────────────────────────────────────────────


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDB:
    def __init__(self, candidates):
        self.candidates = candidates
        self.upserts: list[dict] = []

    def begin_nested(self):
        return _Nested()

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        p = params or {}
        if "SELECT cursor_payload" in sql:
            return _Result([(None,)])
        if "FROM candidates c" in sql:
            rows = [
                SimpleNamespace(id=cid, external_id=ext) for cid, ext in self.candidates
            ]
            if "after_id" in p:
                rows = [r for r in rows if r.id > p["after_id"]][: p["limit"]]
            return _Result(rows)
        if "INSERT INTO candidate_documents" in sql:
            self.upserts.append(dict(p))
        return _Result([])

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.content = b"%PDF-1.4 fake"
        self.headers = {"content-type": "application/pdf"}

    def json(self):
        return self._payload


class _Http:
    async def get(self, url, headers=None):
        return _Resp()


class _FakeTraffit:
    def __init__(self, listings, details, detail_status=200):
        self.listings = listings
        self.details = details
        self.detail_status = detail_status
        self.detail_calls: list[str] = []
        self._http = _Http()
        self.config = SimpleNamespace(api_base="https://traffit.test/api")

    async def _get_raw(self, path, page=1, page_size=50):
        parts = path.strip("/").split("/")
        emp = parts[1]
        if len(parts) == 2:
            self.detail_calls.append(emp)
            return _Resp(self.detail_status, self.details.get(emp))
        return _Resp(payload=self.listings.get(emp, []))

    async def _ensure_token(self):
        return "token"

    async def _throttle(self):
        return None


@pytest.fixture(autouse=True)
def _no_object_storage(monkeypatch):
    monkeypatch.setattr(
        object_storage_mod,
        "upload_cv",
        lambda content=None, filename=None, content_type=None: "s3://fake-key",
    )


@pytest.mark.asyncio
async def test_import_writes_the_traffit_upload_date_from_the_detail() -> None:
    db = _FakeDB(candidates=[(1, "100")])
    traffit = _FakeTraffit(
        listings={"100": [{"id": 1, "name": "cv.pdf"}, {"id": 2, "name": "list.docx"}]},
        details={
            "100": {
                "id": 100,
                "files": [
                    {"filename": "cv.pdf", "file_uploaded": WINTER},
                    {"filename": "list.docx", "file_uploaded": SUMMER},
                ],
            }
        },
    )

    importer = TraffitImporter(traffit, db, dry_run=False, batch_size=100)
    progress = await importer.import_candidate_files(since=None)

    by_ext = {u["external_id"]: u["uploaded_at"] for u in db.upserts}
    assert by_ext == {"100-1": WINTER_UTC, "100-2": SUMMER_UTC}
    # Jeden detal na osobę, nie na plik.
    assert traffit.detail_calls == ["100"]
    assert progress.errors == 0


@pytest.mark.asyncio
async def test_listing_date_wins_and_skips_the_detail_call() -> None:
    db = _FakeDB(candidates=[(1, "100")])
    traffit = _FakeTraffit(
        listings={"100": [{"id": 1, "name": "cv.pdf", "file_uploaded": SUMMER}]},
        details={},
    )

    await TraffitImporter(traffit, db, dry_run=False).import_candidate_files(since=None)

    assert [u["uploaded_at"] for u in db.upserts] == [SUMMER_UTC]
    assert traffit.detail_calls == []


@pytest.mark.asyncio
async def test_failed_detail_leaves_the_date_empty_without_an_error() -> None:
    db = _FakeDB(candidates=[(1, "100")])
    traffit = _FakeTraffit(
        listings={"100": [{"id": 1, "name": "cv.pdf"}]}, details={}, detail_status=503
    )

    progress = await TraffitImporter(traffit, db, dry_run=False).import_candidate_files(
        since=None
    )

    assert [u["uploaded_at"] for u in db.upserts] == [None]
    # Data to wzbogacenie — plik i tak się zapisuje, faza nie jest zablokowana.
    assert progress.errors == 0
    assert progress.inserted == 1
