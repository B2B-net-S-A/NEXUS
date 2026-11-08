"""Jednorazowa korekta dat zakończenia umów (09.2026).

Dwie rzeczy, w tej kolejności:

1. **Zakończenia ze zgłoszenia** — lista osób kończących współpracę, każda
   z datą i wpisem „[Kto] — [Powód]". Wykonane tak jak „Zakończ współpracę"
   (``POST /api/contracts/{id}/terminate``): ``terminated_at``,
   ``termination_reason`` (najbliższa wartość słownika), treść do pola
   tekstowego ``termination_lessons``, domknięcie zamówień klienta. Jedna
   różnica, świadoma: data zakończenia jest DOKŁADNIE ta ze zgłoszenia, także
   gdy jest późniejsza niż dotychczasowa — dotychczasowa pochodziła z końca
   zamówienia i to ją korygujemy. Status liczony jak w ``/terminate`` i w
   nocnym cronie: dzień zakończenia minął albo jest dziś → „Zakończony",
   najbliższe 30 dni → „Kończący się", później → „Aktywny" (kontrakt pracuje
   do tej daty, więc nie znika z MRR przed czasem).

   Repo jest publiczne, więc lista NIE zawiera nazwisk: każdy wpis to
   identyfikatory kontraktu, osoby i klienta sprawdzone na produkcji.
   Wpis, którego trójka ID się nie zgadza, zostaje nietknięty z kodem powodu
   w paragonie.

2. **Umowy B2B bez ręcznego zakończenia** — każda umowa B2B w statusie
   „Aktywny"/„Kończący się" z datą zakończenia, której nikt nie zakończył
   (brak ``terminated_at``, ``termination_reason`` i aneksu
   ``early_termination``), staje się bezterminowa. „Kończący się" wraca na
   „Aktywny" (bezterminowa umowa się nie kończy). Umowy „Zakończone",
   zlecenia i umowy o pracę — bez zmian. Szkice też bez zmian: szkic z datą
   z przeszłości nie aktywuje się automatycznie, a wyczyszczenie daty
   wpuściłoby go do MRR przy najbliższym zapisie zamówienia.

Blok jest jednorazowy (marker w ``app_settings`` + advisory lock) i odpalany
z ``entrypoint.sh``. Paragon pod kluczem ``NNNN_…`` niesie wyłącznie liczniki,
ID, daty i kody powodów (czyta go publiczny log workflow ``migration-receipts``);
treść wpisów „kto — powód" leży pod kluczem innego kształtu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client_order import ClientOrder
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    ContractType,
)
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.services.b2b_contract_end_date import is_manually_terminated
from app.services.contract_lifecycle import assert_transition, reopen_contract
from app.services.contract_order_offboarding import apply_contract_order_offboarding
from app.services.contract_order_sync import resync_contract_safely
from app.services.contract_rates import RATE_SCHEDULE_LOADS

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0307_b2b_indefinite_end_date"
DETAILS_KEY = "repair_details_0307_b2b_indefinite_end_date"
SOURCE = REPAIR_MARKER

ENDING_WINDOW_DAYS = 30  # lustro `contract_alerts._promote_statuses`

# „[Kto] — [Powód]" ze zgłoszenia → najbliższa wartość słownika powodów.
# Słownik zasila analitykę odejść (rezygnacje = inicjatywa konsultanta), więc
# decyduje w nim KTO zakończył; szczegół zostaje w treści wpisu.
NOTE_REASON: dict[str, ContractTerminationReason] = {
    "Klient — No budget": ContractTerminationReason.client_budget_cut,
    "Klient — Wydajność": ContractTerminationReason.performance_issue,
    "Kandydat — Wyższa stawka": ContractTerminationReason.better_offer,
    "Kandydat — Przyczyny osobiste": ContractTerminationReason.personal_reasons,
    "Kandydat — No budget": ContractTerminationReason.consultant_resigned,
    "Kandydat": ContractTerminationReason.consultant_resigned,
    "Internalizacja": ContractTerminationReason.poached_by_client,
}


@dataclass(frozen=True)
class TicketTermination:
    """Jedna osoba ze zgłoszenia — wyłącznie identyfikatory, bez nazwiska."""

    contract_id: int
    candidate_id: int
    client_id: int
    end_date: date
    note: str

    @property
    def reason(self) -> ContractTerminationReason:
        return NOTE_REASON[self.note]


# Zgłoszenie 11.09.2026 — 16 osób. Trójki ID (kontrakt, kandydat, klient)
# odczytane z produkcji 11.09.2026: każda osoba ma dokładnie jeden kontrakt.
TICKET_TERMINATIONS: tuple[TicketTermination, ...] = (
    TicketTermination(49, 25574, 11, date(2026, 10, 2), "Klient — No budget"),
    TicketTermination(91, 6404, 11, date(2026, 9, 19), "Klient — Wydajność"),
    TicketTermination(105, 75983, 11, date(2026, 8, 24), "Klient — Wydajność"),
    TicketTermination(139, 26203, 11, date(2026, 9, 30), "Klient — No budget"),
    TicketTermination(259, 25896, 11, date(2026, 10, 31), "Kandydat — Wyższa stawka"),
    TicketTermination(345, 197213, 11, date(2026, 9, 30), "Kandydat — Wyższa stawka"),
    TicketTermination(419, 25753, 16, date(2026, 12, 31), "Internalizacja"),
    TicketTermination(433, 13252, 35, date(2026, 7, 31), "Klient — Wydajność"),
    TicketTermination(452, 65741, 26, date(2026, 8, 31), "Klient — Wydajność"),
    TicketTermination(489, 5435, 39, date(2026, 9, 11), "Klient — No budget"),
    TicketTermination(498, 19471, 11, date(2026, 6, 30), "Kandydat"),
    TicketTermination(
        518, 5874, 12, date(2026, 9, 30), "Kandydat — Przyczyny osobiste"
    ),
    TicketTermination(519, 67701, 26, date(2026, 8, 18), "Klient — Wydajność"),
    TicketTermination(574, 70446, 18, date(2026, 9, 3), "Klient — Wydajność"),
    TicketTermination(605, 12579, 61, date(2026, 10, 31), "Kandydat — No budget"),
    TicketTermination(618, 5404, 26, date(2026, 8, 31), "Kandydat — Wyższa stawka"),
)


def target_status(end_date: date, today: date) -> ContractStatus:
    """Status umowy zakończonej z datą ``end_date`` (``/terminate`` + cron)."""
    if end_date <= today:
        return ContractStatus.ended
    if end_date <= today + timedelta(days=ENDING_WINDOW_DAYS):
        return ContractStatus.ending
    return ContractStatus.active


async def _move_status(
    db: AsyncSession, contract: Contract, target: ContractStatus
) -> None:
    """Przejście przez krawędzie maszyny stanów, z audytem przy wskrzeszeniu."""
    if contract.status == target:
        return
    if target != ContractStatus.ended and contract.status in (
        ContractStatus.ended,
        ContractStatus.ending,
    ):
        await reopen_contract(db, contract, actor_id=None)
    if contract.status != target:
        assert_transition(contract.status, target)
        contract.status = target


async def _apply_ticket_termination(
    db: AsyncSession, spec: TicketTermination, *, today: date
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "contract_id": spec.contract_id,
        "end_date": spec.end_date.isoformat(),
        "reason": spec.reason.value,
        "skipped": None,
    }
    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == spec.contract_id)
        .options(*RATE_SCHEDULE_LOADS)
        .with_for_update(of=Contract)
    )
    if contract is None:
        item["skipped"] = "not_found"
        return item
    if (contract.candidate_id, contract.client_id) != (
        spec.candidate_id,
        spec.client_id,
    ):
        item["skipped"] = "identity_mismatch"
        return item
    if contract.status in (
        ContractStatus.void,
        ContractStatus.draft,
        ContractStatus.ready_for_signature,
    ):
        item["skipped"] = f"status_{contract.status.value}"
        return item
    if (
        contract.terminated_at == spec.end_date
        and contract.termination_reason == spec.reason
        and contract.termination_lessons == spec.note
        and contract.end_date == spec.end_date
    ):
        item["skipped"] = "already_applied"
        return item

    previous_end = contract.end_date
    item["before"] = {
        "status": contract.status.value,
        "end_date": previous_end.isoformat() if previous_end else None,
        "terminated_at": (
            contract.terminated_at.isoformat() if contract.terminated_at else None
        ),
        "termination_reason": (
            contract.termination_reason.value if contract.termination_reason else None
        ),
    }
    item["before_lessons"] = contract.termination_lessons
    # Data wsteczna skraca albo anuluje zamówienia (tak jak `/terminate`) —
    # stan sprzed korekty zostaje w szczegółach, żeby dało się ją odwrócić.
    item["orders_before"] = [
        {
            "order_id": order.id,
            "status": order.status.value,
            "start_date": order.start_date.isoformat() if order.start_date else None,
            "end_date": order.end_date.isoformat() if order.end_date else None,
            "order_group_id": order.order_group_id,
        }
        for order in (
            await db.scalars(
                select(ClientOrder)
                .where(ClientOrder.contract_id == contract.id)
                .order_by(ClientOrder.id)
            )
        ).all()
    ]

    contract.terminated_at = spec.end_date
    contract.termination_reason = spec.reason
    contract.termination_lessons = spec.note
    contract.end_date = spec.end_date
    await _move_status(db, contract, target_status(spec.end_date, today))

    offboarding = await apply_contract_order_offboarding(
        db,
        contract_id=contract.id,
        effective_date=spec.end_date,
        actor_id=None,
        today=today,
    )
    if previous_end is not None and spec.end_date < previous_end:
        db.add(
            ContractAmendment(
                contract_id=contract.id,
                amendment_type=ContractAmendmentType.early_termination,
                old_values={
                    "end_date": previous_end.isoformat(),
                    "status": item["before"]["status"],
                },
                new_values={
                    "end_date": spec.end_date.isoformat(),
                    "status": contract.status.value,
                },
                effective_date=spec.end_date,
                reason=f"{spec.reason.value}: {spec.note}",
            )
        )
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="terminated",
            user_id=None,
            details={
                "termination_reason": spec.reason.value,
                "terminated_at": spec.end_date.isoformat(),
                "early": previous_end is not None and spec.end_date < previous_end,
                "synced_orders": offboarding.affected_orders,
                "source": SOURCE,
            },
        )
    )
    await resync_contract_safely(db, contract, actor_id=None)
    item["status_after"] = contract.status.value
    item["synced_orders"] = offboarding.affected_orders
    return item


async def _clear_b2b_end_dates(
    db: AsyncSession, *, only_contract_ids: Optional[set[int]]
) -> list[dict[str, Any]]:
    candidates = (
        await db.scalars(
            select(Contract)
            .where(
                Contract.contract_type == ContractType.b2b,
                Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
                Contract.end_date.is_not(None),
                Contract.terminated_at.is_(None),
                Contract.termination_reason.is_(None),
                *(
                    (Contract.id.in_(only_contract_ids),)
                    if only_contract_ids is not None
                    else ()
                ),
            )
            .order_by(Contract.id)
            .with_for_update()
        )
    ).all()
    cleared: list[dict[str, Any]] = []
    for contract in candidates:
        # Aneks `early_termination` to też ręczne zakończenie — bez śladu na
        # samym wierszu, więc sprawdzany osobno (jak w regule dla API).
        if await is_manually_terminated(db, contract):
            continue
        previous_status = contract.status
        previous_end = contract.end_date
        contract.end_date = None
        if previous_status == ContractStatus.ending:
            await reopen_contract(db, contract, actor_id=None)
        db.add(
            Activity(
                entity_type="contract",
                entity_id=contract.id,
                action="end_date_cleared",
                user_id=None,
                details={
                    "previous_end_date": previous_end.isoformat(),
                    "previous_status": previous_status.value,
                    "status": contract.status.value,
                    "source": SOURCE,
                },
            )
        )
        cleared.append(
            {
                "contract_id": contract.id,
                "previous_end_date": previous_end.isoformat(),
                "previous_status": previous_status.value,
            }
        )
    return cleared


async def run_b2b_end_date_repair(
    db: AsyncSession,
    *,
    today: Optional[date] = None,
    terminations: tuple[TicketTermination, ...] = TICKET_TERMINATIONS,
    only_contract_ids: Optional[set[int]] = None,
) -> Optional[dict[str, Any]]:
    """Zakończenia ze zgłoszenia, potem czyszczenie dat B2B. ``None`` = już było.

    Wołający commituje. ``only_contract_ids`` zawęża CZYSZCZENIE — wyłącznie
    dla testów, które nie mogą ruszać cudzych kontraktów we wspólnej bazie.
    """
    today = today or business_today()
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": REPAIR_MARKER}
    )
    if await db.get(AppSetting, REPAIR_MARKER) is not None:
        return None

    terminated = [
        await _apply_ticket_termination(db, spec, today=today) for spec in terminations
    ]
    await db.flush()
    cleared = await _clear_b2b_end_dates(db, only_contract_ids=only_contract_ids)
    await db.flush()

    applied = [item for item in terminated if item["skipped"] is None]
    summary: dict[str, Any] = {
        "business_day": today.isoformat(),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "terminations_requested": len(terminations),
        "terminations_applied": len(applied),
        "terminations_skipped": [
            {"contract_id": item["contract_id"], "reason": item["skipped"]}
            for item in terminated
            if item["skipped"] is not None
        ],
        "terminated": [
            {
                "contract_id": item["contract_id"],
                "end_date": item["end_date"],
                "reason": item["reason"],
                "status_before": item["before"]["status"],
                "end_date_before": item["before"]["end_date"],
                "status_after": item["status_after"],
                "synced_orders": item["synced_orders"],
            }
            for item in applied
        ],
        "b2b_end_dates_cleared": len(cleared),
        "cleared": cleared,
    }
    db.add(AppSetting(key=REPAIR_MARKER, value=summary))
    # Treść wpisów i poprzednie wartości pól tekstowych — do ręcznego
    # odwrócenia; klucz innego kształtu niż paragon, więc publiczny workflow
    # `migration-receipts` go nie wydrukuje.
    db.add(
        AppSetting(
            key=DETAILS_KEY,
            value={
                "terminated": [
                    {
                        "contract_id": item["contract_id"],
                        "note": spec.note,
                        "before": item.get("before"),
                        "before_lessons": item.get("before_lessons"),
                        "orders_before": item.get("orders_before"),
                    }
                    for spec, item in zip(terminations, terminated)
                    if item["skipped"] is None
                ]
            },
        )
    )
    await db.flush()
    logger.info(
        "b2b end-date repair: terminations %s/%s, cleared %s",
        len(applied),
        len(terminations),
        len(cleared),
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    return (
        f"terminations {summary['terminations_applied']}/"
        f"{summary['terminations_requested']} "
        f"(skipped {len(summary['terminations_skipped'])}), "
        f"b2b end dates cleared {summary['b2b_end_dates_cleared']}"
    )
