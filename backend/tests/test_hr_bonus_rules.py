"""Reguły premii z placementów (Compass → NEXUS, D5) — czyste funkcje, bez bazy.

Granice progów rekrutera, 10% × marża/h × 168 dla DL, termin = start + 21
polskich dni roboczych (ze świętami), przeliczenie stawek MD/miesięcznych na
godzinę, walidacja ustawień i odbiorcy premii (rekruter = weryfikujący,
DL rekrutacji, prowadzący z rolą DL albo DL klienta). Kwoty i stawki są fikcyjne.
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
from app.models.user import UserRole
from app.services.hr.placement_bonuses import (
    PlacementContext,
    contract_margin,
    holds_dl_role,
    holds_recruiter_role,
)

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


# ── Odbiorcy premii (decyzja 18.10.2026: jak w Compassie) ─────────────────────


def _context(**overrides) -> PlacementContext:
    values = {
        "jobs": {},
        "client_leads": {},
        "candidates": {},
        "clients": {},
        "verifiers": {},
        "job_leads": {},
    }
    values.update(overrides)
    return PlacementContext(**values)


def _placement_contract(
    candidate_id: int = 1, job_id: int = 10, client_id: int = 100
) -> Contract:
    return Contract(candidate_id=candidate_id, job_id=job_id, client_id=client_id)


def test_recruiter_is_the_first_verifier_not_the_lead_of_the_recruitment() -> None:
    # Prowadzący rekrutację (jobs.recruiter_id) nie ma znaczenia — liczy się
    # osoba, która zweryfikowała kandydata.
    context = _context(jobs={10: 7}, verifiers={(1, 10): 42})
    assert context.people(_placement_contract()) == (7, 42, "job")


def test_dl_who_verified_himself_gets_no_recruiter_bonus() -> None:
    # Decyzja Artura 22.10.2026: DL, który sam zweryfikował osobę w swojej
    # rekrutacji, dostaje tylko premię DL-a — jedna płatność za zatrudnienie.
    context = _context(jobs={10: 7}, verifiers={(1, 10): 7})
    assert context.people(_placement_contract()) == (7, None, "job")
    client_head = _context(
        jobs={10: None}, client_leads={100: [(6, True)]}, verifiers={(1, 10): 6}
    )
    assert client_head.people(_placement_contract()) == (6, None, "client_head")


def test_dl_with_recruiter_role_who_verified_gets_both_bonuses() -> None:
    # Decyzja Artura 25.10.2026: DL, który ma też rolę rekrutera (np. Marlena
    # w Orlenie), dostaje za osobę zweryfikowaną przez siebie obie premie.
    context = _context(
        jobs={10: 7}, verifiers={(1, 10): 7}, recruiter_roles=frozenset({7})
    )
    assert context.people(_placement_contract()) == (7, 7, "job")


def test_recruiter_role_of_someone_else_does_not_restore_dl_bonus() -> None:
    # Rola rekrutera liczy się u weryfikującego DL-a, nie u kogokolwiek.
    context = _context(
        jobs={10: 7}, verifiers={(1, 10): 7}, recruiter_roles=frozenset({8})
    )
    assert context.people(_placement_contract()) == (7, None, "job")


@pytest.mark.parametrize(
    ("role", "roles", "expected"),
    [
        ("recruiter", ["recruiter"], True),
        ("delivery_lead", ["delivery_lead", "recruiter"], True),
        (UserRole.delivery_lead, ["delivery_lead"], False),
        ("sourcer", None, True),  # wycofana rola = rekruter
        ("delivery_lead", ["tac"], True),
        ("head_of_recruitment", ["head_of_recruitment"], False),
        ("delivery_lead", "recruiter", False),  # nie-lista nie jest listą ról
    ],
)
def test_recruiter_role_is_primary_or_secondary(role, roles, expected) -> None:
    assert holds_recruiter_role(role, roles) is expected


def test_dl_verifying_in_someone_elses_recruitment_keeps_recruiter_bonus() -> None:
    context = _context(jobs={10: 7}, verifiers={(1, 10): 8})
    assert context.people(_placement_contract()) == (7, 8, "job")


def test_no_verifier_means_no_recruiter_bonus() -> None:
    context = _context(jobs={10: 7})
    assert context.people(_placement_contract()) == (7, None, "job")


def test_verifier_of_another_recruitment_does_not_count() -> None:
    context = _context(jobs={10: 7, 11: 8}, verifiers={(1, 11): 42})
    assert context.people(_placement_contract())[1] is None


def test_dl_lead_of_recruitment_comes_before_client_dl() -> None:
    context = _context(
        jobs={10: None}, job_leads={10: 3}, client_leads={100: [(6, True)]}
    )
    assert context.people(_placement_contract()) == (3, None, "job_lead")


def test_dl_of_recruitment_wins_over_lead() -> None:
    context = _context(jobs={10: 7}, job_leads={10: 3})
    assert context.people(_placement_contract())[0] == 7


@pytest.mark.parametrize(
    ("role", "roles", "expected"),
    [
        ("delivery_lead", ["delivery_lead"], True),
        (UserRole.recruiter, ["recruiter", "delivery_lead"], True),
        ("recruiter", ["recruiter"], False),
        ("head_of_recruitment", None, False),
        (None, "delivery_lead", False),  # nie-lista nie jest listą ról
    ],
)
def test_dl_role_is_primary_or_secondary(role, roles, expected) -> None:
    assert holds_dl_role(role, roles) is expected


def test_dl_falls_back_to_client_head_then_single_assignment() -> None:
    head = _context(
        jobs={10: None}, client_leads={100: [(5, False), (6, True)]}, verifiers={}
    )
    assert head.people(_placement_contract()) == (6, None, "client_head")
    single = _context(jobs={10: None}, client_leads={100: [(5, False)]})
    assert single.people(_placement_contract()) == (5, None, "client_assignment")
    unclear = _context(jobs={10: None}, client_leads={100: [(5, False), (9, False)]})
    assert unclear.people(_placement_contract()) == (None, None, "none")


def test_contract_without_recruitment_has_no_recruiter() -> None:
    context = _context(client_leads={100: [(6, True)]}, verifiers={(1, 10): 42})
    assert context.people(_placement_contract(job_id=None)) == (6, None, "client_head")


# ── Data startu automatu po przełączeniu z Compassa (audyt 19.10.2026) ───────


class _FakeSettingsDb:
    """``db.scalar`` zwraca surowy wpis ``app_settings`` (bez Postgresa)."""

    def __init__(self, raw: object) -> None:
        self.raw = raw

    async def scalar(self, _statement: object) -> object:
        return self.raw


@pytest.mark.asyncio
async def test_broken_rules_keep_automation_since_instead_of_backfilling() -> None:
    # Zepsuty wpis nie może cofnąć automatu o 120 dni wstecz — to by zdublowało
    # premie zaimportowane z Compassa sprzed przełączenia.
    raw = {"automation_since": "2026-10-01", "dl_percent": "abc"}
    rules = await bonus_rules.load_rules(_FakeSettingsDb(raw))
    assert rules.automation_since == date(2026, 10, 1)
    assert rules.dl_percent == DEFAULT_RULES.dl_percent


@pytest.mark.asyncio
async def test_broken_rules_with_broken_date_stop_new_proposals() -> None:
    raw = {"automation_since": "1.10.2026"}
    rules = await bonus_rules.load_rules(_FakeSettingsDb(raw))
    floor = bonus_rules.automation_floor_for(rules, date(2026, 10, 19))
    assert floor > date(2100, 1, 1)


@pytest.mark.asyncio
async def test_missing_rules_still_use_the_lookback_window() -> None:
    rules = await bonus_rules.load_rules(_FakeSettingsDb(None))
    assert rules.automation_since is None
    assert bonus_rules.automation_floor_for(rules, date(2026, 10, 19)) == date(
        2026, 6, 21
    )


@pytest.mark.parametrize(
    ("current", "new", "imported", "refused"),
    [
        (date(2026, 10, 1), None, True, True),
        (date(2026, 10, 1), date(2026, 9, 1), True, True),
        (date(2026, 10, 1), date(2026, 10, 1), True, False),
        (date(2026, 10, 1), date(2026, 11, 1), True, False),
        (None, None, True, True),
        (date(2026, 10, 1), None, False, False),
        (date(2026, 10, 1), date(2026, 9, 1), False, False),
    ],
)
def test_automation_since_cannot_reach_back_over_compass_imports(
    current, new, imported, refused
) -> None:
    error = bonus_rules.automation_since_change_error(
        current, new, has_compass_imports=imported
    )
    assert (error is not None) is refused
