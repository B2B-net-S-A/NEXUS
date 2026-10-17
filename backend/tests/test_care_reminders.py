"""Dzienny przebieg opieki (``app.services.care.reminders.run_once``).

* jeden przebieg na dzień kalendarza firmy (``hr_job_runs``), awaria daje się
  ponowić (Compass oddawał wtedy HTTP 200 z ``ok: false``),
* zaległy kontakt → dzwonek ``care_contact_due`` do opiekuna, najwyżej raz
  na 7 dni na kontrakt, link do zakładki „Opieka”,
* koniec projektu < 60 dni → wpis „Do przepięcia”,
* „dziś” to dzień w Warszawie (Compass liczył follow-up od północy UTC).

Dane zmyślone; baza wspólna, więc każdy test zakłada własne kontrakty.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import time_machine
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.contract import Contract
from app.models.contract_care import (
    CONTRACTS_CARE,
    CareConversation,
    CarePlanItem,
    RedeployQueueItem,
    TechCard,
)
from app.models.hr_ops import HrJobRun
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.services.care import access as care_access
from app.services.care import plan as care_plan
from app.services.care import reminders
from tests.test_care_api import (  # noqa: F401  (fixture'y modułów)
    care_off,
    care_on,
    make_client,
    make_contract,
    make_user,
)

pytestmark = pytest.mark.asyncio

#: 17.10.2026 00:30 w Warszawie; w UTC jeszcze 16.10.
AFTER_WARSAW_MIDNIGHT = datetime(2026, 10, 16, 22, 30, tzinfo=timezone.utc)


async def _forget_run(period: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(HrJobRun).where(
                HrJobRun.kind == reminders.JOB_KIND, HrJobRun.period_key == period
            )
        )
        await db.commit()


async def _set_owner(contract_id: int, user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CONTRACTS_CARE)
            .where(CONTRACTS_CARE.c.id == contract_id)
            .values(care_owner_user_id=user_id)
        )
        await db.commit()


async def _reminders_for(contract_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.notification_type
                        == NotificationType.care_contact_due,
                        Notification.related_entity_type == "contract",
                        Notification.related_entity_id == contract_id,
                    )
                )
            ).all()
        )


@pytest.mark.usefixtures("care_off")
async def test_run_once_does_nothing_with_module_off() -> None:
    async with AsyncSessionLocal() as db:
        assert await reminders.run_once(db) == {"status": "disabled"}


@pytest.mark.usefixtures("care_on")
async def test_run_once_plans_reminds_owner_and_flags_project_end() -> None:
    today = business_today()
    await _forget_run(today.isoformat())
    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    due_contract, _ = await make_contract(client_id, started_days_ago=10)
    await _set_owner(due_contract, owner.id)
    ending_contract, _ = await make_contract(client_id, started_days_ago=3)
    async with AsyncSessionLocal() as db:
        # Karta zapisana z pominięciem API (np. import) — wpis powstaje w przebiegu.
        db.add(
            TechCard(
                contract_id=ending_contract,
                client_id=client_id,
                interview_on=today,
                status="ok",
                is_draft=False,
                finalized_at=local_now(),
                project_end_on=today + timedelta(days=20),
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        result = await reminders.run_once(db)
    assert result["status"] == "done", result

    sent = await _reminders_for(due_contract)
    assert [n.user_id for n in sent] == [owner.id]
    assert sent[0].link == f"/contracts/{due_contract}?tab=care"
    assert "dzień 7" in sent[0].message
    async with AsyncSessionLocal() as db:
        kinds = set(
            (
                await db.scalars(
                    select(CarePlanItem.kind).where(
                        CarePlanItem.contract_id == due_contract
                    )
                )
            ).all()
        )
        # Kamień „dzień 7” i rozmowy z rytmu (etap 3: co 2 tygodnie przez 90 dni).
        assert {"day_7", "cadence"} <= kinds
        flagged = (
            await db.scalars(
                select(RedeployQueueItem).where(
                    RedeployQueueItem.contract_id == ending_contract
                )
            )
        ).all()
        assert [(i.reason, i.status, i.due_on) for i in flagged] == [
            ("project_end", "open", today + timedelta(days=20))
        ]

    async with AsyncSessionLocal() as db:
        again = await reminders.run_once(db)
    assert again == {"status": "skipped", "period": today.isoformat()}
    assert len(await _reminders_for(due_contract)) == 1


@pytest.mark.usefixtures("care_on")
async def test_reminder_repeats_only_after_seven_days() -> None:
    owner = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=owner)
    contract_id, _ = await make_contract(client_id, started_days_ago=12)
    today = business_today()
    async with AsyncSessionLocal() as db:
        contracts = await care_access.live_contracts(db, contract_ids=[contract_id])
        await care_plan.ensure_plan(
            db,
            contract_id,
            start=contracts[0].start_date,
            end=contracts[0].end_date,
            today=today,
        )
        first = await reminders.remind(db, contracts, today=today, now=local_now())
        await db.commit()
        second = await reminders.remind(db, contracts, today=today, now=local_now())
        await db.commit()
    assert first["sent"] == 1
    assert (second["sent"], second["skipped"]) == (0, 1)

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Notification)
            .where(
                Notification.notification_type == NotificationType.care_contact_due,
                Notification.related_entity_id == contract_id,
            )
            .values(created_at=local_now() - timedelta(days=8))
        )
        await db.commit()
        third = await reminders.remind(db, contracts, today=today, now=local_now())
        await db.commit()
    assert third["sent"] == 1
    assert [n.user_id for n in await _reminders_for(contract_id)] == [owner.id] * 2


@pytest.mark.usefixtures("care_on")
async def test_failed_run_can_be_retried_the_same_day() -> None:
    period = business_today().isoformat()
    await _forget_run(period)
    async with AsyncSessionLocal() as db:
        db.add(
            HrJobRun(
                kind=reminders.JOB_KIND, period_key=period, status="failed", error="X"
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        result = await reminders.run_once(db)
    assert result["status"] == "done", result
    async with AsyncSessionLocal() as db:
        run = await db.scalar(
            select(HrJobRun).where(
                HrJobRun.kind == reminders.JOB_KIND, HrJobRun.period_key == period
            )
        )
        assert (run.status, run.error) == ("done", None)


@pytest.mark.usefixtures("care_on")
async def test_follow_up_is_due_by_the_warsaw_calendar() -> None:
    """00:30 w Warszawie: follow-up „na dziś” już jest do zrobienia."""

    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        # Start 14.10 — żaden punkt planu nie wypada do 17.10, dzwoni tylko follow-up.
        contract.start_date = date(2026, 10, 14)
        db.add(
            CareConversation(
                contract_id=contract_id,
                occurred_on=date(2026, 10, 15),
                channel="phone",
                follow_up_on=date(2026, 10, 17),
            )
        )
        await db.commit()
    await _set_owner(contract_id, owner.id)
    await _forget_run("2026-10-17")

    with time_machine.travel(AFTER_WARSAW_MIDNIGHT, tick=False):
        async with AsyncSessionLocal() as db:
            result = await reminders.run_once(db)
    assert result["status"] == "done", result
    sent = await _reminders_for(contract_id)
    assert [n.user_id for n in sent] == [owner.id]
    assert "umówiony kolejny kontakt — dziś" in sent[0].message
    async with AsyncSessionLocal() as db:
        assert await db.scalar(
            select(HrJobRun.id).where(
                HrJobRun.kind == reminders.JOB_KIND, HrJobRun.period_key == "2026-10-17"
            )
        )
