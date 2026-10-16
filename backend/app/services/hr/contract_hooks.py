"""Kontrakt zmienia stan → moduły „Ludzi w NEXUSIE” dowiadują się o tym tutaj.

Trzy zdarzenia:

* ``contract_started`` — aktywacja: propozycje premii z placementu (Płace),
  zadanie „przygotuj zestaw” (Sprzęt, klient z „sprzęt od nas”), sprawa
  „Wejście konsultanta” (Sprawy administracja@),
* ``contract_ended`` — zakończenie albo unieważnienie: premie przed terminem
  anulowane, zadanie odbioru sprzętu; przy unieważnieniu (``void``, także
  szkicu) dodatkowo anulowane zadanie „Przygotuj zestaw” i zamknięta sprawa
  „Wejście konsultanta” — wejścia nie będzie,
* ``contract_end_undone`` — cofnięcie zakończenia / ponowne otwarcie: premie
  wracają.

Każdy moduł sam sprawdza swój przełącznik i jest idempotentny po kluczu
(``source_key``), a krok biegnie w savepoincie: awaria modułu pobocznego jest
logowana i nie blokuje zmiany kontraktu. Haki nie commitują — robi to
wołający razem ze zmianą kontraktu.

Kontrakt zmienia stan wieloma ścieżkami (ekran, masowe zakończenie, PATCH,
nocna synchronizacja z zamówieniami), więc źródłem prawdy jest przegląd
``reconcile_upcoming`` z pętli HR; haki w ścieżkach głównych tylko skracają
czas do pojawienia się zadania. Przegląd domyka też kontrakty unieważnione,
po których została otwarta sprawa albo zadanie startu (hak padł w savepoincie).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import and_, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.admin_case import AdminCase
from app.models.contract import Contract, ContractStatus
from app.models.equipment import EquipmentTask
from app.services.admin_cases_schema import TERMINAL_STATUSES

logger = logging.getLogger(__name__)

#: Ile dni naprzód przegląd szuka startów i końców kontraktów.
LOOKAHEAD_DAYS = 14

Step = Callable[[AsyncSession, Contract], Awaitable[Any]]


async def _equipment_enabled(db: AsyncSession) -> bool:
    from app.services.hr.modules import load_modules

    return bool((await load_modules(db)).get("equipment"))


async def _run(
    db: AsyncSession, contract: Contract, event: str, steps: list[tuple[str, Step]]
) -> dict[str, str]:
    outcome: dict[str, str] = {}
    for name, step in steps:
        try:
            async with db.begin_nested():
                await step(db, contract)
            outcome[name] = "ok"
        except Exception as exc:  # noqa: BLE001 — moduł poboczny nie blokuje kontraktu
            logger.exception(
                "[contract_hooks] %s kontraktu %s: krok %s nie przeszedł",
                event,
                contract.id,
                name,
            )
            outcome[name] = type(exc).__name__
    return outcome


async def _payroll_started(db: AsyncSession, contract: Contract) -> None:
    from app.services.hr import placement_bonuses

    await placement_bonuses.on_contract_started(db, contract)


async def _payroll_ended(db: AsyncSession, contract: Contract) -> None:
    from app.services.hr import placement_bonuses

    await placement_bonuses.on_contract_ended(db, contract)


async def _payroll_end_undone(db: AsyncSession, contract: Contract) -> None:
    from app.services.hr import placement_bonuses

    await placement_bonuses.on_contract_end_undone(db, contract)


async def _equipment_start(db: AsyncSession, contract: Contract) -> None:
    if not await _equipment_enabled(db):
        return
    from app.services.equipment import tasks as equipment_tasks

    await equipment_tasks.tasks_for_contract_start(db, contract)


async def _equipment_end(db: AsyncSession, contract: Contract) -> None:
    if not await _equipment_enabled(db):
        return
    from app.services.equipment import tasks as equipment_tasks

    if contract.status == ContractStatus.void:
        await equipment_tasks.cancel_contract_start_task(db, contract.id)
    await equipment_tasks.tasks_for_contract_end(db, contract)


async def _equipment_void(db: AsyncSession, contract: Contract) -> None:
    if contract.status != ContractStatus.void or not await _equipment_enabled(db):
        return
    from app.services.equipment import tasks as equipment_tasks

    await equipment_tasks.cancel_contract_start_task(db, contract.id)


async def _cases_void(db: AsyncSession, contract: Contract) -> None:
    if contract.status != ContractStatus.void:
        return
    from app.services.admin_cases.hooks import close_case_for_voided_contract

    await close_case_for_voided_contract(db, contract.id)


async def _cases_start(db: AsyncSession, contract: Contract) -> None:
    from app.services.admin_cases.hooks import open_case_for_new_contract

    await open_case_for_new_contract(db, contract)


async def contract_started(db: AsyncSession, contract: Contract) -> dict[str, str]:
    return await _run(
        db,
        contract,
        "started",
        [
            ("payroll", _payroll_started),
            ("equipment", _equipment_start),
            ("cases", _cases_start),
        ],
    )


async def contract_ended(db: AsyncSession, contract: Contract) -> dict[str, str]:
    return await _run(
        db,
        contract,
        "ended",
        [
            ("payroll", _payroll_ended),
            ("equipment", _equipment_end),
            ("cases", _cases_void),
        ],
    )


async def contract_end_undone(db: AsyncSession, contract: Contract) -> dict[str, str]:
    return await _run(db, contract, "end_undone", [("payroll", _payroll_end_undone)])


_LIVE = (ContractStatus.active, ContractStatus.ending)
_UPCOMING = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.active,
)


async def reconcile_upcoming(db: AsyncSession) -> dict[str, int]:
    """Przegląd: starty i końce w ciągu ``LOOKAHEAD_DAYS`` (idempotentnie).

    Premie z placementów uzgadnia osobno pętla Płac (``payroll_jobs``).
    """
    today = business_today()
    horizon = today + timedelta(days=LOOKAHEAD_DAYS)
    starting = list(
        await db.scalars(
            select(Contract).where(
                Contract.status.in_(_UPCOMING),
                Contract.start_date.is_not(None),
                Contract.start_date.between(today, horizon),
            )
        )
    )
    ending = list(
        await db.scalars(
            select(Contract).where(
                Contract.status.in_(_LIVE),
                or_(
                    and_(
                        Contract.end_date.is_not(None),
                        Contract.end_date.between(today, horizon),
                    ),
                ),
            )
        )
    )
    for contract in starting:
        await _run(
            db,
            contract,
            "reconcile_start",
            [("equipment", _equipment_start), ("cases", _cases_start)],
        )
    for contract in ending:
        await _run(db, contract, "reconcile_end", [("equipment", _equipment_end)])
    voided = await _voided_with_open_start(db)
    for contract in voided:
        await _run(
            db,
            contract,
            "reconcile_void",
            [("equipment", _equipment_void), ("cases", _cases_void)],
        )
    return {"starting": len(starting), "ending": len(ending), "voided": len(voided)}


async def _voided_with_open_start(db: AsyncSession) -> list[Contract]:
    """Unieważnione kontrakty z otwartą sprawą albo zadaniem startu."""

    start_key = "contract:%:start"
    open_links = union(
        select(AdminCase.contract_id).where(
            AdminCase.source_key.like(start_key),
            AdminCase.status.not_in(TERMINAL_STATUSES),
            AdminCase.contract_id.is_not(None),
        ),
        select(EquipmentTask.contract_id).where(
            EquipmentTask.source_key.like(start_key),
            EquipmentTask.status == "otwarte",
            EquipmentTask.contract_id.is_not(None),
        ),
    )
    return list(
        await db.scalars(
            select(Contract).where(
                Contract.status == ContractStatus.void,
                Contract.id.in_(open_links),
            )
        )
    )
