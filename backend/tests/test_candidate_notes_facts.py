"""Fakty z notatek na profilu kandydata: przeliczenia, tryb pracy, zapis na kliknięcie.

Kontrakty:
- stawka za dzień ÷ 8, miesięczna ÷ 168, inna waluta — bez przeliczenia;
- tryb pracy wynika z dni w biurze (N dni akceptuje też mniej) — ta sama reguła
  co bramka dni w biurze w wyszukiwaniu;
- ekstrakcja wypełnia tryb pracy tylko w PUSTYM profilu, a kliknięcie „Zapisz
  w profilu” zapisuje wartość wyliczoną przez serwer.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.services.candidate_notes_facts as facts_mod
from app.services.candidate_notes_facts import (
    NotesFactUnavailable,
    apply_notes_fact,
    build_notes_facts,
    fill_work_mode_from_notes,
    hourly_from_notes_rate,
    modes_for_office_days,
    work_mode_from_insights,
)


@pytest.fixture(autouse=True)
def _no_orm_instrumentation(monkeypatch):
    monkeypatch.setattr(facts_mod, "flag_modified", lambda *a, **k: None)


def _cand(insights=None, **kw):
    data = dict(
        id=1,
        preferences=None,
        max_onsite_days_per_week=None,
        expected_rate_hourly=None,
        expected_rate_currency=None,
        profile_rate_version=0,
        profile_rate_updated_at=None,
        notice_period=None,
        notice_period_unit=None,
        availability_date=None,
        cv_extracted_data={"_notes_insights": insights}
        if insights is not None
        else None,
    )
    data.update(kw)
    return SimpleNamespace(**data)


# ── Stawka ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("period", "value", "expected"),
    [
        ("h", 150, Decimal("150.00")),
        ("md", 1200, Decimal("150.00")),
        ("md", 1001, Decimal("125.13")),
        ("month", 25200, Decimal("150.00")),
        ("month", 18000, Decimal("107.14")),
    ],
)
def test_pln_rates_convert_to_hourly(period, value, expected):
    rate = hourly_from_notes_rate(
        {"value": value, "currency": "pln", "period": period}, contract_form="b2b"
    )
    assert rate["hourly_pln"] == expected
    assert rate["currency"] == "PLN"
    assert rate["note"] is None


@pytest.mark.parametrize("contract_form", [None, "uop", "any"])
def test_monthly_rate_without_b2b_is_not_converted(contract_form):
    """CAND-04: 18 000 PLN/mies. na UoP brutto ≠ 107 PLN/h B2B netto."""
    rate = hourly_from_notes_rate(
        {"value": 18000, "currency": "PLN", "period": "month"},
        contract_form=contract_form,
    )
    assert rate is not None
    assert rate["hourly_pln"] is None
    assert rate["note"] and "B2B" in rate["note"]


@pytest.mark.parametrize(("period", "value"), [("h", 150), ("md", 1200)])
def test_hourly_and_daily_rates_do_not_need_a_contract_form(period, value):
    rate = hourly_from_notes_rate({"value": value, "currency": "PLN", "period": period})
    assert rate["hourly_pln"] == Decimal("150.00")


@pytest.mark.parametrize(
    "rate",
    [
        {"value": 40, "currency": "EUR", "period": "h"},
        {"value": 800, "currency": None, "period": "md"},
        {"value": 150, "currency": "PLN", "period": None},
        {"value": 5000, "currency": "PLN", "period": "h"},
    ],
)
def test_rates_without_safe_conversion_keep_text_only(rate):
    out = hourly_from_notes_rate(rate)
    assert out is not None and out["hourly_pln"] is None


@pytest.mark.parametrize("value", [None, True, "150-200", 0, -10])
def test_unusable_rate_values_are_ignored(value):
    assert (
        hourly_from_notes_rate({"value": value, "currency": "PLN", "period": "h"})
        is None
    )


# ── Tryb pracy ──────────────────────────────────────────────────────────────


def test_modes_follow_office_days():
    assert modes_for_office_days(0) == ["remote"]
    assert modes_for_office_days(2) == ["remote", "hybrid"]
    assert modes_for_office_days(5) == ["remote", "hybrid", "onsite"]


@pytest.mark.parametrize(
    ("prefs", "expected"),
    [
        ({"remote_only": True}, {"modes": ["remote"], "max_onsite_days": 0}),
        (
            {"work_modes": ["hybrid"], "max_onsite_days_per_week": 3},
            {"modes": ["remote", "hybrid"], "max_onsite_days": 3},
        ),
        (
            {"work_modes": ["hybrid"]},
            {"modes": ["remote", "hybrid"], "max_onsite_days": None},
        ),
        (
            {"work_modes": ["onsite"]},
            {"modes": ["remote", "hybrid", "onsite"], "max_onsite_days": 5},
        ),
        ({"work_modes": ["remote"]}, {"modes": ["remote"], "max_onsite_days": None}),
        (
            {"max_onsite_days_per_week": 1},
            {"modes": ["remote", "hybrid"], "max_onsite_days": 1},
        ),
        ({"remote_only": False}, None),
        ({"work_modes": ["office"]}, None),
    ],
)
def test_work_mode_from_insights(prefs, expected):
    assert work_mode_from_insights({"preferences": prefs}) == expected


def test_work_mode_fill_is_per_field():
    cand = _cand(preferences={"remote_modes": ["remote"]})
    stats = fill_work_mode_from_notes(
        cand, {"preferences": {"work_modes": ["hybrid"], "max_onsite_days_per_week": 2}}
    )
    assert cand.preferences == {"remote_modes": ["remote"]}
    assert cand.max_onsite_days_per_week == 2
    assert stats == {"remote_modes_filled": 0, "onsite_days_filled": 1}


# ── Widok ───────────────────────────────────────────────────────────────────


def test_view_without_insights_is_empty():
    view = build_notes_facts(_cand())
    assert view["has_facts"] is False
    assert view["rate"] is None and view["work_mode"] is None


def test_view_compares_notes_with_profile():
    cand = _cand(
        {
            "_extracted_at": "2026-09-20T04:00:00+00:00",
            "expected_rate": {
                "value": 1200,
                "currency": "PLN",
                "period": "md",
                "raw": "1200 zł/MD",
            },
            "preferences": {
                "work_modes": ["hybrid"],
                "max_onsite_days_per_week": 2,
                "locations": ["Warszawa"],
            },
            "contract_form_preference": "b2b",
            "availability": {
                "raw": "okres wypowiedzenia 1 miesiąc",
                "notice_period": "1 miesiąc",
            },
            "relocation": {"willing": True, "targets": ["Kraków"]},
            "current_engagement": {"employer": "Bank X", "ends_at": "2026-12"},
            "client_vetoes": [{"client": "Firma Y", "reason": "zła atmosfera"}],
            "languages_observed": [{"name": "angielski", "level": "C1"}],
        },
        expected_rate_hourly=Decimal("150.00"),
        expected_rate_currency="PLN",
        preferences={"contract_types": ["b2b"]},
    )
    view = build_notes_facts(cand)
    assert view["has_facts"] is True
    assert view["rate"]["hourly_pln"] == Decimal("150.00")
    assert view["rate"]["can_apply"] is False, "profil już ma tę stawkę"
    assert view["work_mode"]["modes"] == ["remote", "hybrid"]
    assert view["work_mode"]["max_onsite_days"] == 2
    assert view["work_mode"]["can_apply"] is True
    assert view["contract_form"]["can_apply"] is False
    assert view["availability"]["notice_period"] == 1
    assert view["availability"]["notice_period_unit"] == "months"
    assert view["availability"]["can_apply"] is True
    assert view["office_cities"]["cities"] == ["Warszawa"]
    assert view["relocation"] == {"willing": True, "targets": ["Kraków"]}
    assert view["current_engagement"]["employer"] == "Bank X"
    assert view["client_vetoes"] == [{"client": "Firma Y", "reason": "zła atmosfera"}]
    assert view["languages"] == [{"name": "angielski", "level": "C1"}]


def test_view_handles_malformed_ai_shapes():
    cand = _cand(
        {
            "preferences": "zdalnie",
            "expected_rate": "150",
            "relocation": [],
            "languages_observed": ["niemiecki", 3],
            "client_vetoes": ["x"],
        }
    )
    view = build_notes_facts(cand)
    assert view["work_mode"] is None and view["rate"] is None
    assert view["languages"] == [{"name": "niemiecki", "level": None}]
    assert view["client_vetoes"] == []


# ── Zapis na kliknięcie ─────────────────────────────────────────────────────


def test_apply_rate_writes_converted_hourly_and_locks_it():
    cand = _cand(
        {
            "expected_rate": {"value": 25200, "currency": "PLN", "period": "month"},
            "contract_form_preference": "b2b",
            "_rate_from_notes": True,
        }
    )
    details = apply_notes_fact(cand, "rate")
    assert cand.expected_rate_hourly == Decimal("150.00")
    assert cand.expected_rate_currency == "PLN"
    assert cand.profile_rate_version == 1
    assert details["rate_audit"]["source"] == "notes_confirmed"
    assert cand.cv_extracted_data["_manual_override_rate"] is True
    assert "_rate_from_notes" not in cand.cv_extracted_data["_notes_insights"]


def test_apply_rate_refuses_monthly_amount_without_b2b():
    """CAND-04: UoP brutto miesięcznie nie trafia do profilu jako B2B/h."""
    cand = _cand(
        {
            "expected_rate": {"value": 18000, "currency": "PLN", "period": "month"},
            "contract_form_preference": "uop",
        }
    )
    with pytest.raises(NotesFactUnavailable):
        apply_notes_fact(cand, "rate")
    assert cand.expected_rate_hourly is None
    view = build_notes_facts(cand)
    assert view["rate"]["hourly_pln"] is None
    assert view["rate"]["can_apply"] is False
    assert "B2B" in view["rate"]["note"]


def test_apply_rate_refuses_foreign_currency():
    cand = _cand({"expected_rate": {"value": 40, "currency": "EUR", "period": "h"}})
    with pytest.raises(NotesFactUnavailable):
        apply_notes_fact(cand, "rate")
    assert cand.expected_rate_hourly is None


def test_apply_work_mode_overwrites_profile_and_keeps_other_preferences():
    cand = _cand(
        {"preferences": {"work_modes": ["hybrid"], "max_onsite_days_per_week": 3}},
        preferences={"remote_modes": ["remote"], "industries": ["bank"]},
        max_onsite_days_per_week=0,
    )
    apply_notes_fact(cand, "work_mode")
    assert cand.preferences == {
        "remote_modes": ["remote", "hybrid"],
        "industries": ["bank"],
    }
    assert cand.max_onsite_days_per_week == 3


def test_apply_work_mode_without_days_keeps_profile_days():
    cand = _cand(
        {"preferences": {"work_modes": ["hybrid"]}}, max_onsite_days_per_week=2
    )
    apply_notes_fact(cand, "work_mode")
    assert cand.max_onsite_days_per_week == 2


def test_apply_contract_form_any_means_both():
    cand = _cand({"contract_form_preference": "any"})
    apply_notes_fact(cand, "contract_form")
    assert cand.preferences == {"contract_types": ["b2b", "uop"]}


def test_apply_availability_prefers_date_over_notice():
    cand = _cand(
        {"availability": {"available_from": "2026-11-01", "notice_period": "1 miesiąc"}}
    )
    apply_notes_fact(cand, "availability")
    assert cand.availability_date == date(2026, 11, 1)
    assert cand.notice_period is None


def test_apply_office_cities_and_unparseable_availability():
    cand = _cand(
        {
            "preferences": {"locations": ["Warszawa", "warszawa", "Łódź"]},
            "availability": {"raw": "po projekcie"},
        }
    )
    apply_notes_fact(cand, "office_cities")
    assert cand.preferences == {"office_cities": ["Warszawa", "Łódź"]}
    with pytest.raises(NotesFactUnavailable):
        apply_notes_fact(cand, "availability")


# ── API (baza) ──────────────────────────────────────────────────────────────


async def _seed_candidate(**kw) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Notes",
            lastname=f"Facts-{uuid.uuid4().hex[:6]}",
            email=f"notes-facts-{uuid.uuid4().hex[:8]}@example.com",
            **kw,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


@pytest.fixture
def _real_flag_modified(monkeypatch):
    from sqlalchemy.orm.attributes import flag_modified

    monkeypatch.setattr(facts_mod, "flag_modified", flag_modified)


@pytest.mark.asyncio
async def test_api_read_apply_and_work_mode_round_trip(app_client, _real_flag_modified):
    from app.models.user import UserRole
    from tests._jarvis_helpers import make_user

    _, admin_headers = await make_user(UserRole.recruiter)
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from sqlalchemy import select

    cid = await _seed_candidate(
        cv_extracted_data={
            "_notes_insights": {
                "_extracted_at": "2026-09-20T04:00:00+00:00",
                "expected_rate": {"value": 1200, "currency": "PLN", "period": "md"},
                "preferences": {
                    "work_modes": ["hybrid"],
                    "max_onsite_days_per_week": 2,
                },
                "contract_form_preference": "b2b",
            }
        },
        preferences={"industries": ["bank"]},
    )

    view = await app_client.get(
        f"/api/candidates/{cid}/notes-facts", headers=admin_headers
    )
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["rate"]["hourly_pln"] == "150.00"
    assert body["rate"]["can_apply"] is True
    assert body["work_mode"]["modes"] == ["remote", "hybrid"]

    missing_version = await app_client.post(
        f"/api/candidates/{cid}/notes-facts/apply",
        headers=admin_headers,
        json={"field": "rate"},
    )
    assert missing_version.status_code == 422

    stale = await app_client.post(
        f"/api/candidates/{cid}/notes-facts/apply",
        headers=admin_headers,
        json={"field": "rate", "expected_profile_rate_version": 7},
    )
    assert stale.status_code == 412

    applied = await app_client.post(
        f"/api/candidates/{cid}/notes-facts/apply",
        headers=admin_headers,
        json={
            "field": "rate",
            "expected_profile_rate_version": body["rate"]["profile_rate_version"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["rate"]["can_apply"] is False

    mode = await app_client.post(
        f"/api/candidates/{cid}/notes-facts/apply",
        headers=admin_headers,
        json={"field": "work_mode"},
    )
    assert mode.status_code == 200, mode.text
    assert mode.json()["work_mode"]["can_apply"] is False

    unavailable = await app_client.post(
        f"/api/candidates/{cid}/notes-facts/apply",
        headers=admin_headers,
        json={"field": "availability"},
    )
    assert unavailable.status_code == 409

    patched = await app_client.patch(
        f"/api/candidates/{cid}/work-mode",
        headers=admin_headers,
        json={"remote_modes": ["onsite", "remote"], "max_onsite_days_per_week": 5},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["remote_modes"] == ["remote", "onsite"]

    incoherent = await app_client.patch(
        f"/api/candidates/{cid}/work-mode",
        headers=admin_headers,
        json={"remote_modes": ["remote"], "max_onsite_days_per_week": 3},
    )
    assert incoherent.status_code == 422

    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, cid)
        assert cand.expected_rate_hourly == Decimal("150.00")
        assert cand.preferences == {
            "industries": ["bank"],
            "remote_modes": ["remote", "onsite"],
        }
        assert cand.max_onsite_days_per_week == 5
        actions = set(
            (
                await db.scalars(
                    select(Activity.action).where(
                        Activity.entity_type == "candidate", Activity.entity_id == cid
                    )
                )
            ).all()
        )
    assert {
        "profile_rate_changed",
        "candidate_notes_fact_applied",
        "candidate_work_mode_changed",
    } <= actions


@pytest.mark.asyncio
async def test_api_viewer_cannot_read_or_write(app_client):
    from app.models.user import UserRole
    from tests._jarvis_helpers import make_user

    _, viewer_headers = await make_user(UserRole.user)
    cid = await _seed_candidate()
    read = await app_client.get(
        f"/api/candidates/{cid}/notes-facts", headers=viewer_headers
    )
    assert read.status_code == 403
    write = await app_client.patch(
        f"/api/candidates/{cid}/work-mode",
        headers=viewer_headers,
        json={"remote_modes": ["remote"]},
    )
    assert write.status_code == 403
