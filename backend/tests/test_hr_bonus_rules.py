"""Reguły premii z placementów (Compass → NEXUS, D5) — czyste funkcje, bez bazy.

Granice progów rekrutera, 10% × marża/h × 168 dla DL, termin = start + 21
polskich dni roboczych (ze świętami), przeliczenie stawek MD/miesięcznych na
godzinę i walidacja ustawień. Kwoty i stawki są fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.contract import Contract, RateUnit
from app.services.hr import bonus_rules
from app.services.hr.bonus_rules import (
    DEFAULT_RULES,
    BonusRulesError,
    dl_bonus,
    eligible_date,
    parse_rules,
    recruiter_bonus,
    recruiter_tier,
)
from app.services.hr.calendar import WorkCalendar
from app.services.hr.placement_bonuses import contract_margin

#: Sam kalendarz ustawowy (bez dni wolnych firmy) — czyste granice reguły.
PLAIN = WorkCalendar()


@pytest.mark.parametrize(
    ("margin", "tier", "amount"),
    [
        ("0", 1, "1000"),
        ("39.99", 1, "1000"),
        ("40", 1, "1000"),
        ("40.01", 2, "1500"),
        ("49.99", 2, "1500"),
        ("50", 3, "2000"),
        ("120", 3, "2000"),
    ],
)
def test_recruiter_tiers_match_compass_boundaries(margin, tier, amount) -> None:
    assert recruiter_tier(Decimal(margin)) == tier
    assert recruiter_bonus(Decimal(margin)) == Decimal(amount)


def test_negative_margin_gives_no_recruiter_bonus() -> None:
    assert recruiter_tier(Decimal("-0.01")) is None
    assert recruiter_bonus(Decimal("-5")) is None


@pytest.mark.parametrize(
    ("margin", "expected"),
    [("46", "772.80"), ("31.50", "529.20"), ("0", "0.00"), ("12.345", "207.40")],
)
def test_dl_bonus_is_ten_percent_of_168_hours_margin(margin, expected) -> None:
    assert dl_bonus(Decimal(margin)) == Decimal(expected)


def test_eligible_date_counts_21_business_days_after_start() -> None:
    # wt 1.09.2026 → 21 dni roboczych → śr 30.09.2026 (bez świąt w oknie).
    assert eligible_date(date(2026, 9, 1), DEFAULT_RULES, calendar=PLAIN) == date(
        2026, 9, 30
    )


def test_eligible_date_skips_polish_holidays() -> None:
    # 11 listopada w oknie: termin przesuwa się z 30.11 na 1.12 — i zmienia
    # miesiąc premii. Compass do 08.2026 liczył tylko weekendy.
    assert eligible_date(date(2026, 10, 30), DEFAULT_RULES, calendar=PLAIN) == (
        date(2026, 12, 1)
    )
    # Wigilia (ustawowo wolna od 2025), Boże Narodzenie i Nowy Rok.
    assert eligible_date(date(2026, 12, 1), DEFAULT_RULES, calendar=PLAIN) == (
        date(2027, 1, 4)
    )


def test_company_day_off_in_the_window_moves_the_deadline_by_a_day() -> None:
    # Decyzja 17.10.2026: dni wolne firmy liczą się jak przy urlopie.
    company = WorkCalendar(company_days_off={date(2026, 9, 10): "Dzień firmy"})
    assert eligible_date(date(2026, 9, 1), DEFAULT_RULES, calendar=company) == (
        date(2026, 10, 1)
    )
    assert (
        bonus_rules.business_days_elapsed(
            date(2026, 9, 1), date(2026, 9, 14), calendar=company
        )
        == 8
    )


def test_business_days_elapsed_drives_progress_bar() -> None:
    start = date(2026, 9, 1)
    assert bonus_rules.business_days_elapsed(start, start, calendar=PLAIN) == 0
    assert (
        bonus_rules.business_days_elapsed(start, date(2026, 9, 14), calendar=PLAIN) == 9
    )
    assert (
        bonus_rules.business_days_elapsed(start, date(2026, 9, 30), calendar=PLAIN)
        == 21
    )


def test_rules_from_settings_change_amounts_and_deadline() -> None:
    rules = parse_rules(
        {
            "recruiter_tier_bounds": [30, 45],
            "recruiter_tier_amounts": [800, 1200, 1800],
            "dl_percent": "12.5",
            "eligible_business_days": 10,
        }
    )
    assert recruiter_bonus(Decimal("30"), rules) == Decimal("800")
    assert recruiter_bonus(Decimal("44.99"), rules) == Decimal("1200")
    assert recruiter_bonus(Decimal("45"), rules) == Decimal("1800")
    assert dl_bonus(Decimal("40"), rules) == Decimal("840.00")
    assert eligible_date(date(2026, 9, 1), rules, calendar=PLAIN) == date(2026, 9, 15)


def test_default_rules_carry_no_people() -> None:
    # Compass trzymał regułę dodatkowej premii DL w kodzie razem z e-mailami
    # dwóch osób. Tu domyślnie nie ma nikogo — osoby wskazuje ustawienie.
    assert DEFAULT_RULES.extra_dl == ()
    payload = bonus_rules.rules_payload(DEFAULT_RULES)
    assert payload["extra_dl"] == []
    assert parse_rules(payload) == DEFAULT_RULES


@pytest.mark.parametrize(
    "raw",
    [
        {"recruiter_tier_bounds": [50, 40]},
        {"recruiter_tier_bounds": [40]},
        {"recruiter_tier_amounts": [1000, 0, 2000]},
        {"dl_percent": 0},
        {"dl_percent": "abc"},
        {"eligible_business_days": 0},
        {"extra_dl": [{"dl_user_id": 7, "recipient_user_id": 7}]},
        {
            "extra_dl": [
                {"dl_user_id": 7, "recipient_user_id": 8},
                {"dl_user_id": 7, "recipient_user_id": 9},
            ]
        },
        {"league_types": ["hall_of_fame"]},
        {"automation_since": "16.10.2026"},
    ],
)
def test_invalid_rules_are_refused_with_polish_message(raw) -> None:
    with pytest.raises(BonusRulesError):
        parse_rules(raw)


def test_extra_dl_rule_is_looked_up_by_user_id() -> None:
    rules = parse_rules({"extra_dl": [{"dl_user_id": 11, "recipient_user_id": 12}]})
    assert bonus_rules.extra_dl_recipient(11, rules) == 12
    assert bonus_rules.extra_dl_recipient(12, rules) is None


def _contract(unit: RateUnit, client: str, cost: str, **extra) -> Contract:
    return Contract(
        rate_unit=unit,
        rate_client=Decimal(client),
        rate_candidate=Decimal(cost),
        currency="PLN",
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
        billing_hours_per_month=168,
        **extra,
    )


@pytest.mark.asyncio
async def test_md_rates_are_converted_to_hourly_margin() -> None:
    margin = await contract_margin(
        None, _contract(RateUnit.daily, "1000", "680"), date(2026, 9, 1)
    )
    # (1000 − 680) zł/MD ÷ 8 h = 40 zł/h → próg I, DL 672,00.
    assert margin.per_hour == Decimal("40.00")
    assert margin.snapshot["rate_unit"] == "daily"
    assert recruiter_tier(margin.per_hour) == 1
    assert dl_bonus(margin.per_hour) == Decimal("672.00")


@pytest.mark.asyncio
async def test_hourly_and_monthly_rates_give_margin_per_hour() -> None:
    hourly = await contract_margin(
        None, _contract(RateUnit.hourly, "150", "104"), date(2026, 9, 1)
    )
    assert hourly.per_hour == Decimal("46.00")
    monthly = await contract_margin(
        None, _contract(RateUnit.monthly, "25200", "16800"), date(2026, 9, 1)
    )
    assert monthly.per_hour == Decimal("50.00")


@pytest.mark.asyncio
async def test_missing_rate_gives_no_margin_with_reason() -> None:
    contract = _contract(RateUnit.hourly, "150", "100")
    contract.rate_candidate = None
    margin = await contract_margin(None, contract, date(2026, 9, 1))
    assert margin.per_hour is None
    assert margin.reason == "missing_rates"
