"""Jednorazowa korekta zużycia MD po imporcie za sierpień 2026 (ticket 23.09.2026).

Przypadek BIK (klient 18, kontrakt 574): jedna osoba na dwóch kolejnych
zamówieniach MD — 4500030067 (linia 150, okres do 14.08) i jego następcy
4500029903 (linia 151, od 15.08). Arkusz za sierpień niósł dwa wiersze, każdy
z numerem zamówienia w „Uwagach": 13,75 MD na 4500030067 i 6,25 MD na
4500029903. Do tej poprawki import MD czytał numer wyłącznie u Polkomtela,
więc oba wiersze wpadły do „Wymaga przypisania", a przy ręcznym przypisaniu
drugiego reguła FIN-MD-01 przekierowała go na poprzednika i NADPISAŁA 13,75
liczbą 6,25. Następca nie dostał nic.

Drugi ślad tego samego defektu pochodzi z lipca: wiersz „22 MD, 4500030067"
przekroczył ówczesny budżet linii 150 (13,75 MD), więc 8,25 MD przeszło
automatycznie na 4500029903 — zamówienie, które zaczęło się 15.08 i w lipcu
nie istniało. Ręczne korekty MD (−8,25 na 150, +8,25 na 151) kompensowały to
przeniesienie. Po podniesieniu budżetu 4500030067 do 35,75 MD całe lipcowe
22 MD mieści się na zamówieniu, które arkusz wskazał.

Stan docelowy (ticket, kryteria akceptacji):

* 150: lipiec 22 MD, sierpień 13,75 MD, korekta ręczna 0 → wykorzystano
  35,75 / 35,75, pozostało 0,
* 151: brak lipca, sierpień 6,25 MD, korekta ręczna 0 → pozostało
  22,24 − 6,25 = 15,99,
* z historii znikają wpisy o nadpisaniu i o przeniesieniu 8,25 MD (migawka
  usuniętych wpisów zostaje pod ``DETAILS_KEY``), a obie karty dostają wpis
  korygujący.

Korekta rusza WYŁĄCZNIE, gdy stan produkcji zgadza się z tym z 23.09.2026
(liczby, numery, powiązania). Inaczej nic nie zapisuje i zostawia kod powodu —
ręczna poprawka człowieka wygrywa. Repo nie niesie nazwisk: tylko ID, numery
zamówień i liczby. Paragon (``REPAIR_MARKER``) ma same liczniki i ID.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
from app.models.md_consumption import (
    CONSUMPTION_SOURCE_IMPORT,
    ClientOrderMdConsumption,
)
from app.services.client_order_lines import recompute_remaining, record_event
from app.services.multi_consultant_orders import (
    EVENT_MANUAL_EDIT,
    format_md,
    quantize_md,
)

logger = logging.getLogger(__name__)

REPAIR_MARKER = "md_import_order_number_repair_2026_09_23"
DETAILS_KEY = "repair_details_md_import_order_number_2026_09_23"


@dataclass(frozen=True)
class RepairCase:
    client_id: int
    contract_id: int
    predecessor_order_id: int
    predecessor_group_id: int
    predecessor_number: str
    successor_order_id: int
    successor_group_id: int
    successor_number: str
    #: Miesiąc raportu (sierpień) i paczka, której wiersze wskazały oba zamówienia.
    report_month: str
    august_import_id: int
    #: Miesiąc poprzedni (lipiec) i jego paczka (22 MD z numerem poprzednika).
    previous_month: str
    july_import_id: int
    #: Stan sprzed korekty: {(order_id, miesiąc): MD}; brak klucza = brak wpisu.
    expected_before: dict[tuple[int, str], Decimal]
    #: Korekty ręczne sprzed korekty.
    expected_adjustments: dict[int, Decimal]
    #: Stan docelowy.
    target: dict[tuple[int, str], Decimal]
    #: Wpisy historii, które opisują nadpisanie i cofnięte przeniesienie.
    wrong_event_ids: tuple[int, ...]


def _d(value: str) -> Decimal:
    return Decimal(value)


TICKET_CASE = RepairCase(
    client_id=18,
    contract_id=574,
    predecessor_order_id=150,
    predecessor_group_id=55,
    predecessor_number="4500030067",
    successor_order_id=151,
    successor_group_id=56,
    successor_number="4500029903",
    report_month="2026-08",
    august_import_id=2,
    previous_month="2026-07",
    july_import_id=1,
    expected_before={
        (150, "2026-07"): _d("13.75"),
        (150, "2026-08"): _d("6.25"),
        (151, "2026-07"): _d("8.25"),
    },
    expected_adjustments={150: _d("-8.25"), 151: _d("8.25")},
    target={
        (150, "2026-07"): _d("22"),
        (150, "2026-08"): _d("13.75"),
        (151, "2026-08"): _d("6.25"),
    },
    # 511: „nadpisano wcześniejsze 13,75 MD" (wiersz 4500029903 na 4500030067);
    # 286/287: przeniesienie 8,25 MD za lipiec na 4500029903.
    wrong_event_ids=(511, 286, 287),
)


async def _consumptions(
    db: AsyncSession, order_ids: tuple[int, int]
) -> dict[tuple[int, str], ClientOrderMdConsumption]:
    rows = (
        await db.execute(
            select(ClientOrderMdConsumption)
            .where(ClientOrderMdConsumption.order_id.in_(order_ids))
            .with_for_update()
        )
    ).scalars()
    return {(row.order_id, row.period_month): row for row in rows}


def _values(
    rows: dict[tuple[int, str], ClientOrderMdConsumption],
) -> dict[tuple[int, str], Decimal]:
    return {
        key: quantize_md(Decimal(str(row.md_reported))) for key, row in rows.items()
    }


def _normalized(
    values: dict[tuple[int, str], Decimal],
) -> dict[tuple[int, str], Decimal]:
    return {key: quantize_md(value) for key, value in values.items()}


async def _check_identity(
    db: AsyncSession, case: RepairCase
) -> tuple[Optional[str], Optional[ClientOrder], Optional[ClientOrder]]:
    pred = await db.scalar(
        select(ClientOrder)
        .where(ClientOrder.id == case.predecessor_order_id)
        .with_for_update()
    )
    succ = await db.scalar(
        select(ClientOrder)
        .where(ClientOrder.id == case.successor_order_id)
        .with_for_update()
    )
    if pred is None or succ is None:
        return "order_missing", None, None
    for line, group_id in (
        (pred, case.predecessor_group_id),
        (succ, case.successor_group_id),
    ):
        if (
            line.contract_id != case.contract_id
            or line.client_id != case.client_id
            or line.order_group_id != group_id
            or line.md_total is None
        ):
            return "identity_mismatch", None, None
    groups = {
        g.id: g
        for g in (
            await db.execute(
                select(ClientOrderGroup).where(
                    ClientOrderGroup.id.in_(
                        (case.predecessor_group_id, case.successor_group_id)
                    )
                )
            )
        ).scalars()
    }
    pred_group = groups.get(case.predecessor_group_id)
    succ_group = groups.get(case.successor_group_id)
    if (
        pred_group is None
        or succ_group is None
        or pred_group.order_number.strip() != case.predecessor_number
        or succ_group.order_number.strip() != case.successor_number
        or succ_group.predecessor_group_id != case.predecessor_group_id
    ):
        return "group_mismatch", None, None
    return None, pred, succ


async def run_md_import_order_number_repair(
    db: AsyncSession,
    *,
    case: RepairCase = TICKET_CASE,
    marker: str = REPAIR_MARKER,
    details_key: str = DETAILS_KEY,
) -> Optional[dict[str, Any]]:
    """Wykonaj korektę. ``None`` = już była. Wołający commituje."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    if await db.get(AppSetting, marker) is not None:
        return None

    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "order_ids": [case.predecessor_order_id, case.successor_order_id],
        "applied": False,
        "skipped": None,
    }

    reason, pred, succ = await _check_identity(db, case)
    if reason is None:
        order_ids = (case.predecessor_order_id, case.successor_order_id)
        rows = await _consumptions(db, order_ids)
        current = _values(rows)
        adjustments = {
            pred.id: quantize_md(Decimal(str(pred.md_manual_adjustment or 0))),
            succ.id: quantize_md(Decimal(str(succ.md_manual_adjustment or 0))),
        }
        target = _normalized(case.target)
        months = (case.previous_month, case.report_month)
        relevant = {key: value for key, value in current.items() if key[1] in months}
        if relevant == target and all(v == 0 for v in adjustments.values()):
            reason = "already_ok"
        elif relevant != _normalized(case.expected_before) or adjustments != {
            key: quantize_md(value) for key, value in case.expected_adjustments.items()
        }:
            reason = "edited_since_snapshot"

    if reason is not None:
        summary["skipped"] = reason
        db.add(AppSetting(key=marker, value=summary))
        await db.flush()
        logger.info("md import order-number repair skipped: %s", reason)
        return summary

    # Migawka do ewentualnego odwrócenia — liczby i treść usuwanych wpisów.
    removed_events = list(
        (
            await db.execute(
                select(ClientOrderGroupEvent).where(
                    ClientOrderGroupEvent.id.in_(case.wrong_event_ids),
                    ClientOrderGroupEvent.group_id.in_(
                        (case.predecessor_group_id, case.successor_group_id)
                    ),
                )
            )
        ).scalars()
    )
    details: dict[str, Any] = {
        "consumptions_before": {
            f"{order_id}:{month}": str(value)
            for (order_id, month), value in sorted(current.items())
        },
        "adjustments_before": {str(k): str(v) for k, v in adjustments.items()},
        "removed_events": [
            {
                "id": event.id,
                "group_id": event.group_id,
                "order_id": event.order_id,
                "event_type": event.event_type,
                "description": event.description,
                "payload": event.payload,
                "created_at": event.created_at.isoformat()
                if event.created_at
                else None,
            }
            for event in removed_events
        ],
    }

    for key, row in rows.items():
        if key[1] not in months:
            continue
        if key not in case.target:
            await db.delete(row)
    for (order_id, month), value in case.target.items():
        row = rows.get((order_id, month))
        import_id = (
            case.august_import_id if month == case.report_month else case.july_import_id
        )
        if row is None:
            db.add(
                ClientOrderMdConsumption(
                    order_id=order_id,
                    period_month=month,
                    md_reported=value,
                    source=CONSUMPTION_SOURCE_IMPORT,
                    import_id=import_id,
                )
            )
        else:
            row.md_reported = value
            row.import_id = import_id
            row.source = CONSUMPTION_SOURCE_IMPORT
    pred.md_manual_adjustment = Decimal("0")
    succ.md_manual_adjustment = Decimal("0")
    for event in removed_events:
        await db.delete(event)
    await db.flush()

    pred_remaining = await recompute_remaining(db, pred, rebalance=False)
    succ_remaining = await recompute_remaining(db, succ, rebalance=False)

    record_event(
        db,
        group_id=case.predecessor_group_id,
        order_id=pred.id,
        event_type=EVENT_MANUAL_EDIT,
        description=(
            "Korekta importu MD (zgłoszenie 23.09.2026): sierpień 2026 = 13,75 MD "
            f"z wiersza z numerem {case.predecessor_number} (wiersz dla zamówienia "
            f"{case.successor_number} nie nadpisuje już tej wartości); lipiec "
            f"2026 = 22 MD w całości na tym zamówieniu (cofnięto przeniesienie "
            f"8,25 MD na {case.successor_number} i kompensującą je ręczną korektę). "
            f"Pozostało {format_md(pred_remaining)} MD."
        ),
        payload={
            "correction": REPAIR_MARKER,
            "md_remaining": str(pred_remaining),
        },
    )
    record_event(
        db,
        group_id=case.successor_group_id,
        order_id=succ.id,
        event_type=EVENT_MANUAL_EDIT,
        description=(
            "Korekta importu MD (zgłoszenie 23.09.2026): sierpień 2026 = 6,25 MD "
            f"z wiersza z numerem {case.successor_number}; usunięto błędne zużycie "
            f"za lipiec 2026 przeniesione z zamówienia {case.predecessor_number} "
            "(to zamówienie zaczęło się 15.08.2026) i kompensującą je ręczną "
            f"korektę. Pozostało {format_md(succ_remaining)} MD."
        ),
        payload={
            "correction": REPAIR_MARKER,
            "md_remaining": str(succ_remaining),
        },
    )

    summary.update(
        applied=True,
        predecessor_remaining=str(pred_remaining),
        successor_remaining=str(succ_remaining),
        removed_event_ids=[event["id"] for event in details["removed_events"]],
    )
    db.add(AppSetting(key=marker, value=summary))
    db.add(AppSetting(key=details_key, value=details))
    await db.flush()
    logger.info(
        "md import order-number repair applied: orders %s remaining %s/%s",
        summary["order_ids"],
        pred_remaining,
        succ_remaining,
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    if summary.get("skipped"):
        return f"skipped ({summary['skipped']}) for orders {summary['order_ids']}"
    return (
        f"applied for orders {summary['order_ids']}: remaining "
        f"{summary['predecessor_remaining']} / {summary['successor_remaining']} MD, "
        f"removed events {summary['removed_event_ids']}"
    )
