"""Unit tests for TalentRadarImporter normalizers (Phase 7a)."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import talent_radar_importer as tri


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
    assert result == date.today()
    result = tri.parse_availability("ASAP")
    assert result == date.today()


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
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
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
