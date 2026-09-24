"""Jednorazowa korekta importu MD za sierpień 2026 (ticket 1.1, 24.09.2026).

Przypadek BIK (klient 18, kontrakt 572): jedna osoba, dwa wiersze raportu
za sierpień z dwoma numerami zamówień — 2 MD na 4500030197 (linia 145,
grupa 51) i 19 MD na 4500030845 (linia 625, grupa 92). Import z 23.09.2026
(paczka 2) dopasowywał wiersze po samym nazwisku, a zamówienie 4500030845
wystawiono 3.09 — jego okres nie obejmował sierpnia, więc jedynym
kandydatem była linia 145. Oba wiersze zsumowały się na niej (21 MD), saldo
spadło do −19 MD, a zamówienie 4500030197 zakończyło się automatycznie
23.09.2026 na błędnym saldzie.

Stan docelowy:

* 145: sierpień 2 MD → wykorzystano 25 / 25, pozostało 0,
* 625: sierpień 19 MD → pozostało 42 − 19 = 23,
* wiersz 36 paczki 2 wskazuje linię 625,
* zamówienie 4500030197 zakończone z datą ostatniego dnia miesiąca ostatniego
  zejścia (31.08.2026), obie karty z wpisem korekty.

Korekta rusza WYŁĄCZNIE, gdy stan produkcji zgadza się z tym z 24.09.2026.
Inaczej nic nie zapisuje i zostawia kod powodu — ręczna poprawka człowieka
wygrywa. Repo nie niesie nazwisk: tylko ID, numery i liczby. Paragon
(``REPAIR_MARKER``) ma same liczniki i ID; stan sprzed korekty leży pod
``DETAILS_KEY`` (klucz innego kształtu — publiczny workflow go nie drukuje).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.client_order import ClientOrder
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    ClientOrderGroup,
)
from app.models.md_consumption import (
    CONSUMPTION_SOURCE_IMPORT,
    ClientOrderMdConsumption,
    MdConsumptionImportRow,
)
from app.services.client_order_lines import recompute_remaining, record_event
from app.services.contract_lifecycle import lock_contract_then_orders
from app.services.multi_consultant_orders import (
    EVENT_MANUAL_EDIT,
    format_md,
    quantize_md,
)
from app.services.order_md_exhaustion import (
    MD_EXHAUSTED_CLOSURE_REASON,
    closed_by_md_exhaustion,
)

logger = logging.getLogger(__name__)

REPAIR_MARKER = "md_import_split_rows_repair_2026_09_24"
DETAILS_KEY = "repair_details_md_import_split_rows_2026_09_24"


@dataclass(frozen=True)
class SplitRowsCase:
    client_id: int
    contract_id: int
    #: Zamówienie, na które błędnie trafiły oba wiersze.
    wrong_order_id: int
    wrong_group_id: int
    wrong_number: str
    #: Zamówienie wskazane w drugim wierszu.
    right_order_id: int
    right_group_id: int
    right_number: str
    report_month: str
    import_id: int
    #: Numer wiersza arkusza, który wskazał ``right_number``.
    moved_row_number: int
    #: Stan sprzed korekty: {(order_id, miesiąc): MD}; brak klucza = brak wpisu.
    expected_before: dict[tuple[int, str], Decimal]
    #: Stan docelowy miesiąca raportu.
    target: dict[tuple[int, str], Decimal]
    #: Dzień, z którym zamówienie zakończyło się na błędnym saldzie.
    wrong_closure_date: date


def _d(value: str) -> Decimal:
    return Decimal(value)


TICKET_CASE = SplitRowsCase(
    client_id=18,
    contract_id=572,
    wrong_order_id=145,
    wrong_group_id=51,
    wrong_number="4500030197",
    right_order_id=625,
    right_group_id=92,
    right_number="4500030845",
    report_month="2026-08",
    import_id=2,
    moved_row_number=36,
    expected_before={
        (145, "2026-07"): _d("23"),
        (145, "2026-08"): _d("21"),
    },
    target={
        (145, "2026-08"): _d("2"),
        (625, "2026-08"): _d("19"),
    },
    wrong_closure_date=date(2026, 9, 23),
)


def _month_end(period_month: str) -> date:
    import calendar

    year, month = (int(part) for part in period_month.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


async def _consumptions(
    db: AsyncSession, order_ids: tuple[int, ...]
) -> dict[tuple[int, str], ClientOrderMdConsumption]:
    rows = (
        await db.execute(
            select(ClientOrderMdConsumption)
            .where(ClientOrderMdConsumption.order_id.in_(order_ids))
            .with_for_update()
        )
    ).scalars()
    return {(row.order_id, row.period_month): row for row in rows}


async def _check_identity(
    db: AsyncSession, case: SplitRowsCase
) -> tuple[Optional[str], dict[str, Any]]:
    # Kolejność blokad writerów zamówień: kontrakt → zamówienia → grupy.
    await lock_contract_then_orders(
        db, order_ids=[case.wrong_order_id, case.right_order_id]
    )
    lines = {
        line.id: line
        for line in (
            await db.execute(
                select(ClientOrder)
                .where(ClientOrder.id.in_((case.wrong_order_id, case.right_order_id)))
                .order_by(ClientOrder.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars()
    }
    wrong = lines.get(case.wrong_order_id)
    right = lines.get(case.right_order_id)
    if wrong is None or right is None:
        return "order_missing", {}
    for line, group_id in (
        (wrong, case.wrong_group_id),
        (right, case.right_group_id),
    ):
        if (
            line.contract_id != case.contract_id
            or line.client_id != case.client_id
            or line.order_group_id != group_id
            or line.md_total is None
            or quantize_md(Decimal(str(line.md_manual_adjustment or 0))) != 0
        ):
            return "identity_mismatch", {}
    groups = {
        g.id: g
        for g in (
            await db.execute(
                select(ClientOrderGroup)
                .where(
                    ClientOrderGroup.id.in_((case.wrong_group_id, case.right_group_id))
                )
                .order_by(ClientOrderGroup.id)
                .with_for_update()
            )
        ).scalars()
    }
    wrong_group = groups.get(case.wrong_group_id)
    right_group = groups.get(case.right_group_id)
    if (
        wrong_group is None
        or right_group is None
        or wrong_group.order_number.strip() != case.wrong_number
        or right_group.order_number.strip() != case.right_number
        or wrong_group.client_id != case.client_id
        or right_group.client_id != case.client_id
    ):
        return "group_mismatch", {}
    if right_group.status != GROUP_STATUS_ACTIVE or not (
        closed_by_md_exhaustion(wrong_group)
        and wrong_group.closure_date == case.wrong_closure_date
    ):
        return "group_state_changed", {}
    moved = await db.scalar(
        select(MdConsumptionImportRow)
        .where(
            MdConsumptionImportRow.import_id == case.import_id,
            MdConsumptionImportRow.row_number == case.moved_row_number,
        )
        .with_for_update()
    )
    if (
        moved is None
        or moved.matched_order_id != case.wrong_order_id
        or (moved.order_number_hint or "").strip() != case.right_number
        or quantize_md(Decimal(str(moved.md_reported)))
        != quantize_md(case.target[(case.right_order_id, case.report_month)])
    ):
        return "import_row_mismatch", {}
    return None, {
        "wrong": wrong,
        "right": right,
        "wrong_group": wrong_group,
        "right_group": right_group,
        "moved": moved,
    }


async def run_md_import_split_rows_repair(
    db: AsyncSession,
    *,
    case: SplitRowsCase = TICKET_CASE,
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
        "order_ids": [case.wrong_order_id, case.right_order_id],
        "group_ids": [case.wrong_group_id, case.right_group_id],
        "applied": False,
        "skipped": None,
    }

    reason, found = await _check_identity(db, case)
    rows: dict[tuple[int, str], ClientOrderMdConsumption] = {}
    if reason is None:
        rows = await _consumptions(db, (case.wrong_order_id, case.right_order_id))
        current = {
            key: quantize_md(Decimal(str(row.md_reported))) for key, row in rows.items()
        }
        expected = {key: quantize_md(v) for key, v in case.expected_before.items()}
        if current != expected:
            reason = "edited_since_snapshot"

    if reason is not None:
        summary["skipped"] = reason
        db.add(AppSetting(key=marker, value=summary))
        await db.flush()
        logger.info("md import split-rows repair skipped: %s", reason)
        return summary

    wrong: ClientOrder = found["wrong"]
    right: ClientOrder = found["right"]
    wrong_group: ClientOrderGroup = found["wrong_group"]
    moved: MdConsumptionImportRow = found["moved"]
    details = {
        "consumptions_before": {
            f"{order_id}:{month}": str(row.md_reported)
            for (order_id, month), row in sorted(rows.items())
        },
        "remaining_before": {
            str(wrong.id): str(wrong.md_remaining),
            str(right.id): str(right.md_remaining),
        },
        "wrong_group_closure_before": {
            "status": wrong_group.status,
            "closure_date": wrong_group.closure_date.isoformat()
            if wrong_group.closure_date
            else None,
        },
        "moved_row_id": moved.id,
    }

    for (order_id, month), value in case.target.items():
        row = rows.get((order_id, month))
        if row is None:
            db.add(
                ClientOrderMdConsumption(
                    order_id=order_id,
                    period_month=month,
                    md_reported=value,
                    source=CONSUMPTION_SOURCE_IMPORT,
                    import_id=case.import_id,
                )
            )
        else:
            row.md_reported = value
            row.import_id = case.import_id
            row.source = CONSUMPTION_SOURCE_IMPORT
    moved.matched_order_id = case.right_order_id
    await db.flush()

    wrong_remaining = await recompute_remaining(db, wrong, rebalance=False)
    right_remaining = await recompute_remaining(db, right, rebalance=False)

    # Zamówienie kończy się z ostatnim dniem miesiąca ostatniego zejścia —
    # ta sama reguła co automatyczne zakończenie (ticket 4500030067).
    last_month = await db.scalar(
        select(ClientOrderMdConsumption.period_month)
        .join(ClientOrder, ClientOrder.id == ClientOrderMdConsumption.order_id)
        .where(ClientOrder.order_group_id == wrong_group.id)
        .order_by(ClientOrderMdConsumption.period_month.desc())
        .limit(1)
    )
    closure_date = _month_end(last_month) if last_month else case.wrong_closure_date
    wrong_group.status = GROUP_STATUS_COMPLETED
    wrong_group.closure_reason = MD_EXHAUSTED_CLOSURE_REASON
    wrong_group.closed_by_user_id = None
    wrong_group.closure_date = closure_date

    label = case.report_month
    record_event(
        db,
        group_id=case.wrong_group_id,
        order_id=wrong.id,
        event_type=EVENT_MANUAL_EDIT,
        description=(
            f"Korekta importu MD (ticket 1.1, 24.09.2026): za {label} "
            f"zaksięgowano 2 MD z wiersza z numerem {case.wrong_number}; "
            f"19 MD z wiersza z numerem {case.right_number} przeniesiono na "
            f"zamówienie {case.right_number}. Pozostało "
            f"{format_md(wrong_remaining)} MD. Zamówienie zakończone z dniem "
            f"{closure_date.isoformat()} (ostatni miesiąc zejścia), "
            f"wcześniej {case.wrong_closure_date.isoformat()}."
        ),
        payload={
            "correction": REPAIR_MARKER,
            "md_remaining": str(wrong_remaining),
            "closure_date": closure_date.isoformat(),
        },
    )
    record_event(
        db,
        group_id=case.right_group_id,
        order_id=right.id,
        event_type=EVENT_MANUAL_EDIT,
        description=(
            f"Korekta importu MD (ticket 1.1, 24.09.2026): za {label} "
            f"zaksięgowano 19 MD z wiersza z numerem {case.right_number} "
            f"(import z 23.09.2026 zapisał je błędnie na {case.wrong_number}). "
            f"Pozostało {format_md(right_remaining)} MD."
        ),
        payload={
            "correction": REPAIR_MARKER,
            "md_remaining": str(right_remaining),
        },
    )

    summary.update(
        applied=True,
        wrong_remaining=str(wrong_remaining),
        right_remaining=str(right_remaining),
        closure_date=closure_date.isoformat(),
    )
    db.add(AppSetting(key=marker, value=summary))
    db.add(AppSetting(key=details_key, value=details))
    await db.flush()
    logger.info(
        "md import split-rows repair applied: orders %s remaining %s/%s",
        summary["order_ids"],
        wrong_remaining,
        right_remaining,
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    if summary.get("skipped"):
        return f"skipped ({summary['skipped']}) for orders {summary['order_ids']}"
    return (
        f"applied for orders {summary['order_ids']}: remaining "
        f"{summary['wrong_remaining']} / {summary['right_remaining']} MD, "
        f"closure {summary['closure_date']}"
    )
