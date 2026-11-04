"""Import stawek i premii z Compassa: raport bez kwot, idempotencja, CHECK-i.

Kwoty i nazwiska są zmyślone; każdy test kończy się rollbackiem.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.hr_payroll import EmployeeRate, HrBonus
from app.services.hr import compass_import
from app.services.hr.compass_import import payroll as payroll_import
from tests.test_hr_compass_import_leave import (
    assert_report_clean,
    make_bundle,
    make_person,
    run_import,
)


def _rate(person: str, start: str, *, end=None, rate="187.25", currency="PLN") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "user_id": person,
        "hourly_rate": rate,
        "currency": currency,
        "effective_from": start,
        "effective_to": end,
        "reason": "Podwyżka roczna",
        "set_by": None,
        "created_at": "2026-05-01T08:00:00+00:00",
    }


def _bonus(person: str, proposer: str, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "recipient_user_id": person,
        "proposed_by": proposer,
        "amount": "4321.50",
        "currency": "PLN",
        "category": "recruiter",
        "status": "assigned",
        "period_year": 2026,
        "period_month": 8,
        "period_quarter": None,
        "reason": "Premia za placement",
        "recruiter_candidate_name": "Kandydat Przykładowy",
        "recruiter_margin_per_hour": 41.5,
        "cancelled_at": None,
        "cancelled_by": None,
        "cancellation_reason": None,
        "created_at": "2026-09-03T08:00:00+00:00",
        **values,
    }


@pytest.mark.asyncio
async def test_payroll_dry_run_apply_and_second_apply_changes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            person, r_id, r_row = await make_person(db, f"{tag}-person")
            boss, p_id, p_row = await make_person(db, f"{tag}-boss")
            manual, m_id, m_row = await make_person(db, f"{tag}-manual")
            _, n_id, n_row = await make_person(db, f"{tag}-none", with_profile=False)
            db.add(
                EmployeeRate(
                    user_id=manual.id,
                    hourly_rate=Decimal("150.00"),
                    effective_from=date(2026, 9, 1),
                )
            )
            await db.flush()

            older = _rate(r_id, "2026-01-01")  # druga otwarta stawka w Compassie
            current = _rate(r_id, "2026-05-01", rate="199.99")
            mid_month = _rate(r_id, "2026-07-15")
            manual_history = _rate(m_id, "2026-01-01")
            no_profile_rate = _rate(n_id, "2026-01-01")

            assigned = _bonus(r_id, p_id)
            cancelled = _bonus(
                r_id,
                p_id,
                currency="EUR",
                category="delivery_lead",
                status="cancelled",
                cancelled_at="2026-09-10T08:00:00+00:00",
                cancelled_by=p_id,
                cancellation_reason="Pomyłka w okresie",
            )
            league = _bonus(
                r_id,
                p_id,
                category="champions_league",
                period_month=None,
                period_quarter=3,
                place_rank=1,
            )
            self_proposed = _bonus(r_id, r_id, category="custom")
            no_profile_bonus = _bonus(n_id, p_id)
            zero = _bonus(r_id, p_id, amount="0")
            bundle = make_bundle(
                {
                    "profiles": [r_row, p_row, m_row, n_row],
                    "user_rates": [
                        older,
                        current,
                        mid_month,
                        manual_history,
                        no_profile_rate,
                    ],
                    "bonuses": [
                        assigned,
                        cancelled,
                        league,
                        self_proposed,
                        no_profile_bonus,
                        zero,
                    ],
                }
            )
            importer = compass_import.IMPORTERS["payroll"]

            batch, report, written = await run_import(db, "payroll", bundle)
            assert report["counts"] == {"create": 6, "conflict": 2, "skip": 3}
            assert report["reasons"]["historia stawek prowadzona już w NEXUSIE"] == 1
            assert report["reasons"]["stawka nie od 1. dnia miesiąca"] == 1
            assert report["reasons"][payroll_import.SELF_PROPOSED] == 1
            assert report["reasons"]["kwota premii poza zakresem"] == 1
            # Suma kontrolna per waluta = liczba wierszy, nie kwota.
            assert report["extra"] == {
                "rate_rows_per_currency": {"PLN": 2},
                "bonus_rows_per_currency": {"PLN": 3, "EUR": 1},
            }
            assert_report_clean(
                batch.report,
                "4321",
                "187.25",
                "199.99",
                "Kandydat Przykładowy",
                "Premia za placement",
            )
            assert written == {"rates_written": 2, "bonuses_written": 4}

            rates = list(
                await db.scalars(
                    select(EmployeeRate)
                    .where(EmployeeRate.user_id == person.id)
                    .order_by(EmployeeRate.effective_from)
                )
            )
            assert [(r.effective_from, r.effective_to) for r in rates] == [
                (date(2026, 1, 1), date(2026, 4, 30)),
                (date(2026, 5, 1), None),
            ]
            assert str(rates[0].compass_id) == older["id"]

            by_compass = {
                str(b.compass_id): b
                for b in await db.scalars(
                    select(HrBonus).where(HrBonus.recipient_user_id == person.id)
                )
            }
            first = by_compass[assigned["id"]]
            assert first.source == "compass_import"
            assert first.source_key == f"compass:{assigned['id']}"
            assert first.status == "assigned"
            assert first.assigned_by == boss.id
            assert first.assigned_at is not None
            assert first.amount == Decimal("4321.50")
            assert first.rule_snapshot["compass"]["recruiter_margin_per_hour"] == 41.5
            dropped = by_compass[cancelled["id"]]
            assert dropped.status == "cancelled"
            assert dropped.cancel_reason == "manual"
            assert dropped.cancelled_by == boss.id
            quarterly = by_compass[league["id"]]
            assert (quarterly.category, quarterly.period_month) == ("league", 9)
            own = by_compass[self_proposed["id"]]
            assert own.proposed_by is None
            assert own.assigned_by is None

            batch2, _ = await compass_import.dry_run(
                db,
                module="payroll",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert batch2.report["dry_run"]["counts"] == {
                "unchanged": 6,
                "conflict": 2,
                "skip": 3,
            }
            written2 = await compass_import.apply(
                db,
                batch=batch2,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            assert written2 == {"rates_written": 0, "bonuses_written": 0}
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_payroll_dry_run_writes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            person, r_id, r_row = await make_person(db, f"{tag}-person")
            _, p_id, p_row = await make_person(db, f"{tag}-boss")
            bundle = make_bundle(
                {
                    "profiles": [r_row, p_row],
                    "user_rates": [_rate(r_id, "2026-01-01")],
                    "bonuses": [_bonus(r_id, p_id)],
                }
            )
            importer = compass_import.IMPORTERS["payroll"]
            _, plan = await compass_import.dry_run(
                db,
                module="payroll",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan.counts() == {"create": 2}
            assert (
                await db.scalar(
                    select(EmployeeRate.id).where(EmployeeRate.user_id == person.id)
                )
                is None
            )
            assert (
                await db.scalar(
                    select(HrBonus.id).where(HrBonus.recipient_user_id == person.id)
                )
                is None
            )
        finally:
            await db.rollback()
