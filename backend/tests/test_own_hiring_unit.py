"""Rekrutacja własna: czyste reguły, bez bazy."""

from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.own_hiring.candidate_filter import (
    classify,
    normalize_title,
    parse_offer_note,
)
from app.services.own_hiring.mail import invitation
from app.services.own_hiring.schema import TABLE_DDL
from app.services.own_hiring.slots import (
    SlotRules,
    compute_slots,
    group_by_day,
    response_deadline,
)

WARSAW = ZoneInfo("Europe/Warsaw")
TODAY = date(2026, 11, 9)


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=WARSAW).astimezone(
        timezone.utc
    )


def _rules(**over) -> SlotRules:
    base = {
        "windows": {"3": [["09:00", "10:00"]]},
        "minutes": 30,
        "buffer_minutes": 0,
        "lead_hours": 24,
        "horizon_days": 7,
    }
    return SlotRules(**{**base, **over})


def test_recruiter_role_matches_with_months():
    verdict = classify(
        [
            {
                "role": "IT Recruiter",
                "company": "Firma",
                "start": "2024-01",
                "end": "2024-12",
            }
        ],
        TODAY,
    )
    assert (verdict.bucket, verdict.reason) == ("match", "role")
    assert verdict.evidence["months"] == 12
    assert verdict.evidence["is_it"] is True


def test_parallel_recruiter_roles_are_not_counted_twice():
    verdict = classify(
        [
            {"role": "Rekruter", "start": "2024-01", "end": "2024-06"},
            {"role": "Sourcer", "start": "2024-03", "end": "2024-08"},
        ],
        TODAY,
    )
    assert verdict.evidence["months"] == 8


def test_current_role_counts_until_today():
    verdict = classify(
        [{"role": "Recruiter", "start": "2026-09", "end": "present"}], TODAY
    )
    assert verdict.evidence["months"] == 3
    assert verdict.evidence["until"] is None


def test_hr_role_with_recruiting_duty_matches():
    verdict = classify(
        [{"role": "HR Manager", "desc": "Prowadzenie rekrutacji na stanowiska"}], TODAY
    )
    assert (verdict.bucket, verdict.reason) == ("match", "hr_duty")


def test_other_role_with_mention_goes_to_review():
    verdict = classify(
        [{"role": "Kierownik sklepu", "desc": "rekrutacja pracowników do zespołu"}],
        TODAY,
    )
    assert (verdict.bucket, verdict.reason) == ("review", "mention")


def test_no_recruiting_trace_is_filtered():
    verdict = classify([{"role": "Kelner", "desc": "Obsługa gości"}], TODAY)
    assert (verdict.bucket, verdict.reason) == ("filtered", "none")


def test_unread_cv_is_never_filtered_out():
    assert classify([], TODAY).bucket == "review"
    assert classify(None, TODAY).reason == "cv_unread"
    assert classify({"role": "x"}, TODAY).reason == "cv_unread"


def test_dates_without_month_and_garbage_do_not_break():
    verdict = classify(
        [
            {"role": "Rekruterka", "start": "2020", "end": "2021"},
            {"role": "Recruiter", "start": "kiedyś", "end": "?"},
            {"role": 5, "desc": None},
        ],
        TODAY,
    )
    assert verdict.bucket == "match"
    assert verdict.evidence["months"] == 24


def test_title_normalization_removes_invisible_characters():
    assert normalize_title("IT​  Rekruter ") == normalize_title("it rekruter")


def test_offer_note_is_parsed_for_both_scrapers():
    assert parse_offer_note(
        "Źródło: Pracuj.pl — oferta: IT Rekruter / IT Rekruterka"
    ) == (
        "Pracuj.pl",
        "IT Rekruter / IT Rekruterka",
    )
    assert parse_offer_note("Źródło: RocketJobs/JJIT — oferta: IT Recruiter") == (
        "RocketJobs/JJIT",
        "IT Recruiter",
    )
    assert parse_offer_note("Import ręczny") is None
    assert parse_offer_note(None) is None


def test_deadline_counts_business_days_and_skips_holiday():
    # Pon. 9.11, 11.11 to święto: 10, 12, 13 → koniec piątku 13.11.
    assert response_deadline(_local(2026, 11, 9, 10), 3) == _local(2026, 11, 14, 0)


def test_deadline_skips_weekend():
    # Pt. 6.11: 9, 10, 12 → koniec czwartku 12.11.
    assert response_deadline(_local(2026, 11, 6, 16), 3) == _local(2026, 11, 13, 0)


def test_slots_come_from_windows_and_skip_busy():
    busy = [(_local(2026, 11, 12, 9, 30), _local(2026, 11, 12, 10))]
    slots = compute_slots(_rules(), now=_local(2026, 11, 9, 8), busy=busy)
    assert slots == [_local(2026, 11, 12, 9)]


def test_slots_respect_lead_time():
    rules = _rules(lead_hours=48)
    assert compute_slots(rules, now=_local(2026, 11, 11, 8), busy=[]) == []


def test_slots_skip_public_holiday():
    rules = _rules(windows={"2": [["09:00", "10:00"]]}, horizon_days=2)
    assert compute_slots(rules, now=_local(2026, 11, 9, 8), busy=[]) == []


def test_buffer_blocks_neighbouring_slot():
    rules = _rules(buffer_minutes=15, windows={"3": [["09:00", "11:00"]]})
    busy = [(_local(2026, 11, 12, 9, 50), _local(2026, 11, 12, 10, 20))]
    slots = compute_slots(rules, now=_local(2026, 11, 9, 8), busy=busy)
    assert _local(2026, 11, 12, 9, 45) not in slots
    assert _local(2026, 11, 12, 9) in slots


def test_days_have_polish_labels():
    days = group_by_day([_local(2026, 11, 12, 9)])
    assert days[0]["label"] == "czw. 12 listopada"


def test_invitation_escapes_title_and_assumes_no_gender():
    text = invitation(role_title="IT <b>", minutes=30, link="https://x/t/abc")
    assert "&lt;b&gt;" in text.body_html
    assert "Pani" not in text.body_html
    assert "Pana" not in text.body_html
    assert 'href="https://x/t/abc"' in text.body_html


def test_migration_and_entrypoint_share_one_ddl_source():
    root = Path(__file__).resolve().parents[1]
    entrypoint = (root / "entrypoint.sh").read_text(encoding="utf-8")
    migration = (root / "alembic/versions/0670_own_hiring.py").read_text(
        encoding="utf-8"
    )
    assert "own_hiring_schema.TABLE_DDL" in migration
    assert "_own_hiring_schema.TABLE_DDL" in entrypoint
    assert "*_OWN_HIRING_DDL" in entrypoint
    assert len(TABLE_DDL) >= 4


def test_public_module_keeps_slowapi_compatible_annotations():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app/api/public_own_hiring.py").read_text(encoding="utf-8")
    assert "\nfrom __future__ import annotations" not in source
