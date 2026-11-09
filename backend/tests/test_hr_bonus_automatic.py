"""Premie z automatu (decyzje z 09.11.2026): samo przyznawanie, gwarancja, ręczne tylko admin.

Dane fikcyjne; stawki zmyślone.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.hr_payroll import HrBonus, HrBonusClawback
from app.models.notification import Notification
from app.models.user import User
from app.services.hr import bonus_auto_assign, bonus_guarantee, double_bonus
from app.services.hr.bonus_rules import SETTING_KEY as RULES_KEY
from app.services.hr.bonus_rules import BonusRulesError, parse_rules, rules_payload
from tests.test_hr_bonus_automation import (  # noqa: F401  (fikstura)
    _bonuses,
    _person,
    _placement,
    _reconcile,
    _set_setting,
    _update_contract,
    payroll_on,
)
from tests.test_hr_double_bonus import _payroll_headers, _set_job_dl

pytestmark = pytest.mark.usefixtures("payroll_on")

AUTOMATIC = {"auto_assign_from": "2020-01"}


async def _admin_headers() -> tuple[dict[str, str], int]:
    async with AsyncSessionLocal() as db:
        person = await _person(db, "admin")
        await db.commit()
        token = create_access_token(subject=person.id, role="admin")
        return {"Authorization": f"Bearer {token}"}, person.id


async def _ready_placement() -> dict:
    """Placement po terminie premii, z zamówieniem, bez znaczników."""

    world = await _placement(started_days_ago=45)
    await _update_contract(
        world["contract"],
        client_order_start_date=business_today() - timedelta(days=45),
    )
    return world


async def _assign() -> dict:
    async with AsyncSessionLocal() as db:
        counts = await bonus_auto_assign.assign_due(db, today=business_today())
        await db.commit()
    return counts


async def _sync_guarantees() -> dict:
    async with AsyncSessionLocal() as db:
        counts = await bonus_guarantee.sync_guarantees(db, today=business_today())
        await db.commit()
    return counts


async def _debts(user_id: int) -> list[HrBonusClawback]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(HrBonusClawback).where(
                    HrBonusClawback.recipient_user_id == user_id,
                    HrBonusClawback.status != "cancelled",
                )
            )
        )


async def _same_person(earlier: int, later: int) -> None:
    async with AsyncSessionLocal() as db:
        candidate = await db.scalar(
            select(Contract.candidate_id).where(Contract.id == later)
        )
    await _update_contract(earlier, candidate_id=candidate)


async def _import_row(world: dict, *, amount: str = "700.00") -> tuple[int, str]:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
        candidate = await db.get(Candidate, contract.candidate_id)
        start = contract.start_date
        bonus = HrBonus(
            recipient_user_id=world["dl"],
            amount=Decimal(amount),
            currency="PLN",
            category="delivery_lead",
            period_year=start.year,
            period_month=start.month,
            status="assigned",
            source="compass_import",
            source_key=f"import-{world['contract']}",
            assigned_at=contract.created_at,
            description=f"Premia DL — placement {candidate.name} {candidate.lastname} @ Klient",
        )
        db.add(bonus)
        await db.commit()
        return bonus.id, candidate.lastname


# ── Reguły ──


def test_rules_roundtrip_and_refuse_bad_values() -> None:
    rules = parse_rules(
        {
            "auto_assign_from": "2026-11",
            "rule_items": [
                {"user_id": 7, "amount": "1200", "month": "2026-11", "reason": "Punkty"}
            ],
        }
    )
    assert rules.auto_assign_from == (2026, 11)
    assert rules.rule_items[0].amount == Decimal("1200.00")
    assert parse_rules(rules_payload(rules)) == rules
    with pytest.raises(BonusRulesError, match="RRRR-MM"):
        parse_rules({"auto_assign_from": "listopad"})
    with pytest.raises(BonusRulesError, match="powód"):
        parse_rules(
            {
                "rule_items": [
                    {"user_id": 7, "amount": "10", "month": "2026-11", "reason": " "}
                ]
            }
        )


# ── Samo przyznawanie ──


@pytest.mark.asyncio
async def test_nothing_is_assigned_until_the_setting_is_on() -> None:
    world = await _ready_placement()
    await _reconcile(world["contract"])
    assert (await _assign())["assigned"] == 0
    assert (await _bonuses(world["contract"]))["dl"].status == "proposed"


@pytest.mark.asyncio
async def test_due_bonus_is_assigned_with_no_person_and_a_bell() -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    world = await _ready_placement()
    await _reconcile(world["contract"])
    counts = await _assign()
    assert counts["assigned"] >= 2

    found = await _bonuses(world["contract"])
    assert found["dl"].status == "assigned"
    assert found["dl"].assigned_by is None
    assert found["dl"].assigned_at is not None
    async with AsyncSessionLocal() as db:
        bells = await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.related_entity_type == "hr_bonus",
                Notification.related_entity_id == found["dl"].id,
            )
        )
    assert bells == 1


@pytest.mark.asyncio
async def test_bonus_before_deadline_or_before_start_month_waits() -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    fresh = await _placement(started_days_ago=3)
    await _reconcile(fresh["contract"])
    await _assign()
    assert (await _bonuses(fresh["contract"]))["dl"].status == "proposed"

    await _set_setting(RULES_KEY, {"auto_assign_from": "2100-01"})
    world = await _ready_placement()
    await _reconcile(world["contract"])
    await _assign()
    assert (await _bonuses(world["contract"]))["dl"].status == "proposed"


@pytest.mark.asyncio
async def test_flagged_bonus_is_held_for_the_admin() -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    world = await _placement(started_days_ago=45)  # bez daty zamówienia
    await _update_contract(world["contract"], client_order_start_date=None)
    await _reconcile(world["contract"])
    counts = await _assign()
    assert counts["held"] >= 1
    assert (await _bonuses(world["contract"]))["dl"].status == "proposed"


@pytest.mark.asyncio
async def test_contract_signed_in_program_month_waits_for_the_result() -> None:
    today = business_today()
    key = f"{today.year}-{today.month:02d}"
    await _set_setting(RULES_KEY, {**AUTOMATIC, "double_bonus": {"months": [key]}})
    await _set_setting(double_bonus.RESULTS_KEY, None)
    world = await _ready_placement()
    await _reconcile(world["contract"])
    await _assign()
    assert (await _bonuses(world["contract"]))["dl"].status == "proposed"


# ── Odbiorca odszedł ──


@pytest.mark.asyncio
async def test_recipient_who_left_loses_the_bonus_until_account_returns() -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    world = await _ready_placement()
    await _reconcile(world["contract"])

    async with AsyncSessionLocal() as db:
        (await db.get(User, world["recruiter"])).is_active = False
        await db.commit()
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    assert found["recruiter"].status == "cancelled"
    assert found["recruiter"].cancel_reason == "recipient_left"
    assert found["dl"].status == "proposed"

    async with AsyncSessionLocal() as db:
        (await db.get(User, world["recruiter"])).is_active = True
        await db.commit()
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["recruiter"].status == "proposed"


async def _proposal(world: dict, role: str = "dl") -> HrBonus:
    await _reconcile(world["contract"])
    return (await _bonuses(world["contract"]))[role]


@pytest.mark.asyncio
async def test_sheet_row_of_someone_who_left_is_lost_not_assigned() -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    world = await _ready_placement()
    bonus = await _proposal(world)
    async with AsyncSessionLocal() as db:
        row = await db.get(HrBonus, bonus.id)
        row.rule_snapshot = {**row.rule_snapshot, "settlement_import": True}
        (await db.get(User, world["dl"])).is_active = False
        await db.commit()
    await _reconcile(world["contract"])
    await _assign()
    found = (await _bonuses(world["contract"]))["dl"]
    assert found.status == "cancelled"
    assert found.cancel_reason == "recipient_left"


@pytest.mark.asyncio
async def test_lost_bonus_does_not_pass_to_a_new_dl() -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    world = await _ready_placement()
    await _proposal(world)
    async with AsyncSessionLocal() as db:
        (await db.get(User, world["dl"])).is_active = False
        successor = await _person(db, "delivery_lead")
        await db.commit()
        successor_id = successor.id
    await _reconcile(world["contract"])
    await _set_job_dl(world["contract"], successor_id)
    await _reconcile(world["contract"])
    found = (await _bonuses(world["contract"]))["dl"]
    assert found.status == "cancelled"
    assert found.recipient_user_id == world["dl"]


@pytest.mark.asyncio
async def test_doubled_bonus_is_assigned_before_its_deadline() -> None:
    today = business_today()
    await _set_setting(RULES_KEY, AUTOMATIC)
    world = await _placement(started_days_ago=3)
    await _update_contract(world["contract"], client_order_start_date=today)
    bonus = await _proposal(world)
    assert bonus.eligible_on > today
    await _assign()
    assert (await _bonuses(world["contract"]))["dl"].status == "proposed"

    async with AsyncSessionLocal() as db:
        row = await db.get(HrBonus, bonus.id)
        row.rule_snapshot = {
            **row.rule_snapshot,
            "double_bonus": {"month": "2020-01", "multiplier": "2"},
        }
        await db.commit()
    await _assign()
    assert (await _bonuses(world["contract"]))["dl"].status == "assigned"


# ── Przepięcie ──


@pytest.mark.asyncio
async def test_continuation_gives_no_dl_bonus_but_recruiter_keeps_his() -> None:
    today = business_today()
    earlier = await _placement(
        started_days_ago=200,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=50),
    )
    world = await _placement(started_days_ago=40)
    await _same_person(earlier["contract"], world["contract"])
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    assert "dl" not in found
    assert found["recruiter"].status == "proposed"


@pytest.mark.asyncio
async def test_new_contract_after_a_long_break_is_a_new_placement() -> None:
    today = business_today()
    earlier = await _placement(
        started_days_ago=300,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=90),
    )
    world = await _placement(started_days_ago=40)
    await _same_person(earlier["contract"], world["contract"])
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["dl"].status == "proposed"


# ── Gwarancja ──


async def _assigned_dl(world: dict) -> HrBonus:
    await _reconcile(world["contract"])
    async with AsyncSessionLocal() as db:
        bonus = await db.scalar(
            select(HrBonus).where(
                HrBonus.contract_id == world["contract"],
                HrBonus.category == "delivery_lead",
            )
        )
        bonus.status = "assigned"
        bonus.assigned_at = func.now()
        await db.commit()
    return bonus


@pytest.mark.asyncio
async def test_guarantee_broken_by_any_reason_creates_a_debt_of_the_whole_bonus() -> (
    None
):
    world = await _ready_placement()
    bonus = await _assigned_dl(world)
    await _update_contract(
        world["contract"],
        status=ContractStatus.ended,
        end_date=business_today() - timedelta(days=1),
    )
    await _sync_guarantees()
    debts = await _debts(world["dl"])
    assert [d.bonus_id for d in debts] == [bonus.id]
    assert debts[0].amount == bonus.amount
    assert debts[0].deduct_from == business_today().replace(day=1)


@pytest.mark.asyncio
async def test_continuation_keeps_guarantee_until_the_chain_breaks() -> None:
    today = business_today()
    world = await _ready_placement()
    await _assigned_dl(world)
    await _update_contract(
        world["contract"],
        status=ContractStatus.ended,
        end_date=today - timedelta(days=10),
    )
    following = await _placement(started_days_ago=9)
    await _same_person(world["contract"], following["contract"])
    await _sync_guarantees()
    assert await _debts(world["dl"]) == []

    await _update_contract(
        following["contract"],
        status=ContractStatus.ended,
        end_date=today - timedelta(days=1),
    )
    await _sync_guarantees()
    assert len(await _debts(world["dl"])) == 1


@pytest.mark.asyncio
async def test_imported_bonus_gets_a_debt_only_when_automatic_is_on() -> None:
    today = business_today()
    world = await _placement(
        started_days_ago=100,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=20),
    )
    bonus_id, _lastname = await _import_row(world)

    await _sync_guarantees()
    assert await _debts(world["dl"]) == []

    await _set_setting(RULES_KEY, AUTOMATIC)
    await _sync_guarantees()
    debts = await _debts(world["dl"])
    assert [d.bonus_id for d in debts] == [bonus_id]
    assert debts[0].contract_id == world["contract"]
    assert debts[0].amount == Decimal("700.00")


@pytest.mark.asyncio
async def test_imported_bonus_settled_in_october_gets_no_debt(monkeypatch) -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    world = await _placement(
        started_days_ago=100,
        status=ContractStatus.ended,
        end_date=business_today() - timedelta(days=20),
    )
    bonus_id, _lastname = await _import_row(world)
    monkeypatch.setattr(
        bonus_guarantee, "SETTLED_BEFORE_AUTOMATION", frozenset({bonus_id})
    )
    await _sync_guarantees()
    assert await _debts(world["dl"]) == []


@pytest.mark.asyncio
async def test_draft_contract_is_not_a_continuation() -> None:
    today = business_today()
    world = await _ready_placement()
    await _assigned_dl(world)
    await _update_contract(
        world["contract"],
        status=ContractStatus.ended,
        end_date=today - timedelta(days=10),
    )
    draft = await _placement(started_days_ago=9, status=ContractStatus.draft)
    await _same_person(world["contract"], draft["contract"])
    await _sync_guarantees()
    assert len(await _debts(world["dl"])) == 1


@pytest.mark.asyncio
async def test_import_ignores_void_contract_and_old_history() -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    today = business_today()
    world = await _placement(
        started_days_ago=100,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=20),
    )
    bonus_id, _lastname = await _import_row(world)
    void = await _placement(
        started_days_ago=100,
        status=ContractStatus.void,
        end_date=today - timedelta(days=20),
    )
    await _same_person(void["contract"], world["contract"])
    await _sync_guarantees()
    assert [d.bonus_id for d in await _debts(world["dl"])] == [bonus_id]

    old = await _placement(
        started_days_ago=700,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=600),
    )
    await _import_row(old)
    await _sync_guarantees()
    assert await _debts(old["dl"]) == []


@pytest.mark.asyncio
async def test_import_name_must_start_a_word() -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    world = await _placement(
        started_days_ago=100,
        status=ContractStatus.ended,
        end_date=business_today() - timedelta(days=20),
    )
    bonus_id, _lastname = await _import_row(world)
    async with AsyncSessionLocal() as db:
        row = await db.get(HrBonus, bonus_id)
        row.description = (
            f"Premia DL — placement Jo{row.description.split('placement ')[1]}"
        )
        await db.commit()
    await _sync_guarantees()
    assert await _debts(world["dl"]) == []


# ── Pozycje admina ──


@pytest.mark.asyncio
async def test_rule_item_is_assigned_once() -> None:
    world = await _placement(started_days_ago=3)
    today = business_today()
    month = f"{today.year}-{today.month:02d}"
    await _set_setting(
        RULES_KEY,
        {
            **AUTOMATIC,
            "rule_items": [
                {
                    "user_id": world["recruiter"],
                    "amount": "1495",
                    "month": month,
                    "reason": "Premia za punkty",
                }
            ],
        },
    )
    for _ in range(2):
        async with AsyncSessionLocal() as db:
            await bonus_auto_assign.assign_rule_items(db)
            await db.commit()
    async with AsyncSessionLocal() as db:
        rows = list(
            await db.scalars(
                select(HrBonus).where(
                    HrBonus.recipient_user_id == world["recruiter"],
                    HrBonus.source == "manual",
                )
            )
        )
    assert len(rows) == 1
    assert rows[0].status == "assigned"
    assert rows[0].amount == Decimal("1495.00")
    assert rows[0].description == "Premia za punkty"


@pytest.mark.asyncio
async def test_rule_items_wait_for_the_setting_and_refuse_oneself(app_client) -> None:
    world = await _placement(started_days_ago=3)
    today = business_today()
    item = {
        "user_id": world["recruiter"],
        "amount": "100",
        "month": f"{today.year}-{today.month:02d}",
        "reason": "Pozycja testowa",
    }
    await _set_setting(RULES_KEY, {"rule_items": [item]})
    async with AsyncSessionLocal() as db:
        counts = await bonus_auto_assign.assign_rule_items(db)
        await db.commit()
    assert counts == {"items_assigned": 0}

    async with AsyncSessionLocal() as db:
        person = await _person(db, "admin")
        await db.commit()
        own = person.id
        token = create_access_token(subject=own, role="admin")
    response = await app_client.put(
        "/api/hr/payroll/rules",
        json={"rule_items": [{**item, "user_id": own}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


# ── Ręczne tylko admin ──


@pytest.mark.asyncio
async def test_manual_actions_are_open_while_automatic_is_off(app_client) -> None:
    headers = await _payroll_headers()
    mode = await app_client.get("/api/hr/payroll/bonus-mode", headers=headers)
    assert mode.json() == {"automatic": False, "manual_allowed": True}


@pytest.mark.asyncio
async def test_only_admin_changes_bonus_by_hand_and_gives_a_reason(app_client) -> None:
    await _set_setting(RULES_KEY, AUTOMATIC)
    world = await _ready_placement()
    await _reconcile(world["contract"])
    bonus = (await _bonuses(world["contract"]))["dl"]
    payroll = await _payroll_headers()

    mode = await app_client.get("/api/hr/payroll/bonus-mode", headers=payroll)
    assert mode.json() == {"automatic": True, "manual_allowed": False}
    denied = await app_client.post(
        f"/api/hr/payroll/bonuses/{bonus.id}/cancel",
        json={"note": "nie należy się"},
        headers=payroll,
    )
    assert denied.status_code == 403
    approve = await app_client.post(
        f"/api/hr/payroll/bonuses/{bonus.id}/approve", headers=payroll
    )
    assert approve.status_code == 403

    admin, _admin_id = await _admin_headers()
    no_reason = await app_client.post(
        f"/api/hr/payroll/bonuses/{bonus.id}/cancel", json={}, headers=admin
    )
    assert no_reason.status_code == 422
    done = await app_client.post(
        f"/api/hr/payroll/bonuses/{bonus.id}/cancel",
        json={"note": "Korekta po zgłoszeniu"},
        headers=admin,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_report_notifies_admin_and_needs_a_note(app_client) -> None:
    world = await _ready_placement()
    await _reconcile(world["contract"])
    bonus = (await _bonuses(world["contract"]))["dl"]
    _headers, admin_id = await _admin_headers()
    payroll = await _payroll_headers()

    empty = await app_client.post(
        f"/api/hr/payroll/bonuses/{bonus.id}/report", json={}, headers=payroll
    )
    assert empty.status_code in (400, 409, 422)
    sent = await app_client.post(
        f"/api/hr/payroll/bonuses/{bonus.id}/report",
        json={"note": "Zła osoba przy tym placemencie"},
        headers=payroll,
    )
    assert sent.status_code == 204, sent.text
    async with AsyncSessionLocal() as db:
        bells = await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == admin_id,
                Notification.related_entity_type == "hr_bonus",
                Notification.related_entity_id == bonus.id,
            )
        )
    assert bells == 1
