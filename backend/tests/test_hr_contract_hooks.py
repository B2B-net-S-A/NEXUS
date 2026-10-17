"""Kontrakt → Płace, Sprzęt, Sprawy (``app/services/hr/contract_hooks.py``).

Awaria jednego modułu nie blokuje pozostałych ani zmiany kontraktu; przegląd
startów zakłada zadanie sprzętu i sprawę wejścia raz (drugi przebieg nic nie
dubluje). Dane fikcyjne.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase
from app.models.contract import Contract
from app.models.equipment import EquipmentTask
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

    monkeypatch.setattr(contract_hooks, "_payroll_started", broken)
    monkeypatch.setattr(contract_hooks, "_lifecycle_start", entry)
    monkeypatch.setattr(contract_hooks, "_equipment_start", ok)
    monkeypatch.setattr(contract_hooks, "_cases_start", cases)
    async with AsyncSessionLocal() as db:
        try:
            contract = Contract(id=-1)
            outcome = await contract_hooks.contract_started(db, contract)
        finally:
            await db.rollback()
    # Wejście konsultanta przed sprawą administracja@ — sprawa czyta jego listę.
    assert calls == ["payroll", "lifecycle", "equipment", "cases"]
    assert outcome == {
        "payroll": "RuntimeError",
        "lifecycle": "ok",
        "equipment": "ok",
        "cases": "ok",
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
