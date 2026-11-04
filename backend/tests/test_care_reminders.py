"""Dzienny przebieg opieki (``app.services.care.reminders.run_once``).

* jeden przebieg na dzień kalendarza firmy (``hr_job_runs``), awaria daje się
  ponowić (Compass oddawał wtedy HTTP 200 z ``ok: false``),
* zaległy kontakt → dzwonek ``care_contact_due`` do opiekuna, najwyżej raz
  na 7 dni na kontrakt, link do karty konsultanta (``/care?contract=<id>``),
  zbiorczy — do „Do zrobienia” z filtrem (makieta R2, 22.10.2026),
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
from app.models.hr_ops import HrAuditEvent, HrJobRun
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
    assert sent[0].link == f"/care?contract={due_contract}"
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


#: 17.10.2026 10:00 w Warszawie.
OCT_17_MORNING = datetime(2026, 10, 17, 8, 0, tzinfo=timezone.utc)


async def _open_due(contract_id: int, today: date) -> list[CarePlanItem]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CarePlanItem).where(
                        CarePlanItem.contract_id == contract_id,
                        CarePlanItem.status == "open",
                        CarePlanItem.due_on <= today,
                    )
                )
            ).all()
        )


@pytest.mark.usefixtures("care_on")
async def test_last_talk_covers_earlier_plan_points() -> None:
    """Rozmowa opiekuna (także z importu Compassa) pokrywa wcześniejsze punkty.

    Po włączeniu modułu prawie każdy kontrakt miał zaległą rozmowę z rytmu,
    choć opiekun rozmawiał z konsultantem po jej terminie (przegląd
    17.10.2026). Punkt z terminem nie późniejszym niż ostatnia rozmowa nie
    powstaje, a już otwarty zamyka przebieg nocny tą rozmową. Kontrakt bez
    żadnej rozmowy dalej ma zaległość.
    """

    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    # Program 90 dni do 01.07, potem co miesiąc: 01.08, 01.09, 01.10, 01.11…
    start = date(2026, 7, 1) - timedelta(days=90)
    imported, planned, silent = [(await make_contract(client_id))[0] for _ in range(3)]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id.in_([imported, planned, silent]))
            .values(start_date=start)
        )
        await db.commit()
    for contract_id in (imported, planned, silent):
        await _set_owner(contract_id, owner.id)
    await _forget_run("2026-10-17")

    with time_machine.travel(OCT_17_MORNING, tick=False):
        today = business_today()
        async with AsyncSessionLocal() as db:
            # Plan założony przed importem rozmów (moduł włączony wcześniej).
            contracts = await care_access.live_contracts(db, contract_ids=[planned])
            await care_plan.ensure_plans(db, contracts, today=today)
            await db.commit()
        assert [item.due_on for item in await _open_due(planned, today)] == [
            date(2026, 10, 1)
        ]
        async with AsyncSessionLocal() as db:
            talks = {
                contract_id: CareConversation(
                    contract_id=contract_id,
                    occurred_on=date(2026, 10, 10),
                    channel="phone",
                    compass_source_id=f"compass-{contract_id}",
                )
                for contract_id in (imported, planned)
            }
            db.add_all(talks.values())
            await db.commit()
            talk_ids = {cid: talk.id for cid, talk in talks.items()}

        async with AsyncSessionLocal() as db:
            result = await reminders.run_once(db)
    assert result["status"] == "done", result

    today = date(2026, 10, 17)
    assert await _open_due(imported, today) == []
    assert await _open_due(planned, today) == []
    async with AsyncSessionLocal() as db:
        closed = (
            await db.scalars(
                select(CarePlanItem).where(
                    CarePlanItem.contract_id == planned,
                    CarePlanItem.due_on == date(2026, 10, 1),
                )
            )
        ).one()
    assert closed.status == "done"
    assert closed.done_conversation_id == talk_ids[planned]
    assert closed.resolved_by is None
    async with AsyncSessionLocal() as db:
        traces = (
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_type == "contract",
                    HrAuditEvent.entity_id.in_([str(imported), str(planned)]),
                    HrAuditEvent.action == "care.plan_covered",
                )
            )
        ).all()
    assert [(t.entity_id, t.actor_user_id, t.details) for t in traces] == [
        (
            str(planned),
            None,
            {"plan_item_ids": [closed.id], "conversation_ids": [talk_ids[planned]]},
        )
    ]
    assert await _reminders_for(imported) == []
    assert await _reminders_for(planned) == []
    # Bez żadnej rozmowy zaległość jest prawdziwą informacją.
    assert [item.due_on for item in await _open_due(silent, today)] == [
        date(2026, 10, 1)
    ]
    assert [n.user_id for n in await _reminders_for(silent)] == [owner.id]


def _care_contract(contract_id: int, owner_id: int) -> care_access.CareContract:
    return care_access.CareContract(
        id=contract_id,
        client_id=1,
        client_name="Klient Przykładowy",
        candidate_id=contract_id,
        candidate_name=f"Osoba {contract_id}",
        job_id=None,
        job_title=None,
        job_delivery_lead_id=None,
        status="active",
        start_date=date(2026, 9, 1),
        contract_end_date=None,
        order_end_date=None,
        explicit_owner_id=owner_id,
        client_default_owner_id=None,
    )


async def test_owner_with_many_due_contracts_gets_one_bell(monkeypatch) -> None:
    """Pierwszy przebieg 18.10.2026 dał 472 dzwonki (jednemu DL 290) — po
    jednym na kontrakt. Opiekun z wieloma zaległymi dostaje jeden zbiorczy."""

    today = date(2026, 10, 19)
    many = [_care_contract(cid, 27) for cid in range(1, 41)]
    single = _care_contract(99, 30)
    calls: list[dict] = []

    async def fake_due(db, ids, day):
        return {}

    async def fake_latest(db, ids):
        return {}

    def fake_next(items, latest, day):
        return care_plan.NextContact(kind="cadence", due_on=date(2026, 10, 1))

    async def fake_none(db, ids, now):
        return set()

    async def fake_owners(db, contracts):
        return {
            c.id: care_access.OwnerChoice(c.explicit_owner_id, "contract")
            for c in contracts
        }

    async def fake_notify(db, user_ids, **kwargs):
        calls.append({"users": list(user_ids), **kwargs})
        return 1

    monkeypatch.setattr(reminders, "_due_items", fake_due)
    monkeypatch.setattr(care_plan, "latest_conversations", fake_latest)
    monkeypatch.setattr(care_plan, "next_contact", fake_next)
    monkeypatch.setattr(reminders, "_recently_reminded", fake_none)
    monkeypatch.setattr(reminders, "_recent_digests", fake_none, raising=False)
    monkeypatch.setattr(care_access, "effective_owners", fake_owners)
    monkeypatch.setattr(reminders, "notify_each", fake_notify)

    result = await reminders.remind(
        None, [*many, single], today=today, now=AFTER_WARSAW_MIDNIGHT
    )

    by_user = {call["users"][0]: call for call in calls}
    assert len(calls) == 2
    digest = by_user[27]
    assert digest["related_entity_type"] == reminders.DIGEST_ENTITY
    assert digest["related_entity_id"] == 27
    assert digest["link"] == "/care?filter=po-terminie"  # najstarszy 01.10 < dziś
    assert digest["message"].startswith("Do zrobienia: 40 — Osoba 1")
    assert "i 37 inne" in digest["message"]
    assert "01.10" in digest["message"]
    assert by_user[30]["related_entity_id"] == 99  # jeden kontrakt — jak dotąd
    assert (result["sent"], result["digests"], result["skipped"]) == (41, 1, 0)


async def test_digest_waits_seven_days_unless_something_is_due_today(
    monkeypatch,
) -> None:
    today = date(2026, 10, 20)
    items = [_care_contract(cid, 27) for cid in (1, 2)]
    due = {1: date(2026, 10, 1), 2: date(2026, 10, 2)}
    calls: list[int] = []

    async def fake_due(db, ids, day):
        return {}

    async def fake_latest(db, ids):
        return {}

    async def fake_none(db, ids, now):
        return set()

    async def fake_digested(db, ids, now):
        return {27}

    async def fake_owners(db, contracts):
        return {c.id: care_access.OwnerChoice(27, "contract") for c in contracts}

    async def fake_notify(db, user_ids, **kwargs):
        calls.append(kwargs["related_entity_id"])
        return 1

    monkeypatch.setattr(reminders, "_due_items", fake_due)
    monkeypatch.setattr(care_plan, "latest_conversations", fake_latest)
    monkeypatch.setattr(reminders, "_recently_reminded", fake_none)
    monkeypatch.setattr(reminders, "_recent_digests", fake_digested)
    monkeypatch.setattr(care_access, "effective_owners", fake_owners)
    monkeypatch.setattr(reminders, "notify_each", fake_notify)

    def next_for(contract_id):
        return care_plan.NextContact(kind="cadence", due_on=due[contract_id])

    # next_contact dostaje punkt planu, nie id — podstawiamy po kolejności.
    order = iter([1, 2])
    monkeypatch.setattr(
        care_plan, "next_contact", lambda items_, latest, day: next_for(next(order))
    )
    quiet = await reminders.remind(None, items, today=today, now=AFTER_WARSAW_MIDNIGHT)
    assert calls == [] and quiet["skipped"] == 2

    due[2] = today
    order = iter([1, 2])
    monkeypatch.setattr(
        care_plan, "next_contact", lambda items_, latest, day: next_for(next(order))
    )
    rung = await reminders.remind(None, items, today=today, now=AFTER_WARSAW_MIDNIGHT)
    assert calls == [27] and rung["digests"] == 1


def test_digest_link_filters_overdue_or_this_week() -> None:
    today = date(2026, 10, 20)
    items = [_care_contract(cid, 27) for cid in (1, 2)]
    overdue = {
        1: care_plan.NextContact(kind="cadence", due_on=date(2026, 10, 19)),
        2: care_plan.NextContact(kind="cadence", due_on=today),
    }
    assert reminders.digest_link(items, overdue, today) == "/care?filter=po-terminie"
    only_today = {
        cid: care_plan.NextContact(kind="cadence", due_on=today) for cid in (1, 2)
    }
    assert reminders.digest_link(items, only_today, today) == "/care?filter=do-piatku"
    assert reminders.contract_link(5) == "/care?contract=5"
