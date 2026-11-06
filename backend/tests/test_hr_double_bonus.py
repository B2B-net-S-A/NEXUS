"""Automat premii: stała premia TCM, gwarancja DL i premia 200% (decyzje 05.11.2026).

* TCM jako weryfikujący dostaje stałą kwotę zamiast progu marży,
* zastępstwo osoby, którą zatrudnił ten sam DL i która odeszła przed rokiem:
  bez premii DL, rekruter dostaje swoją,
* zapisana decyzja 200% podwaja premie kontraktu podpisanego w miesiącu
  programu i przenosi je na miesiąc podpisu; koniec przed terminem jej nie zabiera.

Dane fikcyjne; stawki zmyślone.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.user import User, UserRole
from app.services.hr import double_bonus
from app.services.hr.bonus_rules import SETTING_KEY as RULES_KEY
from app.services.hr.bonus_rules import load_rules
from tests.test_hr_bonus_automation import (  # noqa: F401  (fikstura)
    _bonuses,
    _placement,
    _reconcile,
    _set_setting,
    _update_contract,
    payroll_on,
)


# Fikstura z ``test_hr_bonus_automation``: moduł Płac włączony, czyste premie.
pytestmark = pytest.mark.usefixtures("payroll_on")


def _previous_month(today: date) -> tuple[int, int]:
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


@pytest_asyncio.fixture
async def results_clean():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == double_bonus.RESULTS_KEY)
        )
    await _set_setting(double_bonus.RESULTS_KEY, None)
    yield
    await _set_setting(double_bonus.RESULTS_KEY, previous)


def _decision(key: str, world: dict, *, recruiter: bool, dl: bool) -> dict:
    """Zapisana decyzja miesiąca w kształcie ``store_result``."""

    contract = str(world["contract"])
    return {
        key: {
            "recruiters": [world["recruiter"]] if recruiter else [],
            "dls": [world["dl"]] if dl else [],
            "recruiter_contracts": {contract: world["recruiter"]} if recruiter else {},
            "dl_contracts": {contract: world["dl"]} if dl else {},
        }
    }


async def _set_role(user_id: int, role: str) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.role = UserRole(role)
        user.roles = [role]
        await db.commit()


async def _set_job_dl(contract_id: int, dl_id: int) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        job = await db.get(Job, contract.job_id)
        job.delivery_lead_id = dl_id
        await db.commit()


@pytest.mark.asyncio
async def test_tcm_verifier_gets_fixed_amount_instead_of_tier() -> None:
    await _set_setting(
        RULES_KEY,
        {
            "fixed_role_amounts": [
                {"role": "talent_community_manager", "amount": "1000"}
            ]
        },
    )
    world = await _placement(started_days_ago=40, client_rate="160", cost_rate="105")
    await _set_role(world["recruiter"], "talent_community_manager")
    await _reconcile(world["contract"])

    found = await _bonuses(world["contract"])
    assert found["recruiter"].amount == Decimal("1000.00")  # próg III dałby 2000
    assert found["recruiter"].rule_snapshot["fixed_amount"] == "1000.00"
    assert found["dl"].amount == Decimal("924.00")


async def _replacement(*, replaced_days: int, same_dl: bool) -> tuple[dict, dict]:
    today = business_today()
    replaced = await _placement(
        started_days_ago=replaced_days + 60,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=60),
    )
    world = await _placement(started_days_ago=40)
    await _update_contract(
        world["contract"],
        is_replacement=True,
        replaced_contract_id=replaced["contract"],
    )
    if same_dl:
        await _set_job_dl(world["contract"], replaced["dl"])
        world = {**world, "dl": replaced["dl"]}
    return replaced, world


@pytest.mark.asyncio
async def test_guarantee_drops_dl_bonus_of_the_same_dl_only() -> None:
    _replaced, world = await _replacement(replaced_days=200, same_dl=True)
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    assert "dl" not in found
    assert found["recruiter"].recipient_user_id == world["recruiter"]
    assert found["recruiter"].status == "proposed"

    _replaced, other = await _replacement(replaced_days=200, same_dl=False)
    await _reconcile(other["contract"])
    assert (await _bonuses(other["contract"]))["dl"].status == "proposed"


@pytest.mark.asyncio
async def test_replaced_contract_over_a_year_keeps_dl_bonus() -> None:
    _replaced, world = await _replacement(replaced_days=400, same_dl=True)
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["dl"].status == "proposed"


@pytest.mark.asyncio
async def test_stored_decision_doubles_bonus_in_signing_month(results_clean) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    world = await _placement(started_days_ago=10)
    # Kontrakt bez umowy z Generatora: miesiąc podpisu = dzień założenia.
    await _update_contract(
        world["contract"],
        created_at=datetime(*signed, 3, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": [key]}})
    await _set_setting(
        double_bonus.RESULTS_KEY,
        _decision(key, world, recruiter=True, dl=True),
    )
    await _reconcile(world["contract"])

    found = await _bonuses(world["contract"])
    assert found["dl"].amount == Decimal("1545.60")  # 2 × 10% × 46 × 168
    assert found["recruiter"].amount == Decimal("3000.00")  # 2 × próg II
    for bonus in found.values():
        assert (bonus.period_year, bonus.period_month) == signed
        assert bonus.rule_snapshot["double_bonus"] == {"month": key, "multiplier": "2"}

    # Konsultant odchodzi przed terminem: premia 200% zostaje (ryzyko firmy).
    await _update_contract(
        world["contract"], end_date=business_today() - timedelta(days=2)
    )
    await _reconcile(world["contract"])
    assert {b.status for b in (await _bonuses(world["contract"])).values()} == {
        "proposed"
    }


@pytest.mark.asyncio
async def test_only_qualified_role_is_doubled(results_clean) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    world = await _placement(started_days_ago=40)
    await _update_contract(
        world["contract"],
        created_at=datetime(*signed, 3, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": [key]}})
    await _set_setting(
        double_bonus.RESULTS_KEY, _decision(key, world, recruiter=True, dl=False)
    )
    await _reconcile(world["contract"])

    found = await _bonuses(world["contract"])
    assert found["recruiter"].amount == Decimal("3000.00")
    assert found["dl"].amount == Decimal("772.80")
    assert "double_bonus" not in found["dl"].rule_snapshot


@pytest.mark.asyncio
async def test_month_outside_program_is_not_doubled(results_clean) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    world = await _placement(started_days_ago=40)
    await _update_contract(
        world["contract"],
        created_at=datetime(*signed, 3, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": ["2020-01"]}})
    await _set_setting(
        double_bonus.RESULTS_KEY, _decision(key, world, recruiter=True, dl=True)
    )
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["recruiter"].amount == Decimal("1500.00")


@pytest.mark.asyncio
async def test_decision_is_frozen_to_contracts_and_people(results_clean) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    world = await _placement(started_days_ago=40)
    await _set_setting(RULES_KEY, {"double_bonus": {"months": [key]}})
    # Osoba z wynikiem, ale kontraktu nie ma w zapisanej decyzji: bez 200%.
    await _set_setting(
        double_bonus.RESULTS_KEY,
        {key: {"recruiters": [world["recruiter"]], "dls": [world["dl"]]}},
    )
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["recruiter"].amount == Decimal("1500.00")
    # Kontrakt w decyzji, ale z innym rekruterem: 200% nie przechodzi na nowego.
    decision = _decision(key, world, recruiter=True, dl=False)
    decision[key]["recruiter_contracts"][str(world["contract"])] = world["dl"]
    await _set_setting(double_bonus.RESULTS_KEY, decision)
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["recruiter"].amount == Decimal("1500.00")


@pytest.mark.asyncio
async def test_settle_month_stores_dl_above_threshold_and_doubles(
    results_clean,
) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    # Marża 160 − 105 = 55 zł/h > 50: DL zrobił cel; rekruter bez KPI — nie.
    world = await _placement(started_days_ago=10, client_rate="160", cost_rate="105")
    await _update_contract(
        world["contract"],
        created_at=datetime(*signed, 3, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": [key]}})
    async with AsyncSessionLocal() as db:
        rules = await load_rules(db)
        evaluation, ids = await double_bonus.settle_month(
            db, *signed, rules, today=business_today()
        )
        await db.commit()
    assert world["contract"] in ids
    assert evaluation["stored"]["dl_contracts"] == {str(world["contract"]): world["dl"]}
    assert world["recruiter"] not in evaluation["stored"]["recruiters"]
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    assert found["dl"].amount == Decimal("1848.00")  # 2 × 10% × 55 × 168
    assert found["recruiter"].amount == Decimal("2000.00")
