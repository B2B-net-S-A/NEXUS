"""Unit tests for TalentRadarImporter normalizers (Phase 7a)."""

from datetime import date, datetime, timezone
from pathlib import Path
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
