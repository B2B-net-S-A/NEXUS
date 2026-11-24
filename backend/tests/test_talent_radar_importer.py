"""Unit tests for TalentRadarImporter normalizers (Phase 7a)."""

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import talent_radar_importer as tri
from app.core.scheduling import business_today


# ── normalize_seniority ─────────────────────────────────────────────────────


def test_seniority_known_values():
    assert tri.normalize_seniority("Junior") == "junior"
    assert tri.normalize_seniority("SENIOR") == "senior"
    assert tri.normalize_seniority("Tech Lead") == "lead"
    assert tri.normalize_seniority("Principal") == "architect"


def test_seniority_aliases():
    assert tri.normalize_seniority("Sr") == "senior"
    assert tri.normalize_seniority("Middle") == "mid"
    assert tri.normalize_seniority("Regular") == "mid"


def test_seniority_unknown_kept_as_lowercase():
    assert tri.normalize_seniority("Unicorn") == "unicorn"


def test_seniority_none_returns_none():
    assert tri.normalize_seniority(None) is None
    assert tri.normalize_seniority("") is None


# ── parse_availability ───────────────────────────────────────────────────────


def test_availability_iso_date():
    assert tri.parse_availability("2026-06-01") == date(2026, 6, 1)


def test_availability_eu_format():
    assert tri.parse_availability("01.06.2026") == date(2026, 6, 1)


def test_availability_slash_format():
    assert tri.parse_availability("01/06/2026") == date(2026, 6, 1)


def test_availability_immediately_keyword():
    # Returns today
    result = tri.parse_availability("natychmiast")
    assert result == business_today()
    result = tri.parse_availability("ASAP")
    assert result == business_today()


def test_availability_none_for_invalid():
    assert tri.parse_availability(None) is None
    assert tri.parse_availability("") is None
    assert tri.parse_availability("maybe next year") is None


# ── to_datetime_utc ──────────────────────────────────────────────────────────


def test_to_datetime_from_date():
    d = date(2026, 3, 19)
    result = tri.to_datetime_utc(d)
    assert result is not None
    assert result.year == 2026
    assert result.month == 3
    assert result.day == 19
    assert result.hour == 0
    assert result.tzinfo is timezone.utc


def test_to_datetime_preserves_existing_tz():
    dt = datetime(2026, 3, 19, 14, 30, tzinfo=timezone.utc)
    assert tri.to_datetime_utc(dt) == dt


def test_to_datetime_adds_utc_to_naive():
    dt = datetime(2026, 3, 19, 14, 30)
    result = tri.to_datetime_utc(dt)
    assert result is not None
    assert result.tzinfo is timezone.utc


def test_to_datetime_none():
    assert tri.to_datetime_utc(None) is None


# ── ImportProgress serialization ─────────────────────────────────────────────


def test_import_progress_as_dict():
    p = tri.ImportProgress(processed=10, inserted=8, updated=1, errors=1, total=100)
    d = p.as_dict()
    assert d["processed"] == 10
    assert d["inserted"] == 8
    assert d["updated"] == 1
    assert d["errors"] == 1
    assert d["total"] == 100
    assert d["error_samples"] == []


def test_import_progress_caps_error_samples_at_20():
    p = tri.ImportProgress()
    for i in range(30):
        p.error_samples.append(f"error {i}")
    assert len(p.as_dict()["error_samples"]) == 20


def test_payload_normalizes_location_to_canonical_facts():
    importer = tri.TalentRadarImporter(
        source_dsn="",
        target_db=object(),
        dry_run=True,
    )
    row = {
        "id": 987,
        "traffit_id": 123,
        "email": None,
        "name": "Anna",
        "lastname": "Nowak",
        "raw_cv_text": None,
        "cv_content": None,
        "cv_filename": None,
        "extracted_data": None,
        "skills": None,
        "experience_years": None,
        "seniority": None,
        "languages": None,
        "location": "Berlin, Niemcy",
        "availability": None,
        "cv_language": None,
        "cv_date": None,
    }

    payload = importer._to_payload(row)  # type: ignore[arg-type]

    assert payload["city"] == "Berlin"
    assert payload["country"] == "DE"
    assert payload["location"] == "Berlin, DE"
    assert payload["talent_radar_source_id"] == 987


