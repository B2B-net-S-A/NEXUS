"""Wejście i odejście — poprawki po przeglądzie 16.10.2026 (C11–C13, C15, C16).

* C11 — konto nie wyłącza się, dopóki praca nie przeszła (chyba że Kadry
  wyłączą je jawnie „mimo to”); przekazanie widzi rekrutacje osoby, której konto
  już wyłączono, a wiersz po niepowodzeniu nie przechodzi w „przekazano 0”
  od samego ponownego policzenia,
* C12 — odmowa przy masowym odejściu to nieudany przebieg (sonda ``hr_jobs``)
  i dzwonek do Kadr i adminów, raz dziennie,
* C13 — przejmujący nie może sam odchodzić; odejścia z nieprzekazaną pracą nie
  da się zamknąć; zmiana przełożonego przestawia domyślnych przejmujących,
* C15 — „Cofnij odejście” zamyka sprawę administracja@ i zadanie zwrotu
  sprzętu; unieważniony kontrakt zamyka sprawę „Wejście konsultanta”
  i zadanie „Przygotuj zestaw”,
* C16 — zapis szablonu nie odpina zadań: przeliczenie terminów nie dubluje
  zadań i nie otwiera zrobionych.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.admin_case import AdminCase, AdminCaseComment
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentItem,
    EquipmentModel,
    EquipmentTask,
)
from app.models.hr_lifecycle import (
    LifecycleCase,
    LifecycleTask,
    LifecycleTemplateItem,
    WorkHandover,
)
from app.models.hr_ops import HrJobRun
from app.models.hr_profile import EmployeeProfile
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.notification import Notification, NotificationType
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr import health
from app.services.hr import lifecycle_service as service
from app.services.hr.deactivation import MAX_DEACTIVATIONS_PER_RUN
from app.services.hr.handover import eligible_receivers
from app.services.hr.lifecycle_jobs import run_once
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

WARSAW = ZoneInfo("Europe/Warsaw")
BASE = "/api/hr/lifecycle"


# ── Świat testu ──────────────────────────────────────────────────────────────


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


@pytest_asyncio.fixture
async def modules_on():
    """Moduły włączone, czysta karta pętli (wspólna baza — pętla bierze wszystko).

    Po teście żywe sprawy też idą do kosza: pętla w testach innych plików
    (np. import z Compassa) bierze każdą sprawę w toku.
    """

    async def clean_slate() -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM hr_job_runs WHERE kind LIKE 'hr_lifecycle%'")
            )
            await db.execute(
                text(
                    "UPDATE lifecycle_cases SET status = 'cancelled' "
                    "WHERE status IN ('draft', 'active') AND user_id IS NOT NULL"
                )
            )
            await db.commit()

    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await clean_slate()
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await clean_slate()
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _last_day() -> date:
    day = business_today() + timedelta(days=9)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WARSAW)


def _headers(user_id: int, role: str) -> dict[str, str]:
    token = create_access_token(subject=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def _person(db, tag: str, label: str, roles: list[str]) -> User:
    user = User(
        email=f"review-lc-{label}-{tag}@example.com",
        name=f"Osoba {label} {tag}",
        role=UserRole(roles[0]),
        roles=roles,
        is_active=True,
        profile_completed=True,
    )
    db.add(user)
    return user


async def _world(
    *, start: bool = True, equipment: bool = False, last_day: date | None = None
) -> dict:
    """Kadry, przełożony (rekruter i DL) i odchodząca rekruterka z rekrutacją."""

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        hr = _person(db, tag, "kadry", ["recruiter"])
        boss = _person(db, tag, "szef", ["delivery_lead", "recruiter"])
        leaver = _person(db, tag, "odchodzi", ["recruiter"])
        client = Client(name=f"Klient Przykładowy {tag}")
        db.add(client)
        await db.flush()
        db.add(
            UserActionOverride(user_id=hr.id, action="people_admin", access="manage")
        )
        db.add_all(
            [
                EmployeeProfile(user_id=boss.id),
                EmployeeProfile(user_id=leaver.id, manager_user_id=boss.id),
            ]
        )
        job = Job(
            title=f"Rekrutacja prowadzona {tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=leaver.id,
        )
        db.add(job)
        if equipment:
            model = EquipmentModel(category="laptop", name=f"Laptop Przykładowy {tag}")
            db.add(model)
            await db.flush()
            item = EquipmentItem(
                model_id=model.id, serial_number=f"REVIEW{tag}", status="wydany"
            )
            db.add(item)
            await db.flush()
            db.add(EquipmentAssignment(item_id=item.id, user_id=leaver.id))
        await db.commit()
        case = await service.create_offboarding(
            db,
            actor=hr,
            user_id=leaver.id,
            last_working_day=last_day or _last_day(),
            exit_initiator="employee",
            exit_reason="career_growth",
            exit_note=None,
            manager_user_id=None,
            manager_given=False,
            template_id=None,
        )
        if start:
            await service.start_case(db, case, actor=hr)
        await db.commit()
        return {
            "hr": hr.id,
            "boss": boss.id,
            "leaver": leaver.id,
            "job": job.id,
            "case": case.id,
            "last_day": case.last_working_day,
            "deactivate_on": case.deactivate_on,
        }


async def _run(now: datetime) -> dict:
    async with AsyncSessionLocal() as db:
        return await run_once(db, now=now)


async def _rows(db, case_id: int) -> dict[str, WorkHandover]:
    return {
        row.work_kind: row
        for row in await db.scalars(
            select(WorkHandover)
            .where(WorkHandover.case_id == case_id)
            .execution_options(populate_existing=True)
        )
    }


async def _set_receiver_raw(case_id: int, kind: str, receiver_id: int | None) -> None:
    """Przejmujący wpisany bez walidacji (stan sprzed zmiany u przejmującego)."""

    async with AsyncSessionLocal() as db:
        row = (await _rows(db, case_id))[kind]
        row.receiver_user_id = receiver_id
        await db.commit()


async def _deactivate(user_id: int) -> None:
    """Admin wyłącza konto w Ustawieniach → Użytkownicy (poza sprawą odejścia)."""

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.is_active = False
        await db.commit()


async def _boss_took_the_job(db, world: dict) -> bool:
    job = await db.get(Job, world["job"], populate_existing=True)
    link = await db.scalar(
        select(JobCollaborator).where(
            JobCollaborator.job_id == world["job"],
            JobCollaborator.user_id == world["boss"],
        )
    )
    return job.recruiter_id != world["leaver"] and link is not None


# ── C11: wyłączenie konta czeka na przekazanie pracy ─────────────────────────


@pytest.mark.asyncio
async def test_account_waits_until_the_work_is_handed_over(modules_on) -> None:
    world = await _world()
    await _set_receiver_raw(world["case"], "recruitments", None)

    failed = await _run(_at(world["last_day"], 18, 10))
    assert failed["handover_failed"] == 1

    waiting = await _run(_at(world["deactivate_on"], 0, 5))
    assert waiting.get("account_deactivated", 0) == 0
    assert waiting["deactivation_waiting_handover"] == 1
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, world["leaver"])).is_active is True
        case = await db.get(LifecycleCase, world["case"])
        assert case.account_closed_at is None

    # Kadry wskazują przejmującego → praca przechodzi, potem konto się wyłącza.
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, world["case"])
        hr = await db.get(User, world["hr"])
        await service.set_receivers(
            db, case, actor=hr, receivers={"recruitments": world["boss"]}
        )
        await db.commit()
    done = await _run(_at(world["deactivate_on"], 0, 20))
    assert done["account_deactivated"] == 1
    async with AsyncSessionLocal() as db:
        assert (
            await db.get(User, world["leaver"], populate_existing=True)
        ).is_active is False
        assert await _boss_took_the_job(db, world)


@pytest.mark.asyncio
async def test_handover_moves_recruitments_of_an_account_closed_elsewhere(
    modules_on,
) -> None:
    world = await _world()
    await _deactivate(world["leaver"])

    await _run(_at(world["last_day"], 18, 5))
    async with AsyncSessionLocal() as db:
        row = (await _rows(db, world["case"]))["recruitments"]
        assert row.status == "done"
        assert row.result == {"jobs": 1}, (
            "rekrutacja nie może zostać przy wyłączonym koncie"
        )
        assert await _boss_took_the_job(db, world)


@pytest.mark.asyncio
async def test_failed_row_does_not_turn_into_done_after_the_account_is_closed(
    modules_on,
) -> None:
    world = await _world()
    await _set_receiver_raw(world["case"], "recruitments", None)
    await _run(_at(world["last_day"], 18, 10))
    await _deactivate(world["leaver"])

    await _run(_at(world["last_day"], 18, 25))
    async with AsyncSessionLocal() as db:
        row = (await _rows(db, world["case"]))["recruitments"]
        assert row.status == "failed" and row.error == "no_receiver"
        assert row.item_count == 1
        case = await db.get(LifecycleCase, world["case"])
        assert case.handover_executed_at is None
        assert (await db.get(Job, world["job"])).recruiter_id == world["leaver"]


@pytest.mark.asyncio
async def test_deactivate_now_needs_finished_handover_or_an_explicit_override(
    app_client, modules_on
) -> None:
    world = await _world()
    await _set_receiver_raw(world["case"], "recruitments", None)
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, world["case"])
        case.last_working_day = business_today() - timedelta(days=1)
        case.deactivate_on = business_today()
        await db.commit()
    headers = _headers(world["hr"], "recruiter")
    url = f"{BASE}/cases/{world['case']}"

    refused = await app_client.post(f"{url}/deactivate-now", headers=headers)
    assert refused.status_code == 409, refused.text
    assert "rekrutacje" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, world["leaver"])).is_active is True

    forced = await app_client.post(
        f"{url}/deactivate-now?despite_handover=true", headers=headers
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["account_close_result"] == "deactivated"
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, world["leaver"])).is_active is False
        audit_rows = await db.scalar(
            text(
                "SELECT count(*) FROM hr_audit_events WHERE entity_type = 'lifecycle_case' "
                "AND entity_id = :id AND action = 'account_closed_despite_handover'"
            ),
            {"id": str(world["case"])},
        )
        assert audit_rows == 1

    # C13: odejścia z nieprzekazaną pracą nie da się zamknąć.
    blocked = await app_client.post(f"{url}/complete", headers=headers)
    assert blocked.status_code == 409
    assert "rekrutacje" in blocked.json()["detail"]

    # Przejmujący wskazany po wyłączeniu konta: pętla naprawdę przenosi pracę.
    chosen = await app_client.put(
        f"{url}/handovers",
        json={"receivers": {"recruitments": world["boss"]}},
        headers=headers,
    )
    assert chosen.status_code == 200, chosen.text
    await _run(_at(business_today(), 23, 0))
    async with AsyncSessionLocal() as db:
        row = (await _rows(db, world["case"]))["recruitments"]
        assert row.status == "done" and row.result == {"jobs": 1}
        assert await _boss_took_the_job(db, world)
    closed = await app_client.post(f"{url}/complete", headers=headers)
    assert closed.status_code == 200, closed.text


# ── C12: masowe odejście = nieudany przebieg + dzwonek ───────────────────────


@pytest.mark.asyncio
async def test_mass_exit_is_a_failed_run_and_rings_hr_and_admins_once_a_day(
    modules_on, monkeypatch
) -> None:
    worlds = [await _world() for _ in range(MAX_DEACTIVATIONS_PER_RUN + 1)]
    async with AsyncSessionLocal() as db:
        admin = _person(db, uuid.uuid4().hex[:8], "admin", ["admin"])
        await db.commit()
        admin_id = admin.id
    hr_id = worlds[0]["hr"]
    deactivate_on = worlds[0]["deactivate_on"]

    result = await _run(_at(deactivate_on, 1, 0))
    assert result["deactivation_error"] == "mass_exit_suspected"
    async with AsyncSessionLocal() as db:
        run = await db.scalar(
            select(HrJobRun)
            .where(HrJobRun.kind == "hr_lifecycle")
            .order_by(HrJobRun.id.desc())
            .limit(1)
        )
        assert run.status == "failed"
        assert run.error == "mass_exit_suspected"
        run_id = run.id
        for user_id in (hr_id, admin_id):
            bells = await db.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user_id,
                    Notification.notification_type
                    == NotificationType.hr_lifecycle_task,
                    Notification.title.like("Wyłączenie kont wstrzymane%"),
                )
            )
            assert bells == 1, user_id

    again = await _run(_at(deactivate_on, 1, 15))
    assert again["deactivation_error"] == "mass_exit_suspected"
    async with AsyncSessionLocal() as db:
        bells = await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == hr_id,
                Notification.title.like("Wyłączenie kont wstrzymane%"),
            )
        )
        assert bells == 1, "dzwonek raz dziennie, nie co kwadrans"

    # Sonda `hr_jobs` widzi ten przebieg (bez cudzych wierszy).
    monkeypatch.setattr(settings, "HR_LOOPS_ENABLED", True)
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(delete(HrJobRun).where(HrJobRun.id != run_id))
            assert await health.hr_jobs_state(db) == "degraded"
            await db.execute(
                text("UPDATE hr_job_runs SET status = 'done' WHERE id = :id"),
                {"id": run_id},
            )
            assert await health.hr_jobs_state(db) == "healthy"
        finally:
            await db.rollback()


# ── C13: przejmujący nie odchodzi, przełożony = domyślny przejmujący ─────────


@pytest.mark.asyncio
async def test_receiver_who_is_leaving_is_refused_and_not_offered(
    app_client, modules_on
) -> None:
    first = await _world()
    other = await _world()  # ta osoba odchodzi tego samego dnia
    headers = _headers(first["hr"], "recruiter")

    refused = await app_client.put(
        f"{BASE}/cases/{first['case']}/handovers",
        json={"receivers": {"recruitments": other["leaver"]}},
        headers=headers,
    )
    assert refused.status_code == 422
    assert "odchodzi" in refused.json()["detail"]

    listed = await app_client.get(
        f"{BASE}/cases/{first['case']}/receivers?kind=recruitments", headers=headers
    )
    assert listed.status_code == 200
    offered = {item["user_id"] for item in listed.json()["items"]}
    assert other["leaver"] not in offered
    assert first["boss"] in offered
    async with AsyncSessionLocal() as db:
        ids = {
            item["user_id"]
            for item in await eligible_receivers(
                db,
                "recruitments",
                leaver_id=first["leaver"],
                handover_day=first["last_day"],
            )
        }
        assert other["leaver"] not in ids

    # Przejmujący wybrany, zanim ruszyło jego własne odejście → przekazanie
    # do niego się nie wykona.
    await _set_receiver_raw(first["case"], "recruitments", other["leaver"])
    await _run(_at(first["last_day"], 18, 5))
    async with AsyncSessionLocal() as db:
        row = (await _rows(db, first["case"]))["recruitments"]
        assert row.status == "failed" and row.error == "receiver_leaving"


@pytest.mark.asyncio
async def test_manager_change_moves_default_receivers_until_handover_starts(
    modules_on,
) -> None:
    world = await _world(start=False)
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        new_boss = _person(db, tag, "nowy-szef", ["delivery_lead", "recruiter"])
        chosen = _person(db, tag, "wybrana", ["recruiter"])
        await db.commit()
        case = await db.get(LifecycleCase, world["case"])
        hr = await db.get(User, world["hr"])
        await service.set_receivers(
            db, case, actor=hr, receivers={"my_people": chosen.id}
        )
        await service.update_case(
            db, case, actor=hr, values={"manager_user_id": new_boss.id}
        )
        await db.commit()
        rows = await _rows(db, world["case"])
        assert rows["recruitments"].receiver_user_id == new_boss.id
        assert rows["delivery_lead_jobs"].receiver_user_id == new_boss.id
        assert rows["dl_clients"].receiver_user_id == new_boss.id
        assert rows["my_people"].receiver_user_id == chosen.id, "wybór Kadr zostaje"


# ── C15: cofnięcie odejścia i unieważniony kontrakt sprzątają po sobie ───────


@pytest.mark.asyncio
async def test_cancelled_offboarding_closes_admin_case_and_return_task(
    modules_on,
) -> None:
    world = await _world(equipment=True)
    exit_key = f"user:{world['leaver']}:exit"
    case_key = f"lifecycle:{world['case']}:offboarding"
    async with AsyncSessionLocal() as db:
        task = await db.scalar(
            select(EquipmentTask).where(EquipmentTask.source_key == exit_key)
        )
        admin_case = await db.scalar(
            select(AdminCase).where(AdminCase.source_key == case_key)
        )
        assert task is not None and task.status == "otwarte"
        assert admin_case is not None and admin_case.status == "new"

    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, world["case"])
        hr = await db.get(User, world["hr"])
        await service.cancel_case(db, case, actor=hr)
        await db.commit()
    async with AsyncSessionLocal() as db:
        task = await db.scalar(
            select(EquipmentTask).where(EquipmentTask.source_key == exit_key)
        )
        assert task.status == "anulowane"
        admin_case = await db.scalar(
            select(AdminCase).where(AdminCase.source_key == case_key)
        )
        assert admin_case.status == "closed" and admin_case.closed_at is not None
        note = await db.scalar(
            select(AdminCaseComment.body).where(
                AdminCaseComment.case_id == admin_case.id
            )
        )
        assert note and "cofnięte" in note

    # Nowe odejście tej samej osoby: zadanie zwrotu wraca jako otwarte.
    async with AsyncSessionLocal() as db:
        hr = await db.get(User, world["hr"])
        again = await service.create_offboarding(
            db,
            actor=hr,
            user_id=world["leaver"],
            last_working_day=_last_day(),
            exit_initiator="employee",
            exit_reason="career_growth",
            exit_note=None,
            manager_user_id=None,
            manager_given=False,
            template_id=None,
        )
        await service.start_case(db, again, actor=hr)
        await db.commit()
    async with AsyncSessionLocal() as db:
        task = await db.scalar(
            select(EquipmentTask).where(EquipmentTask.source_key == exit_key)
        )
        assert task.status == "otwarte"


@pytest.mark.asyncio
async def test_cancelled_onboarding_cancels_the_office_kit_task(modules_on) -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        hr = _person(db, tag, "kadry", ["recruiter"])
        newcomer = _person(db, tag, "nowa", ["recruiter"])
        await db.flush()
        db.add(
            UserActionOverride(user_id=hr.id, action="people_admin", access="manage")
        )
        await db.commit()
        case = await service.create_onboarding(
            db,
            actor=hr,
            user_id=newcomer.id,
            email=None,
            name=None,
            start_date=_last_day(),
            template_id=None,
            manager_user_id=None,
            profile_values={"employment_type": "uop"},
        )
        await service.start_case(db, case, actor=hr)
        await db.commit()
        start_key = f"user:{newcomer.id}:start"
        task = await db.scalar(
            select(EquipmentTask).where(EquipmentTask.source_key == start_key)
        )
        assert task is not None and task.status == "otwarte"
        await service.cancel_case(db, case, actor=hr)
        await db.commit()
        task = await db.scalar(
            select(EquipmentTask)
            .where(EquipmentTask.source_key == start_key)
            .execution_options(populate_existing=True)
        )
        assert task.status == "anulowane"


async def _draft_contract(start: date) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Jan", lastname=f"Testowy-{tag}", email=f"review-c-{tag}@example.com"
        )
        client = Client(name=f"Klient Fikcyjny {tag}")
        db.add_all([candidate, client])
        await db.flush()
        await db.execute(
            text("UPDATE clients SET equipment_provider = 'nasz' WHERE id = :id"),
            {"id": client.id},
        )
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.draft,
            contract_type=ContractType("b2b"),
            start_date=start,
            rate_client=100,
            rate_candidate=80,
            margin=20,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return {"id": contract.id, "client_id": client.id, "candidate_id": candidate.id}


async def _drop(ids: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(EquipmentTask).where(EquipmentTask.contract_id == ids["id"])
        )
        await db.execute(delete(AdminCase).where(AdminCase.contract_id == ids["id"]))
        await db.execute(delete(Contract).where(Contract.id == ids["id"]))
        await db.execute(delete(Candidate).where(Candidate.id == ids["candidate_id"]))
        await db.execute(delete(Client).where(Client.id == ids["client_id"]))
        await db.commit()


async def _start_links(db, contract_id: int) -> tuple[str, str]:
    task = await db.scalar(
        select(EquipmentTask.status).where(
            EquipmentTask.source_key == f"contract:{contract_id}:start"
        )
    )
    case = await db.scalar(
        select(AdminCase.status).where(
            AdminCase.source_key == f"contract:{contract_id}:start"
        )
    )
    return task, case


@pytest.mark.asyncio
async def test_voided_draft_contract_closes_onboarding_case_and_kit_task(
    modules_on,
) -> None:
    from app.services.contract_lifecycle import void_contract
    from app.services.hr import contract_hooks

    hooked = await _draft_contract(business_today() + timedelta(days=10))
    healed = await _draft_contract(business_today() + timedelta(days=11))
    try:
        async with AsyncSessionLocal() as db:
            await contract_hooks.reconcile_upcoming(db)
            await db.commit()
            assert await _start_links(db, hooked["id"]) == ("otwarte", "new")
            assert await _start_links(db, healed["id"]) == ("otwarte", "new")

        # Ścieżka główna: „Anuluj kontrakt”.
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, hooked["id"])
            await void_contract(db, contract, actor_id=None, reason="test")
            await db.commit()
        # Unieważnienie bez haka (np. hak padł) naprawia przegląd.
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE contracts SET status = 'void' WHERE id = :id"),
                {"id": healed["id"]},
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert await _start_links(db, hooked["id"]) == ("anulowane", "closed")
            await contract_hooks.reconcile_upcoming(db)
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert await _start_links(db, hooked["id"]) == ("anulowane", "closed")
            assert await _start_links(db, healed["id"]) == ("anulowane", "closed")
    finally:
        await _drop(hooked)
        await _drop(healed)


# ── C16: zapis szablonu nie odpina zadań ─────────────────────────────────────


@pytest.mark.asyncio
async def test_template_save_keeps_tasks_linked_and_replan_neither_duplicates_nor_reopens(
    modules_on,
) -> None:
    world = await _world(start=False)
    # Własny dział: aktywny szablon nie może trafić do spraw innych testów.
    department = f"Dział testowy {uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        hr = await db.get(User, world["hr"])
        template = await service.save_template(
            db,
            actor=hr,
            template_id=None,
            kind="offboarding",
            name=f"Odejście — test {uuid.uuid4().hex[:6]}",
            is_active=True,
            employment_type=None,
            department=department,
            items=[
                service.ItemInput("Odbierz laptop", "equipment", "reception", -1),
                service.ItemInput("Rozmowa końcowa", "meeting", "manager", 0),
            ],
        )
        await db.commit()
        items = await service.template_items(db, template.id)
        first_id, second_id = items[0].id, items[1].id
        case = await db.get(LifecycleCase, world["case"])
        await service.update_case(
            db, case, actor=hr, values={"template_id": template.id}
        )
        await db.commit()
        tasks = await service.case_tasks(db, case.id)
        laptop = next(t for t in tasks if t.template_item_id == first_id)
        await service.update_task(
            db, laptop, case, actor=hr, status="done", note=None, note_given=False
        )
        talk = next(t for t in tasks if t.template_item_id == second_id)
        await service.update_task(
            db,
            talk,
            case,
            actor=hr,
            status=None,
            note="Termin z kalendarza",
            note_given=True,
        )
        await db.commit()
        talk_id = talk.id

        # Edycja szablonu: pozycje z id (nowy front) i bez id (stary front).
        await service.save_template(
            db,
            actor=hr,
            template_id=template.id,
            kind="offboarding",
            name=template.name,
            is_active=True,
            employment_type=None,
            department=department,
            items=[
                service.ItemInput("Odbierz laptop", "equipment", "reception", -1),
                service.ItemInput(
                    "Rozmowa końcowa z przełożonym",
                    "meeting",
                    "manager",
                    0,
                    id=second_id,
                ),
                service.ItemInput("Zamknij dostęp do budynku", "accounts", "it", 0),
            ],
        )
        await db.commit()
        kept = {item.id for item in await service.template_items(db, template.id)}
        assert {first_id, second_id} <= kept

        # Przeliczenie terminów (zmiana ostatniego dnia).
        case = await db.get(LifecycleCase, world["case"])
        await service.update_case(
            db,
            case,
            actor=hr,
            values={"last_working_day": world["last_day"] + timedelta(days=7)},
        )
        await db.commit()
        tasks = await service.case_tasks(db, case.id)
        by_item: dict[int | None, list[LifecycleTask]] = {}
        for task in tasks:
            by_item.setdefault(task.template_item_id, []).append(task)
        assert [t.status for t in by_item[first_id]] == ["done"], "zrobione nie wraca"
        assert len(by_item[second_id]) == 1
        talk = by_item[second_id][0]
        assert talk.id == talk_id and talk.note == "Termin z kalendarza"
        assert talk.title == "Rozmowa końcowa z przełożonym"
        assert talk.due_date == world["last_day"] + timedelta(days=7)
        assert len(tasks) == 3

        # Pozycja usunięta z szablonu: jej zadanie zostaje i się nie dubluje.
        await service.save_template(
            db,
            actor=hr,
            template_id=template.id,
            kind="offboarding",
            name=template.name,
            is_active=True,
            employment_type=None,
            department=department,
            items=[
                service.ItemInput(
                    "Odbierz laptop", "equipment", "reception", -1, id=first_id
                ),
            ],
        )
        await db.commit()
        case = await db.get(LifecycleCase, world["case"])
        await service.update_case(
            db,
            case,
            actor=hr,
            values={"last_working_day": world["last_day"] + timedelta(days=8)},
        )
        await db.commit()
        tasks = await service.case_tasks(db, case.id)
        assert len(tasks) == 3
        assert sum(1 for t in tasks if t.template_item_id == first_id) == 1
        remaining = await db.scalar(
            select(func.count(LifecycleTemplateItem.id)).where(
                LifecycleTemplateItem.template_id == template.id
            )
        )
        assert remaining == 1


@pytest.mark.asyncio
async def test_template_item_from_another_template_is_refused(modules_on) -> None:
    world = await _world(start=False)
    async with AsyncSessionLocal() as db:
        hr = await db.get(User, world["hr"])
        one = await service.save_template(
            db,
            actor=hr,
            template_id=None,
            kind="offboarding",
            name=f"Szablon A {uuid.uuid4().hex[:6]}",
            is_active=False,
            employment_type=None,
            department=None,
            items=[service.ItemInput("Zadanie A", "other", "people_admin", 0)],
        )
        two = await service.save_template(
            db,
            actor=hr,
            template_id=None,
            kind="offboarding",
            name=f"Szablon B {uuid.uuid4().hex[:6]}",
            is_active=False,
            employment_type=None,
            department=None,
            items=[service.ItemInput("Zadanie B", "other", "people_admin", 0)],
        )
        await db.commit()
        foreign = (await service.template_items(db, one.id))[0].id
        with pytest.raises(service.LifecycleError):
            await service.save_template(
                db,
                actor=hr,
                template_id=two.id,
                kind="offboarding",
                name=two.name,
                is_active=False,
                employment_type=None,
                department=None,
                items=[
                    service.ItemInput(
                        "Zadanie A", "other", "people_admin", 0, id=foreign
                    )
                ],
            )
        await db.rollback()
