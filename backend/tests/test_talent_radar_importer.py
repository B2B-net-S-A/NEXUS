"""Unit tests for TalentRadarImporter normalizers (Phase 7a)."""

from datetime import date, datetime, timezone

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


# ── parse_salary ─────────────────────────────────────────────────────────────


def test_salary_plain_number():
    assert tri.parse_salary("15000") == 15000


def test_salary_with_currency_and_text():
    assert tri.parse_salary("15000 PLN netto") == 15000
    assert tri.parse_salary("oczekiwania: 25000 zł") == 25000


def test_salary_with_range_takes_first_number():
    assert tri.parse_salary("15000-20000") == 15000


def test_salary_with_spaces_and_commas():
    assert tri.parse_salary("15 000") == 15000
    assert tri.parse_salary("15,000 PLN") == 15000


def test_salary_none_for_empty_or_non_numeric():
    assert tri.parse_salary(None) is None
    assert tri.parse_salary("") is None
    assert tri.parse_salary("negotiable") is None


def test_salary_rejects_too_short_numbers():
    # Regex requires 4-6 digits, so "500" won't match
    assert tri.parse_salary("500") is None


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