@pytest.mark.asyncio
async def test_existing_talent_radar_identity_is_reviewed_before_merge(monkeypatch):
    candidate = SimpleNamespace(id=7, name="Jan", lastname="Kowalski")
    review = SimpleNamespace(is_quarantined=True)
    db = SimpleNamespace(scalar=AsyncMock(return_value=candidate))
    captured: dict[str, object] = {}

    async def fake_record(_db, **kwargs):
        captured.update(kwargs)
        return review

    monkeypatch.setattr(
        "app.services.candidate_identity_quarantine.record_detected_identity",
        fake_record,
    )
    importer = tri.TalentRadarImporter(
        source_dsn="",
        target_db=db,
        dry_run=False,
    )
    payload = {
        "talent_radar_source_id": 987,
        "name": "Anna",
        "lastname": "Nowak",
    }

    assert await importer._existing_source_is_quarantined(7, payload) is True
    assert captured["source_kind"] == "talent_radar_cv"
    assert captured["source_id"] == 987
    assert captured["observed_first_name"] == "Anna"
    assert captured["observed_last_name"] == "Nowak"


@pytest.mark.asyncio
async def test_quarantined_talent_radar_source_never_reaches_merge_writers(
    monkeypatch,
):
    # Punkt zapisu per wiersz (audyt 24.11.2026) — sesja musi go mieć.
    db = SimpleNamespace(
        execute=AsyncMock(), commit=AsyncMock(), begin_nested=lambda: _Savepoint()
    )
    importer = tri.TalentRadarImporter("", db, dry_run=False)
    monkeypatch.setattr(importer, "_find_existing_id", AsyncMock(return_value=7))
    monkeypatch.setattr(
        importer,
        "_existing_source_is_quarantined",
        AsyncMock(return_value=True),
    )
    storage_work = AsyncMock()
    monkeypatch.setattr(tri.asyncio, "to_thread", storage_work)

    result = await importer._upsert(
        [
            {
                "talent_radar_source_id": 987,
                "external_id": "123",
                "name": "Anna",
                "lastname": "Nowak",
                "languages": [{"code": "en", "name": "English"}],
                "city": "Berlin",
                "country": "DE",
            }
        ]
    )

    assert result == (0, 0)
    assert importer.quarantined == 1
    storage_work.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_talent_radar_dry_run_never_uploads_cv(monkeypatch):
    importer = tri.TalentRadarImporter("", object(), dry_run=True)
    storage_work = AsyncMock()
    monkeypatch.setattr(tri.asyncio, "to_thread", storage_work)

    assert await importer._upsert(
        [{"talent_radar_source_id": 1, "cv_file_content": b"private"}]
    ) == (0, 0)
    storage_work.assert_not_awaited()


def test_no_python_constant_leaks_into_a_non_f_string_sql_body():
    """A bare Python name inside ``text("...")`` reaches Postgres as an identifier.

    ``_UPSERT_CANDIDATE_DOCUMENT`` shipped with a bare ``SOURCE_VALUE`` where the
    original had the SQL literal ``'talent_radar'``. The body is a plain string,
    not an f-string, so Postgres would have parsed it as a column reference and
    failed with ``column "source_value" does not exist`` on every CV upsert.

    CI stayed green over it because every test in this module replaces
    ``db.execute`` with an ``AsyncMock`` — the statement is asserted on, never
    parsed. So the guard cannot be "does this one line look right"; it has to be
    the shape of the mistake, checked across the whole backend. Renaming the
    constant, or repeating the slip in another module, still trips it.
    """

    import ast
    import re

    app_root = Path(__file__).resolve().parents[1] / "app"
    leaks: list[str] = []

    for path in sorted(app_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - app/ must import anyway
            continue
        constants = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id.isupper()
        }
        if not constants:
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "text"
                and node.args
            ):
                continue
            body = node.args[0]
            if not (isinstance(body, ast.Constant) and isinstance(body.value, str)):
                continue  # f-strings interpolate; only plain bodies can leak
            for name in constants:
                # Not preceded by ':' — that is a bind parameter, which is fine.
                if re.search(rf"(?<![\w:]){re.escape(name)}(?![\w])", body.value):
                    leaks.append(
                        f"{path.relative_to(app_root.parent)}:{node.lineno} → {name}"
                    )

    assert not leaks, "Python name(s) embedded in SQL text: " + "; ".join(leaks)


