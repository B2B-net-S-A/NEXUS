"""Kontrakt → Płace, Sprzęt, Sprawy (``app/services/hr/contract_hooks.py``).

Awaria jednego modułu nie blokuje pozostałych ani zmiany kontraktu; przegląd
startów zakłada zadanie sprzętu i sprawę wejścia raz (drugi przebieg nic nie
dubluje). Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase
from app.models.contract import Contract, ContractStatus
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentItem,
    EquipmentModel,
    EquipmentTask,
)
from app.models.hr_lifecycle import LifecycleCase
from app.services.hr import contract_hooks
from tests.test_equipment_api import _contract, _drop_contract, modules_on  # noqa: F401


@pytest.mark.asyncio
async def test_failing_module_does_not_stop_the_others(monkeypatch) -> None:
    calls: list[str] = []

    async def broken(db, contract) -> None:
        calls.append("payroll")
        raise RuntimeError("awaria modułu")

    async def ok(db, contract) -> None:
        calls.append("equipment")

    async def cases(db, contract) -> None:
        calls.append("cases")

    async def entry(db, contract) -> None:
        calls.append("lifecycle")

    async def care(db, contract) -> None:
        calls.append("care")

    monkeypatch.setattr(contract_hooks, "_payroll_started", broken)
    monkeypatch.setattr(contract_hooks, "_lifecycle_start", entry)
    monkeypatch.setattr(contract_hooks, "_equipment_start", ok)
    monkeypatch.setattr(contract_hooks, "_cases_start", cases)
    monkeypatch.setattr(contract_hooks, "_care_start", care)
    async with AsyncSessionLocal() as db:
        try:
            contract = Contract(id=-1)
            outcome = await contract_hooks.contract_started(db, contract)
        finally:
            await db.rollback()
    # Wejście konsultanta przed sprawą administracja@ — sprawa czyta jego listę.
    assert calls == ["payroll", "lifecycle", "equipment", "cases", "care"]
    assert outcome == {
        "payroll": "RuntimeError",
        "lifecycle": "ok",
        "equipment": "ok",
        "cases": "ok",
        "care": "ok",
    }


@pytest.mark.asyncio
async def test_reconcile_creates_start_task_and_case_once(modules_on) -> None:  # noqa: F811
    start = business_today() + timedelta(days=10)
    ids = await _contract(start=start, end=None, provider="nasz")
    try:
        for _ in range(2):
            async with AsyncSessionLocal() as db:
                await contract_hooks.reconcile_upcoming(db)
                await db.commit()
        async with AsyncSessionLocal() as db:
            tasks = await db.scalar(
                select(func.count())
                .select_from(EquipmentTask)
                .where(EquipmentTask.contract_id == ids["id"])
            )
            cases = await db.scalar(
                select(func.count())
                .select_from(AdminCase)
                .where(AdminCase.contract_id == ids["id"])
            )
        assert tasks == 1
        assert cases == 1
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                EquipmentTask.__table__.delete().where(
                    EquipmentTask.contract_id == ids["id"]
                )
            )
            await db.execute(
                AdminCase.__table__.delete().where(AdminCase.contract_id == ids["id"])
            )
            # Wejście konsultanta (etap 3) nie ma FK do kontraktu.
            await db.execute(
                LifecycleCase.__table__.delete().where(
                    LifecycleCase.contract_id == ids["id"]
                )
            )
            await db.commit()
        await _drop_contract(ids)


async def _imported_issue(
    contract_id: int, *, ownership: str = "nasz", returned: bool = False
) -> int:
    """Wydanie jak z importu plików recepcji: rejestr bez protokołu i bez wpisu zakładki."""

    tag = uuid.uuid4().hex[:10].upper()
    issued_at = datetime.now(timezone.utc) - timedelta(days=30)
    async with AsyncSessionLocal() as db:
        model = EquipmentModel(category="monitor", name=f"Monitor Fikcyjny {tag}")
        db.add(model)
        await db.flush()
        item = EquipmentItem(
            model_id=model.id,
            serial_number=f"TEST{tag}",
            status="na_stanie" if returned else "wydany",
            ownership=ownership,
        )
        db.add(item)
        await db.flush()
        db.add(
            EquipmentAssignment(
                item_id=item.id,
                contract_id=contract_id,
                issued_at=issued_at,
                returned_at=issued_at + timedelta(days=1) if returned else None,
                return_condition="sprawny" if returned else None,
            )
        )
        await db.commit()
        return item.id


async def _end_contract_in_the_past(ids: dict, end) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["id"])
        contract.status = ContractStatus.ended
        contract.end_date = end
        await db.commit()


async def _drop_with_items(ids: dict, item_ids: list[int]) -> None:
    await _drop_contract(ids)  # kaskada: wydania i zadania kontraktu
    async with AsyncSessionLocal() as db:
        model_ids = list(
            await db.scalars(
                select(EquipmentItem.model_id).where(EquipmentItem.id.in_(item_ids))
            )
        )
        await db.execute(delete(EquipmentItem).where(EquipmentItem.id.in_(item_ids)))
        await db.execute(delete(EquipmentModel).where(EquipmentModel.id.in_(model_ids)))
        await db.commit()


async def _return_tasks(contract_id: int) -> list[EquipmentTask]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(EquipmentTask).where(
                    EquipmentTask.contract_id == contract_id,
                    EquipmentTask.kind == "zwrot",
                )
            )
        )


async def _reconcile() -> None:
    async with AsyncSessionLocal() as db:
        await contract_hooks.reconcile_upcoming(db)
        await db.commit()


@pytest.mark.asyncio
async def test_reconcile_opens_overdue_return_task_for_ended_contract(
    modules_on,  # noqa: F811
) -> None:
    """Kontrakt zakończony przed importem plików recepcji (kopia produkcji
    z 19.11.2026: 2 kontrakty, 3 urządzenia) nie miał zadania „Odbierz sprzęt”,
    bo przegląd patrzył tylko 14 dni naprzód. Decyzja Artura z 20.11.2026:
    zadanie recepcji po terminie, bez dzwonka Delivery Leada."""

    end = business_today() - timedelta(days=80)
    ids = await _contract(start=end - timedelta(days=200), end=end, provider="nasz")
    items: list[int] = []
    try:
        await _end_contract_in_the_past(ids, end)
        items.append(await _imported_issue(ids["id"]))
        for _ in range(2):
            await _reconcile()
        tasks = await _return_tasks(ids["id"])
        assert len(tasks) == 1
        task = tasks[0]
        assert task.source_key == f"contract:{ids['id']}:end"
        assert task.status == "otwarte"
        assert task.due_on == end  # termin = koniec kontraktu, więc „po terminie”
        assert task.details["items"] == 1

        # Zadanie zamknięte przez człowieka nie wraca w kolejnym przeglądzie.
        async with AsyncSessionLocal() as db:
            row = await db.get(EquipmentTask, task.id)
            row.status = "zrobione"
            await db.commit()
        await _reconcile()
        assert [t.status for t in await _return_tasks(ids["id"])] == ["zrobione"]
    finally:
        await _drop_with_items(ids, items)


@pytest.mark.asyncio
async def test_reconcile_skips_ended_contract_without_our_unreturned_equipment(
    modules_on,  # noqa: F811
) -> None:
    end = business_today() - timedelta(days=40)
    returned = await _contract(start=end - timedelta(days=100), end=end)
    clients_only = await _contract(start=end - timedelta(days=100), end=end)
    items: dict[int, list[int]] = {returned["id"]: [], clients_only["id"]: []}
    try:
        for ids in (returned, clients_only):
            await _end_contract_in_the_past(ids, end)
        items[returned["id"]].append(
            await _imported_issue(returned["id"], returned=True)
        )
        # Sprzęt klienta wraca do klienta, nie do recepcji (jak `tasks_for_contract_end`).
        items[clients_only["id"]].append(
            await _imported_issue(clients_only["id"], ownership="klienta")
        )
        await _reconcile()
        assert await _return_tasks(returned["id"]) == []
        assert await _return_tasks(clients_only["id"]) == []
    finally:
        await _drop_with_items(returned, items[returned["id"]])
        await _drop_with_items(clients_only, items[clients_only["id"]])
