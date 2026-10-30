"""Okno premii Płac: zmiana osoby trwała mimo automatu, zatwierdzenie przed terminem,
oznaczenia i vouchery. Dane fikcyjne."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.contract import Contract
from app.models.hr_payroll import HrBonus
from app.models.user import User
from app.services.hr import bonus_decisions, bonus_flags, payroll_bonuses
from app.services.hr.payroll_access import PayrollViewer
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollError,
    PayrollForbidden,
)
from tests.test_hr_bonus_automation import (  # noqa: F401
    _bonuses,
    _person,
    _placement,
    _reconcile,
    payroll_on,
)


async def _payroll_viewer() -> PayrollViewer:
    async with AsyncSessionLocal() as db:
        person = await _person(db, "finance")
        await db.commit()
        return PayrollViewer(
            user_id=person.id, payroll=True, admin=False, report_ids=frozenset()
        )


async def _other_person() -> int:
    async with AsyncSessionLocal() as db:
        person = await _person(db, "recruiter")
        await db.commit()
        return person.id


@pytest.mark.asyncio
async def test_recipient_change_survives_automat_and_needs_reason(payroll_on) -> None:  # noqa: F811
    world = await _placement(started_days_ago=40)
    await _reconcile(world["contract"])
    viewer = await _payroll_viewer()
    new_person = await _other_person()
    recruiter = (await _bonuses(world["contract"]))["recruiter"]

    async with AsyncSessionLocal() as db:
        with pytest.raises(PayrollError):
            await payroll_bonuses.update_bonus(
                db,
                viewer,
                recruiter.id,
                {"recipient_user_id": new_person},
                today=business_today(),
            )
        await db.rollback()
        await payroll_bonuses.update_bonus(
            db,
            viewer,
            recruiter.id,
            {"recipient_user_id": new_person, "change_reason": "Prowadziła proces"},
            today=business_today(),
        )
        await db.commit()

    await _reconcile(world["contract"])
    after = (await _bonuses(world["contract"]))["recruiter"]
    assert after.recipient_user_id == new_person
    assert after.rule_snapshot["automat_recipient_user_id"] == world["recruiter"]
    # Kwota dalej się przelicza: nikt jej nie zmienił.
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
        contract.rate_client = Decimal("170")
        await db.commit()
    await _reconcile(world["contract"])
    again = (await _bonuses(world["contract"]))["recruiter"]
    assert again.recipient_user_id == new_person
    assert again.amount == Decimal("2000.00")


@pytest.mark.asyncio
async def test_recipient_change_refuses_self_and_non_payroll(payroll_on) -> None:  # noqa: F811
    world = await _placement(started_days_ago=40)
    await _reconcile(world["contract"])
    viewer = await _payroll_viewer()
    other = await _other_person()
    recruiter = (await _bonuses(world["contract"]))["recruiter"]
    async with AsyncSessionLocal() as db:
        with pytest.raises(PayrollForbidden):
            await payroll_bonuses.update_bonus(
                db,
                viewer,
                recruiter.id,
                {"recipient_user_id": viewer.user_id, "change_reason": "x"},
                today=business_today(),
            )
        await db.rollback()
        manager = PayrollViewer(
            user_id=other,
            payroll=False,
            admin=False,
            report_ids=frozenset({recruiter.recipient_user_id}),
        )
        with pytest.raises(PayrollForbidden):
            await payroll_bonuses.update_bonus(
                db,
                manager,
                recruiter.id,
                {"recipient_user_id": other, "change_reason": "x"},
                today=business_today(),
            )


@pytest.mark.asyncio
async def test_period_change_survives_automat(payroll_on) -> None:  # noqa: F811
    world = await _placement(started_days_ago=40)
    await _reconcile(world["contract"])
    viewer = await _payroll_viewer()
    dl = (await _bonuses(world["contract"]))["dl"]
    target = (dl.period_year + 1, 1)
    async with AsyncSessionLocal() as db:
        await payroll_bonuses.update_bonus(
            db,
            viewer,
            dl.id,
            {"period_year": target[0], "period_month": target[1]},
            today=business_today(),
        )
        await db.commit()
    await _reconcile(world["contract"])
    after = (await _bonuses(world["contract"]))["dl"]
    assert (after.period_year, after.period_month) == target


@pytest.mark.asyncio
async def test_payroll_approves_before_deadline_manager_does_not(payroll_on) -> None:  # noqa: F811
    world = await _placement(started_days_ago=1)
    await _reconcile(world["contract"])
    viewer = await _payroll_viewer()
    other = await _other_person()
    bonuses = await _bonuses(world["contract"])
    today = business_today()
    async with AsyncSessionLocal() as db:
        manager = PayrollViewer(
            user_id=other,
            payroll=False,
            admin=False,
            report_ids=frozenset({bonuses["dl"].recipient_user_id}),
        )
        with pytest.raises(PayrollConflict):
            await payroll_bonuses.approve_bonus(
                db, manager, bonuses["dl"].id, today=today
            )
        await db.rollback()
        approved = await payroll_bonuses.approve_bonus(
            db, viewer, bonuses["dl"].id, today=today
        )
        assert approved.status == "assigned"
        await db.rollback()


@pytest.mark.asyncio
async def test_flags_inactive_day_rate_and_missing_order(payroll_on) -> None:  # noqa: F811
    world = await _placement(started_days_ago=40, client_rate="1300", cost_rate="120")
    await _reconcile(world["contract"])
    bonuses = await _bonuses(world["contract"])
    async with AsyncSessionLocal() as db:
        (await db.get(User, world["recruiter"])).is_active = False
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows = list(
            await db.scalars(
                select(HrBonus).where(HrBonus.contract_id == world["contract"])
            )
        )
        flags = await bonus_flags.bonus_flags(db, rows, today=business_today())
    recruiter_codes = {f["code"] for f in flags[bonuses["recruiter"].id]}
    assert {"inactive", "high_margin", "no_order"} <= recruiter_codes
    assert "inactive" not in {f["code"] for f in flags[bonuses["dl"].id]}


def test_groups_skip_own_bonus_and_split_flagged() -> None:
    def item(pk, source, recipient, flags=()):
        return {
            "id": pk,
            "source": source,
            "recipient_user_id": recipient,
            "flags": list(flags),
        }

    groups = bonus_decisions.group_decisions(
        [
            item(1, "contract_placement", 2),
            item(2, "league", 2),
            item(3, "contract_placement", 2, [{"code": "owner"}]),
            item(4, "contract_placement", 9),
        ],
        viewer_id=9,
    )
    assert [row["id"] for row in groups["signed"]] == [1]
    assert [row["id"] for row in groups["league"]] == [2]
    assert [row["id"] for row in groups["check"]] == [3]


@pytest.mark.asyncio
async def test_voucher_confirmation_once_and_not_own(payroll_on) -> None:  # noqa: F811
    viewer = await _payroll_viewer()
    other = await _other_person()
    async with AsyncSessionLocal() as db:
        winner = CompetitionWinner(
            competition_type=CompetitionType.monthly_placements.value,
            period="2099-01",
            user_id=other,
            rank=1,
            points=1,
            metric_value=1,
            prize_pln=100,
        )
        db.add(winner)
        await db.commit()
        winner_id = winner.id
    try:
        async with AsyncSessionLocal() as db:
            own = PayrollViewer(
                user_id=other, payroll=True, admin=False, report_ids=frozenset()
            )
            with pytest.raises(PayrollForbidden):
                await bonus_decisions.confirm_voucher(db, own, winner_id)
            await bonus_decisions.confirm_voucher(db, viewer, winner_id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert str(winner_id) in await bonus_decisions._confirmations(db)
    finally:
        async with AsyncSessionLocal() as db:
            await db.delete(await db.get(CompetitionWinner, winner_id))
            await db.commit()