# ── Paczka: błąd jednego wiersza (audyt 24.11.2026) ─────────────────────────
#
# Do 24.11 jeden zły wiersz cofał całą paczkę (rollback w `run()`), a mapy
# dedupu miały już id wierszy sprzed rollbacku: następne paczki „scalały”
# osoby z nieistniejącymi rekordami. CV wysłane do magazynu przed INSERT-em
# zostawały w nim bez właściciela.


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _BatchDb:
    """Sesja z punktami zapisu; INSERT wiersza ``fail_ext`` pada."""

    def __init__(self, importer_sql, *, fail_ext=None, fail_commit=False):
        self.importer_sql = importer_sql
        self.fail_ext = fail_ext
        self.fail_commit = fail_commit
        self.next_id = 100
        self.savepoints = 0
        self.commits = 0
        self.rollbacks = 0

    def begin_nested(self):
        self.savepoints += 1
        return _Savepoint()

    async def execute(self, sql, params=None):
        if sql is self.importer_sql:
            if params["external_id"] == self.fail_ext:
                raise RuntimeError("duplicate key value violates unique constraint")
            self.next_id += 1
            new_id = self.next_id
            return SimpleNamespace(fetchone=lambda: (new_id, True))
        return SimpleNamespace(fetchone=lambda: None)

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("connection lost")
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _batch_payload(ext: str) -> dict:
    return {
        "talent_radar_source_id": int(ext),
        "external_id": ext,
        "external_source": tri.SOURCE_VALUE,
        "email": f"osoba{ext}@example.test",
        "name": "Osoba",
        "lastname": f"Testowa{ext}",
        "raw_cv_text": "CV",
        "cv_file_content": b"%PDF-fikcyjne",
        "cv_storage_key": None,
        "cv_filename": f"cv-{ext}.pdf",
        "cv_extracted_data": {},
        "skills": [],
        "years_it_experience": None,
        "competence_category": None,
        "availability_date": None,
        "cv_language": None,
        "cv_parsed_at": None,
        "source": tri.SOURCE_VALUE,
        "status": "active",
    }


@pytest.fixture
def storage(monkeypatch):
    uploaded: list[str] = []
    deleted: list[str] = []

    def fake_upload(*, content, filename, content_type):
        key = f"cvs/0000000{len(uploaded)}-aaaa-bbbb-cccc-dddddddddddd-{filename}"
        uploaded.append(key)
        return key

    async def run_inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def no_dupes(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.services.object_storage.is_available", lambda: True)
    monkeypatch.setattr("app.services.object_storage.upload_cv", fake_upload)
    monkeypatch.setattr("app.services.object_storage.delete_cv", deleted.append)
    monkeypatch.setattr(tri.asyncio, "to_thread", run_inline)
    monkeypatch.setattr(tri, "find_candidate_duplicates", no_dupes)
    return SimpleNamespace(uploaded=uploaded, deleted=deleted)


@pytest.mark.asyncio
async def test_one_bad_row_does_not_roll_back_the_batch(storage):
    importer = tri.TalentRadarImporter("", None, dry_run=False)
    db = _BatchDb(importer._INSERT_SQL, fail_ext="2")
    importer.target_db = db

    result = await importer._upsert([_batch_payload(e) for e in ("1", "2", "3")])

    assert result == (2, 0)
    assert db.savepoints == 3
    assert db.commits == 1
    assert importer.row_errors == 1
    assert len(importer.row_error_samples) == 1
    assert "osoba2@example.test" not in importer.row_error_samples[0]
    # Mapy dedupu tylko z wierszami, które się zapisały.
    assert set(importer._ext_id_to_id) == {"1", "3"}
    assert set(importer._email_to_id) == {"osoba1@example.test", "osoba3@example.test"}
    # CV wiersza, który padł po wysłaniu do magazynu, zostaje usunięte.
    assert storage.deleted == [storage.uploaded[1]]


@pytest.mark.asyncio
async def test_failed_batch_commit_forgets_ids_and_removes_uploaded_cvs(storage):
    importer = tri.TalentRadarImporter("", None, dry_run=False)
    importer._email_to_id = {"stara@example.test": 5}
    importer.target_db = _BatchDb(importer._INSERT_SQL, fail_commit=True)

    with pytest.raises(RuntimeError):
        await importer._upsert([_batch_payload(e) for e in ("1", "3")])

    assert importer._ext_id_to_id == {}
    assert importer._email_to_id == {"stara@example.test": 5}
    assert sorted(storage.deleted) == sorted(storage.uploaded)


@pytest.mark.asyncio
async def test_run_counts_only_the_failed_row_as_error(storage, monkeypatch):
    importer = tri.TalentRadarImporter("", None, batch_size=10, dry_run=False)
    db = _BatchDb(importer._INSERT_SQL, fail_ext="2")
    importer.target_db = db
    conn = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(tri.asyncpg, "connect", AsyncMock(return_value=conn))
    monkeypatch.setattr(importer, "_count_source", AsyncMock(return_value=3))
    monkeypatch.setattr(importer, "_preload_dedup_maps", AsyncMock())
    batches = [[{"id": e} for e in ("1", "2", "3")], []]
    monkeypatch.setattr(
        importer, "_fetch_batch", AsyncMock(side_effect=lambda *_: batches.pop(0))
    )
    monkeypatch.setattr(importer, "_to_payload", lambda row: _batch_payload(row["id"]))

    progress = None
    async for progress in importer.run():
        pass

    assert progress.inserted == 2
    assert progress.errors == 1
    assert len(progress.error_samples) == 1
    assert db.rollbacks == 0
