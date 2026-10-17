"""Wejście konsultanta — jedna lista przy kontrakcie (etap 3, O1, O5, O6, M6).

Lista składa się ze ścieżki „Konsultant u klienta” (pozycje z warunkami formy
i sprzętu), pakietu klienta i formy; zakłada ją hak startu kontraktu raz,
sprawa administracja@ bierze z niej checklistę, zestaw sprzętu to zadanie
recepcji (lustro, bez dubla), stare pozycje onboardingu są tylko do odczytu.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase
from app.models.app_setting import AppSetting
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_onboarding import ContractOnboardingItem
from app.models.equipment import EquipmentTask
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask
from app.models.team_structure import DeliveryLeadClientAssignment
from app.services.hr import client_pack, contract_hooks, lifecycle_service
from app.services.hr.calendar import load_calendar
from app.services.hr.lifecycle_dates import calendar_window, shift_working_days
from app.services.hr_foundation_schema import HR_DIVISIONS_SETTING
from tests.test_equipment_api import _contract, _drop_contract, modules_on  # noqa: F401
from tests.test_hr_lifecycle_api import _grant, _headers, _user

BASE = "/api/hr/lifecycle"


@dataclass(frozen=True)
class _Item:
    name: str
    note: str | None = None


@dataclass(frozen=True)
class _Pack:
    equipment_ours: tuple[_Item, ...]


PACK = [
    client_pack.PackTask(
        title="Zaświadczenie o niekaralności",
        description="Nie starsze niż 3 miesiące.",
        assignee="care_owner",
        offset_days=-1,
        required=True,
        requires_file=True,
        category="documents",
    ),
    client_pack.PackTask(
        title="Konto i VPN u klienta",
        description=None,
        assignee="delivery_lead",
        offset_days=-8,
        required=True,
        requires_file=False,
        category="accounts",
    ),
]


@pytest.fixture
def pack(monkeypatch):
    async def tasks(db, client_id):
        return list(PACK)

    async def load(db, client_id):
        return _Pack((_Item("laptop 14 cali"), _Item("słuchawki")))

    monkeypatch.setattr(client_pack, "pack_tasks", tasks)
    monkeypatch.setattr(client_pack, "load_pack", load)


@pytest_asyncio.fixture
async def back_office_head():
    async with AsyncSessionLocal() as db:
        head = await _user(db, "talent_community_manager")
        row = await db.get(AppSetting, HR_DIVISIONS_SETTING)
        previous = row.value if row is not None else None
        if row is None:
            db.add(AppSetting(key=HR_DIVISIONS_SETTING, value={"back_office": head.id}))
        else:
            row.value = {**(row.value or {}), "back_office": head.id}
        await db.commit()
    yield head
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_DIVISIONS_SETTING)
        if previous is None:
            await db.delete(row)
        else:
            row.value = previous
        await db.commit()


def _future_weekday(days: int):
    day = business_today() + timedelta(days=days)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


async def _world(*, provider: str = "nasz", form: str = "b2b") -> dict:
    start = _future_weekday(28)
    ids = await _contract(start=start, end=None, provider=provider)
    async with AsyncSessionLocal() as db:
        owner = await _user(db, "talent_community_manager")
        lead = await _user(db, "delivery_lead")
        other_lead = await _user(db, "delivery_lead")
        reception = await _user(db, "recruiter")
        await _grant(db, reception, "equipment")
        office = await _user(db, "recruiter")
        await _grant(db, office, "cases")
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=lead.id, client_id=ids["client_id"], is_head=True
            )
        )
        await db.execute(
            text(
                "UPDATE contracts SET care_owner_user_id = :u, contract_type = :t WHERE id = :id"
            ),
            {"u": owner.id, "t": form, "id": ids["id"]},
        )
        await db.commit()
    return {
        **ids,
        "start": start,
        "owner": owner,
        "lead": lead,
        "other_lead": other_lead,
        "reception": reception,
        "office": office,
    }


async def _cleanup(ids: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(LifecycleCase).where(LifecycleCase.contract_id == ids["id"])
        )
        await db.execute(
            delete(EquipmentTask).where(EquipmentTask.contract_id == ids["id"])
        )
        await db.execute(delete(AdminCase).where(AdminCase.contract_id == ids["id"]))
        await db.execute(
            delete(ContractOnboardingItem).where(
                ContractOnboardingItem.contract_id == ids["id"]
            )
        )
        await db.commit()
    await _drop_contract(ids)


async def _start(contract_id: int) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        outcome = await contract_hooks.contract_started(db, contract)
        await db.commit()
    assert outcome["lifecycle"] == "ok", outcome


async def _tasks(contract_id: int) -> list[LifecycleTask]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(LifecycleTask)
                .join(LifecycleCase, LifecycleCase.id == LifecycleTask.case_id)
                .where(LifecycleCase.contract_id == contract_id)
                .order_by(LifecycleTask.id)
            )
        )


async def _due(start, offset: int):
    async with AsyncSessionLocal() as db:
        first, last = calendar_window(start)
        calendar = await load_calendar(db, first, last)
    return shift_working_days(calendar, start, offset)


# ── Składanie listy ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contract_start_builds_one_list_from_path_pack_and_form(
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world()
    try:
        await _start(world["id"])
        await _start(world["id"])  # drugi przebieg niczego nie dubluje
        async with AsyncSessionLocal() as db:
            cases = list(
                await db.scalars(
                    select(LifecycleCase).where(
                        LifecycleCase.contract_id == world["id"]
                    )
                )
            )
        assert len(cases) == 1
        case = cases[0]
        assert case.audience == "consultant" and case.user_id is None
        assert case.status == "active" and case.template_version == 1
        assert case.pending_name.startswith("Jan Testowy")
        tasks = {task.title: task for task in await _tasks(world["id"])}
        # B2B: umowa jest, oświadczenia studenta (zlecenie) nie ma.
        assert "Umowa podpisana, dane do faktur" in tasks
        assert "Oświadczenie studenta i zgłoszenie do ZUS" not in tasks
        contract_task = tasks["Umowa podpisana, dane do faktur"]
        assert (contract_task.source, contract_task.source_label) == ("form", "B2B")
        assert contract_task.assignee_kind == "administration"
        assert contract_task.assignee_user_id is None and contract_task.requires_file
        # Sprzęt od nas: zestaw i wydanie z opisem rzeczy z pakietu.
        kit = tasks["Przygotuj zestaw sprzętu"]
        assert kit.key == "equipment_kit"
        assert kit.description == "Od nas: laptop 14 cali, słuchawki."
        assert kit.due_date == await _due(world["start"], -7)
        assert "Wydanie sprzętu i protokół" in tasks
        # Mail powitalny — opiekun, klucz dla modułu maila.
        mail = tasks["Mail powitalny do konsultanta"]
        assert (mail.key, mail.assignee_user_id) == ("welcome_mail", world["owner"].id)
        # Pakiet klienta: źródło „klient”, wykonawcy z ról.
        papers = tasks["Zaświadczenie o niekaralności"]
        assert papers.source == "client" and papers.source_label.startswith(
            "Klient Fikcyjny"
        )
        assert papers.assignee_user_id == world["owner"].id
        assert papers.due_date == await _due(world["start"], -1)
        assert tasks["Konto i VPN u klienta"].assignee_user_id == world["lead"].id
        assert (
            tasks["Pierwsza opinia menedżera u klienta"].assignee_user_id
            == world["lead"].id
        )
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_client_equipment_and_student_unknown_shape_the_list(
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world(provider="klienta", form="uzlecenie")
    try:
        await _start(world["id"])
        tasks = {task.title: task for task in await _tasks(world["id"])}
        assert "Przygotuj zestaw sprzętu" not in tasks
        assert "Wydanie sprzętu i protokół" not in tasks
        assert "Umowa podpisana, dane do faktur" not in tasks
        # Zlecenie, a status studenta nieznany: pozycja z dopiskiem do sprawdzenia.
        student = tasks["Oświadczenie studenta i zgłoszenie do ZUS"]
        assert student.source_label == "Zlecenie"
        assert "jeśli osoba nie jest studentem" in (student.description or "")
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_switched_off_lifecycle_module_leaves_contracts_as_today(pack) -> None:
    world = await _world()
    try:
        await _start(world["id"])
        assert await _tasks(world["id"]) == []
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_broken_pack_does_not_block_the_entry(
    modules_on,  # noqa: F811
    monkeypatch,
    back_office_head,  # noqa: F811
) -> None:
    async def broken(db, client_id):
        raise RuntimeError("pakiet nie działa")

    monkeypatch.setattr(client_pack, "pack_tasks", broken)
    monkeypatch.setattr(client_pack, "load_pack", broken)
    world = await _world()
    try:
        await _start(world["id"])
        tasks = await _tasks(world["id"])
        assert tasks and all(task.source != "client" for task in tasks)
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_new_start_date_moves_open_tasks_and_keeps_done_ones(
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world()
    try:
        await _start(world["id"])
        tasks = {task.title: task for task in await _tasks(world["id"])}
        async with AsyncSessionLocal() as db:
            done = await db.get(LifecycleTask, tasks["Rozmowa po pierwszym dniu"].id)
            done.status = "done"
            done.done_at = func.now()
            contract = await db.get(Contract, world["id"])
            contract.start_date = _future_weekday(42)
            await db.commit()
        await _start(world["id"])
        moved = {task.title: task for task in await _tasks(world["id"])}
        new_start = _future_weekday(42)
        assert moved["Zaświadczenie o niekaralności"].due_date == await _due(
            new_start, -1
        )
        assert moved["Mail powitalny do konsultanta"].due_date == await _due(
            new_start, -3
        )
        assert moved["Rozmowa po pierwszym dniu"].status == "done"
        assert len(moved) == len(tasks)
    finally:
        await _cleanup(world)


# ── Sprawa administracja@ i Sprzęt: jedna lista, bez dubli ──────────────────


@pytest.mark.asyncio
async def test_admin_case_checklist_is_the_administration_part_of_the_list(
    app_client,
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world()
    try:
        await _start(world["id"])
        async with AsyncSessionLocal() as db:
            entry = await db.scalar(
                select(LifecycleCase).where(LifecycleCase.contract_id == world["id"])
            )
            admin_case = await db.scalar(
                select(AdminCase).where(AdminCase.contract_id == world["id"])
            )
            kits = await db.scalar(
                select(func.count())
                .select_from(EquipmentTask)
                .where(EquipmentTask.contract_id == world["id"])
            )
        assert admin_case.lifecycle_case_id == entry.id
        assert admin_case.checklist == [
            {"text": "Umowa podpisana, dane do faktur", "done": False}
        ]
        assert kits == 1  # zadanie recepcji z haka Sprzętu, jedno
        task = next(
            t for t in await _tasks(world["id"]) if t.assignee_kind == "administration"
        )
        response = await app_client.patch(
            f"{BASE}/tasks/{task.id}",
            json={"status": "done"},
            headers=_headers(world["office"]),
        )
        assert response.status_code == 200, response.text
        async with AsyncSessionLocal() as db:
            admin_case = await db.get(AdminCase, admin_case.id)
        assert admin_case.checklist == [
            {"text": "Umowa podpisana, dane do faktur", "done": True}
        ]
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_checklist_ticked_in_cases_ticks_the_entry_task(
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    from app.services.admin_cases.hooks import sync_entry_tasks_from_checklist

    world = await _world()
    try:
        await _start(world["id"])
        async with AsyncSessionLocal() as db:
            admin_case = await db.scalar(
                select(AdminCase).where(AdminCase.contract_id == world["id"])
            )
            admin_case.checklist = [
                {"text": "Umowa podpisana, dane do faktur", "done": True},
                {"text": "Pozycja dopisana ręcznie", "done": False},
            ]
            assert (
                await sync_entry_tasks_from_checklist(db, admin_case, actor_id=None)
                == 1
            )
            await db.commit()
        task = next(
            t for t in await _tasks(world["id"]) if t.assignee_kind == "administration"
        )
        assert task.status == "done"
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_equipment_kit_mirrors_the_reception_task(
    app_client,
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world()
    try:
        await _start(world["id"])
        kit = next(t for t in await _tasks(world["id"]) if t.key == "equipment_kit")
        refused = await app_client.patch(
            f"{BASE}/tasks/{kit.id}",
            json={"status": "done"},
            headers=_headers(world["reception"]),
        )
        assert refused.status_code == 409
        async with AsyncSessionLocal() as db:
            equipment = await db.scalar(
                select(EquipmentTask).where(
                    EquipmentTask.source_key == f"contract:{world['id']}:start"
                )
            )
            equipment.status = "zrobione"
            await db.commit()
        view = await app_client.get(
            f"{BASE}/contracts/{world['id']}/entry", headers=_headers(world["owner"])
        )
        assert view.status_code == 200, view.text
        row = next(
            t for t in view.json()["case"]["tasks"] if t["key"] == "equipment_kit"
        )
        assert row["status"] == "done" and row["mirror"]["module"] == "equipment"
        assert row["can_toggle"] is False
        mine = await app_client.get(
            f"{BASE}/my-tasks", headers=_headers(world["reception"])
        )
        assert all(item["task_id"] != kit.id for item in mine.json()["items"])
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_voided_contract_cancels_the_entry_and_deleted_one_removes_it(
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world()
    try:
        await _start(world["id"])
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, world["id"])
            contract.status = ContractStatus.void
            await contract_hooks.contract_ended(db, contract)
            await db.commit()
            case = await db.scalar(
                select(LifecycleCase).where(LifecycleCase.contract_id == world["id"])
            )
            assert case.status == "cancelled"
            await contract_hooks.contract_deleted(db, contract)
            await db.commit()
            left = await db.scalar(
                select(func.count())
                .select_from(LifecycleCase)
                .where(LifecycleCase.contract_id == world["id"])
            )
        assert left == 0
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_complete_task_by_key_ticks_once_and_never_raises(
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world()
    try:
        await _start(world["id"])
        async with AsyncSessionLocal() as db:
            first = await lifecycle_service.complete_task_by_key(
                db,
                contract_id=world["id"],
                key="welcome_mail",
                actor_id=world["owner"].id,
            )
            second = await lifecycle_service.complete_task_by_key(
                db,
                contract_id=world["id"],
                key="welcome_mail",
                actor_id=world["owner"].id,
            )
            unknown = await lifecycle_service.complete_task_by_key(
                db, contract_id=world["id"], key="nie_ma", actor_id=world["owner"].id
            )
            no_case = await lifecycle_service.complete_task_by_key(
                db, contract_id=-1, key="welcome_mail", actor_id=world["owner"].id
            )
            await db.commit()
        assert (first, second, unknown, no_case) == (True, False, False, False)
        mail = next(t for t in await _tasks(world["id"]) if t.key == "welcome_mail")
        assert mail.status == "done" and mail.done_by == world["owner"].id
    finally:
        await _cleanup(world)


# ── Zakładka „Wejście” kontraktu ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entry_tab_scopes_owner_lead_viewer_and_outsiders(
    app_client,
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world()
    try:
        await _start(world["id"])
        url = f"{BASE}/contracts/{world['id']}/entry"
        owner = await app_client.get(url, headers=_headers(world["owner"]))
        assert owner.status_code == 200, owner.text
        body = owner.json()
        assert body["case"]["scope"] == "manager" and body["can_add_task"] is True
        assert body["composition"]["care_owner"]["id"] == world["owner"].id
        assert body["composition"]["employment_label"] == "B2B"
        assert body["composition"]["equipment"] == "ours"
        # Opiekun odhacza też zadania DL-a (O6: prowadzi całe wejście).
        lead_task = next(
            t for t in body["case"]["tasks"] if t["title"] == "Konto i VPN u klienta"
        )
        assert lead_task["can_toggle"] is True
        # DL spoza klienta — 403 jak w Kontraktach.
        other = await app_client.get(url, headers=_headers(world["other_lead"]))
        assert other.status_code == 403
        # Recepcja bez sekcji Delivery nie czyta zakładki, ale odhacza swoje.
        reception = await app_client.get(url, headers=_headers(world["reception"]))
        assert reception.status_code == 403
        issue = next(
            t
            for t in body["case"]["tasks"]
            if t["title"] == "Wydanie sprzętu i protokół"
        )
        ticked = await app_client.patch(
            f"{BASE}/tasks/{issue['id']}",
            json={"status": "done"},
            headers=_headers(world["reception"]),
        )
        assert ticked.status_code == 200, ticked.text
        # …ale nie cudze.
        foreign = await app_client.patch(
            f"{BASE}/tasks/{lead_task['id']}",
            json={"status": "done"},
            headers=_headers(world["reception"]),
        )
        assert foreign.status_code == 403
        # Head back office prowadzi wejście jak opiekun.
        head = await app_client.post(
            f"{url}/tasks",
            json={
                "title": "Karta parkingowa",
                "category": "other",
                "assignee_kind": "care_owner",
            },
            headers=_headers(back_office_head),
        )
        assert head.status_code == 201, head.text
        added = next(
            t for t in head.json()["case"]["tasks"] if t["title"] == "Karta parkingowa"
        )
        assert (
            added["source"] == "manual"
            and added["assignee_user_id"] == world["owner"].id
        )
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_entry_tab_explains_missing_list_and_creates_it_on_demand(
    app_client,
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world()
    try:
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, world["id"])
            contract.start_date = business_today() - timedelta(days=3)
            await db.commit()
        url = f"{BASE}/contracts/{world['id']}/entry"
        before = await app_client.get(url, headers=_headers(world["owner"]))
        assert before.json()["case"] is None
        assert before.json()["missing_reason"] == "past_start"
        assert before.json()["can_create"] is True
        await _start(world["id"])  # hak startu nie zakłada wejścia po starcie
        assert await _tasks(world["id"]) == []
        outsider = await app_client.post(url, headers=_headers(world["other_lead"]))
        assert outsider.status_code == 403
        created = await app_client.post(url, headers=_headers(world["owner"]))
        assert created.status_code == 201, created.text
        assert created.json()["case"]["audience"] == "consultant"
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_entry_tab_is_404_with_the_module_off_for_non_admins(app_client) -> None:
    world = await _world()
    try:
        response = await app_client.get(
            f"{BASE}/contracts/{world['id']}/entry", headers=_headers(world["owner"])
        )
        assert response.status_code == 404
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_consultant_start_date_is_changed_only_in_the_contract(
    app_client,
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    world = await _world()
    try:
        await _start(world["id"])
        async with AsyncSessionLocal() as db:
            hr = await _user(db, "recruiter")
            await _grant(db, hr, "people_admin")
            await db.commit()
            case_id = await db.scalar(
                select(LifecycleCase.id).where(LifecycleCase.contract_id == world["id"])
            )
        response = await app_client.patch(
            f"{BASE}/cases/{case_id}",
            json={"start_date": _future_weekday(60).isoformat()},
            headers=_headers(hr),
        )
        assert response.status_code == 422
        # Lista Kadr („Wejście nowej osoby”) nie miesza konsultantów.
        listing = await app_client.get(
            f"{BASE}/cases?kind=onboarding", headers=_headers(hr)
        )
        assert all(item["id"] != case_id for item in listing.json()["items"])
    finally:
        await _cleanup(world)


# ── Stare pozycje onboardingu kontraktu ─────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_onboarding_items_are_read_only_once_the_module_is_on(
    app_client,
    app_auth_headers,
    modules_on,  # noqa: F811
) -> None:
    world = await _world()
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                ContractOnboardingItem(
                    contract_id=world["id"], label="BHP — szkolenie", order=0
                )
            )
            await db.commit()
            item_id = await db.scalar(
                select(ContractOnboardingItem.id).where(
                    ContractOnboardingItem.contract_id == world["id"]
                )
            )
        path = f"/api/contracts/{world['id']}/onboarding"
        listed = await app_client.get(path, headers=app_auth_headers)
        assert listed.status_code == 200 and len(listed.json()) == 1
        for response in (
            await app_client.post(f"{path}/seed", headers=app_auth_headers),
            await app_client.post(
                path, json={"label": "Nowa"}, headers=app_auth_headers
            ),
            await app_client.patch(
                f"{path}/{item_id}", json={"status": "done"}, headers=app_auth_headers
            ),
            await app_client.delete(f"{path}/{item_id}", headers=app_auth_headers),
        ):
            assert response.status_code == 409, response.text
    finally:
        await _cleanup(world)


def test_contract_type_enum_still_matches_entry_forms() -> None:
    from app.services.hr.lifecycle_entry import _FORM_OF_CONTRACT

    assert set(_FORM_OF_CONTRACT) == {value.value for value in ContractType}


@pytest.mark.asyncio
async def test_checklist_saved_through_cases_ticks_the_entry_task(
    modules_on,  # noqa: F811
    pack,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    """Odhaczenie pozycji w Sprawach (zwykły zapis sprawy) przechodzi na listę wejścia."""

    from app.models.user import User
    from app.services.admin_cases import service as cases_service

    world = await _world()
    try:
        await _start(world["id"])
        async with AsyncSessionLocal() as db:
            admin_case = await db.scalar(
                select(AdminCase).where(AdminCase.contract_id == world["id"])
            )
            actor = await db.get(User, world["reception"].id)
            checklist = [dict(item) for item in admin_case.checklist]
            for item in checklist:
                if item["text"] == "Umowa podpisana, dane do faktur":
                    item["done"] = True
            await cases_service.update_case(
                db, admin_case, actor=actor, changes={"checklist": checklist}
            )
            await db.commit()
        task = next(
            t for t in await _tasks(world["id"]) if t.assignee_kind == "administration"
        )
        assert task.status == "done"
    finally:
        await _cleanup(world)
