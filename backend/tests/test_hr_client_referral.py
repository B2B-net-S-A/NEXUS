"""Kandydat wskazany przez klienta: bez premii z placementu (decyzja Artura 06.11.2026).

* „Tak” na kontrakcie: automat nie proponuje premii ani rekruterowi, ani DL-owi,
* istniejące propozycje (też poprawione ręcznie) anulowane z powodem
  ``client_referral``; „Nie” je przywraca,
* zapis w PATCH kontraktu uzgadnia premie od razu,
* kontrakt nie liczy się do premii 200% i do prognozy „w drodze”.

Dane fikcyjne; stawki zmyślone.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.hr_payroll import HrBonus
from app.services.hr import double_bonus, placement_bonuses
from app.services.hr.bonus_rules import SETTING_KEY as RULES_KEY
from app.services.hr.my_settlement import bonus_forecast
from app.services.hr.payroll_bonuses import AUTO_CANCEL_REASONS
from tests.test_hr_bonus_automation import (  # noqa: F401  (fikstura)
    _bonuses,
    _placement,
    _reconcile,
    _set_setting,
    _update_contract,
    payroll_on,
)

pytestmark = pytest.mark.usefixtures("payroll_on")


def _previous_month(today: date) -> tuple[int, int]:
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def test_client_referral_is_a_reason_the_automat_can_undo() -> None:
    assert "client_referral" in AUTO_CANCEL_REASONS
    assert placement_bonuses.CLIENT_REFERRAL == "client_referral"


@pytest.mark.asyncio
async def test_client_referral_contract_gets_no_proposals() -> None:
    world = await _placement(started_days_ago=10)
    await _update_contract(world["contract"], is_client_referral=True)

    counts = await _reconcile(world["contract"])

    assert counts["created"] == 0
    assert counts["skipped"] == "client_referral"
    assert await _bonuses(world["contract"]) == {}


@pytest.mark.asyncio
async def test_unknown_flag_counts_as_no() -> None:
    world = await _placement(started_days_ago=10)
    await _update_contract(world["contract"], is_client_referral=None)
    assert (await _reconcile(world["contract"]))["created"] == 2


@pytest.mark.asyncio
async def test_yes_cancels_proposals_and_no_restores_them() -> None:
    world = await _placement(started_days_ago=10)
    await _reconcile(world["contract"])
    # Płace poprawiły kwotę rekrutera ręcznie — „Tak” i tak ją anuluje.
    async with AsyncSessionLocal() as db:
        bonus = await db.scalar(
            select(HrBonus).where(
                HrBonus.source_key
                == placement_bonuses.source_key(world["contract"], "recruiter")
            )
        )
        bonus.rule_snapshot = {**(bonus.rule_snapshot or {}), "edited_amount": True}
        await db.commit()

    await _update_contract(world["contract"], is_client_referral=True)
    counts = await _reconcile(world["contract"])

    assert counts["cancelled"] == 2
    found = await _bonuses(world["contract"])
    assert {b.status for b in found.values()} == {"cancelled"}
    assert {b.cancel_reason for b in found.values()} == {"client_referral"}
    assert all(b.cancelled_by is None for b in found.values())

    await _update_contract(world["contract"], is_client_referral=False)
    restored = await _reconcile(world["contract"])

    assert restored["restored"] == 2
    found = await _bonuses(world["contract"])
    assert {b.status for b in found.values()} == {"proposed"}
    assert {b.cancel_reason for b in found.values()} == {None}
    # Ręczna poprawka kwoty przetrwała anulowanie i przywrócenie.
    assert found["recruiter"].rule_snapshot.get("edited_amount") is True


@pytest.mark.asyncio
async def test_assigned_bonus_is_left_alone() -> None:
    world = await _placement(started_days_ago=10)
    await _reconcile(world["contract"])
    async with AsyncSessionLocal() as db:
        bonus = await db.scalar(
            select(HrBonus).where(
                HrBonus.source_key
                == placement_bonuses.source_key(world["contract"], "dl")
            )
        )
        bonus.status = "assigned"
        bonus.assigned_at = local_now()
        await db.commit()

    await _update_contract(world["contract"], is_client_referral=True)
    await _reconcile(world["contract"])

    found = await _bonuses(world["contract"])
    assert found["dl"].status == "assigned"
    assert found["recruiter"].cancel_reason == "client_referral"


@pytest.mark.asyncio
async def test_contracts_to_reconcile_picks_up_cancelled_referral() -> None:
    """Przebieg nocny wraca do anulowanych, więc „Nie” przywróci je bez haka."""

    world = await _placement(started_days_ago=10)
    await _reconcile(world["contract"])
    await _update_contract(world["contract"], is_client_referral=True)
    await _reconcile(world["contract"])
    async with AsyncSessionLocal() as db:
        from app.services.hr.bonus_rules import load_rules

        rules = await load_rules(db)
        ids = await placement_bonuses.contracts_to_reconcile(
            db, today=business_today(), rules=rules
        )
    assert world["contract"] in ids


@pytest.mark.asyncio
async def test_client_referral_is_outside_double_bonus_month() -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    world = await _placement(started_days_ago=10, client_rate="160", cost_rate="105")
    await _update_contract(
        world["contract"],
        created_at=datetime(*signed, 3, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
        is_client_referral=True,
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": [key]}})

    async with AsyncSessionLocal() as db:
        contracts = await double_bonus.month_contracts(db, *signed)
    assert world["contract"] not in {c.id for c in contracts}

    await _update_contract(world["contract"], is_client_referral=False)
    async with AsyncSessionLocal() as db:
        contracts = await double_bonus.month_contracts(db, *signed)
    assert world["contract"] in {c.id for c in contracts}
    # Bez śladu dla innych testów miesiąca programu (liczą każdy kontrakt miesiąca).
    await _update_contract(
        world["contract"], created_at=datetime.now(ZoneInfo("Europe/Warsaw"))
    )


@pytest.mark.asyncio
async def test_forecast_skips_client_referral() -> None:
    today = business_today()
    # Start za 5 dni: premia jeszcze „w drodze”, automat jej nie założył.
    world = await _placement(started_days_ago=-5)

    async with AsyncSessionLocal() as db:
        before = await bonus_forecast(db, user_id=world["recruiter"], today=today)
    assert world["contract"] in {item["contract_id"] for item in before}

    await _update_contract(world["contract"], is_client_referral=True)
    async with AsyncSessionLocal() as db:
        after = await bonus_forecast(db, user_id=world["recruiter"], today=today)
    assert world["contract"] not in {item["contract_id"] for item in after}
