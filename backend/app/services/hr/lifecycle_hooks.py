"""Haki spraw wejścia i odejścia dla modułów Spraw i Sprzętu.

lifecycle_integrations to jedno miejsce, w którym moduły poboczne
dowiadują się o sprawie — bez importu ich kodu w serwisie spraw. Każdy hak
sam pyta o przełącznik swojego modułu (wyłączony = nic) i biegnie w swoim
punkcie zapisu: awaria modułu pobocznego nie blokuje sprawy.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_lifecycle import LifecycleCase
from app.services.hr.modules import HrModule, load_modules

logger = logging.getLogger(__name__)

LifecycleEvent = Literal[
    "onboarding_started",
    "onboarding_cancelled",
    "offboarding_started",
    "offboarding_cancelled",
    "exit_executed",
]

LifecycleHook = Callable[[AsyncSession, LifecycleCase, str], Awaitable[None]]


async def _module_on(db: AsyncSession, module: HrModule) -> bool:
    return bool((await load_modules(db)).get(module))


async def _cases_hook(db: AsyncSession, case: LifecycleCase, event: str) -> None:
    """Sprawy administracja@: odejście zakłada sprawę, cofnięcie ją zamyka
    (idempotentnie po kluczu). Wyłączony moduł = nic — do przełączenia sprawy
    prowadzi Compass."""
    if not await _module_on(db, HrModule.cases):
        return
    from app.services.admin_cases import hooks as case_hooks

    if event == "offboarding_started":
        await case_hooks.open_case_for_offboarding(db, case.user_id, case.id)
    elif event == "offboarding_cancelled":
        await case_hooks.close_case_for_cancelled_offboarding(db, case.user_id, case.id)


async def _equipment_hook(db: AsyncSession, case: LifecycleCase, event: str) -> None:
    """Sprzęt: zestaw na wejście, odbiór rzeczy przy odejściu; cofnięcie
    sprawy anuluje zadanie, które założył jej start (idempotentnie)."""
    if not await _module_on(db, HrModule.equipment):
        return
    from app.services.equipment import tasks as equipment_tasks

    if event == "onboarding_started" and case.start_date is not None:
        await equipment_tasks.tasks_for_person_start(db, case.user_id, case.start_date)
    elif event == "offboarding_started" and case.last_working_day is not None:
        await equipment_tasks.tasks_for_person_exit(
            db, case.user_id, case.last_working_day
        )
    elif event == "onboarding_cancelled" and case.user_id is not None:
        await equipment_tasks.cancel_person_start_task(db, case.user_id)
    elif event == "offboarding_cancelled" and case.user_id is not None:
        await equipment_tasks.cancel_person_exit_task(db, case.user_id)


def _integration_hooks() -> list[LifecycleHook]:
    return [_cases_hook, _equipment_hook]


async def lifecycle_integrations(
    db: AsyncSession, case: LifecycleCase, event: LifecycleEvent
) -> None:
    """Jedno miejsce, w którym moduły Spraw i Sprzętu dowiadują się o sprawie.

    Kontrakt (dla koordynatora, który wpina haki):

    * ``event``:
      - ``onboarding_started`` — wejście ruszyło (``case.start_date``,
        ``case.user_id``, ``case.manager_user_id``); Sprzęt: zadanie „Wydaj
        zestaw” na 2 dni robocze przed startem,
      - ``offboarding_started`` — odejście ruszyło (``case.last_working_day``,
        ``case.deactivate_on``); Sprawy: sprawa „Odejście: <osoba>” powiązana
        przez ``lifecycle_case_id``; Sprzęt: zadanie zwrotu rzeczy osoby,
      - ``offboarding_cancelled`` — „Cofnij odejście”; Sprawy zamykają sprawę
        „Odejście: <osoba>”, Sprzęt anuluje otwarte zadanie zwrotu rzeczy,
      - ``onboarding_cancelled`` — anulowane wejście w toku; Sprzęt anuluje
        otwarte zadanie „Przygotuj zestaw biura”,
      - ``exit_executed`` — konto zamknięte (``case.account_close_result``);
        Sprzęt: niezwrócone rzeczy → dzwonek do recepcji i przełożonego.
    * Hak dostaje sesję W TRAKCIE transakcji sprawy: dopisuje swoje wiersze,
      nie commituje. Wyjątek haka jest logowany i cofany savepointem — sprawa
      idzie dalej (moduł poboczny nie blokuje odejścia).
    * Hak ma być idempotentny po ``(case.id, event)`` — pętla może wołać
      ``exit_executed`` po restarcie drugi raz dla tej samej sprawy tylko,
      gdy commit pierwszego przebiegu nie doszedł.
    """

    for hook in _integration_hooks():
        try:
            async with db.begin_nested():
                await hook(db, case, event)
        except Exception:  # noqa: BLE001 — moduł poboczny nie blokuje sprawy
            logger.exception(
                "hr_lifecycle integration failed case=%s event=%s hook=%s",
                case.id,
                event,
                getattr(hook, "__qualname__", hook),
            )


__all__ = ["LifecycleEvent", "LifecycleHook", "lifecycle_integrations"]
