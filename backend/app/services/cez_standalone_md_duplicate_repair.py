"""Jednorazowe anulowanie zdublowanych zamówień jednoosobowych u CeZ (09.2026).

Import danych startowych Centrum e-Zdrowia (16.09.2026) założył zamówienia MD
jako GRUPY z liniami konsultantów i anulował stare szkice zamówień — ale dwie
osoby zostały z dawnym, samodzielnym zamówieniem na tym samym kontrakcie. Na
zakładce „Zamówienia" pokazywały się więc dwa razy: jako karta kontraktora
bez zużycia MD (samodzielne zamówienia MD nie rozliczają zejść — import
zużycia czyta wyłącznie linie grup) i jako linia grupy z właściwym budżetem.
To dokładnie przypadek ``periodic_duplicates_group_line`` z audytu
``/api/admin/engagement-inventory``: dwa równoległe zapisy tej samej
współpracy.

Korekta idzie tą samą drogą co ``DELETE /api/clients/{c}/orders/{o}`` na
zamówieniu niebędącym szkicem: ``status = cancelled`` (rekord zostaje
w historii), wpis ``order_cancelled`` na kliencie i wpis w Historii zdarzeń
(``order.delete``). Szkic też jest ANULOWANY, a nie kasowany — korekta ma być
odwracalna. Potem kontrakt synchronizuje się z zamówieniami jak po zwykłym
zapisie, a braki kolejnego zamówienia dostają odświeżenie.

Pozycja jest wykonywana WYŁĄCZNIE wtedy, gdy stan produkcji zgadza się
z tym, co widać w zgłoszeniu: kontrakt należy do klienta, jest żywy i ma
żywą linię w aktywnej grupie o wskazanym numerze. Inaczej zostaje nietknięta
z kodem powodu — anulowanie jedynego zapisu współpracy byłoby gorsze niż
duplikat.

Repo nie niesie nazwisk: tylko identyfikatory kontraktów i klienta oraz numer
zamówienia grupowego. Paragon pod kluczem ``NNNN_…`` ma wyłącznie liczniki,
ID i kody powodów; migawka anulowanych zamówień (tytuły z nazwiskami) leży
pod kluczem innego kształtu, którego publiczny workflow ``migration-receipts``
nie wydrukuje.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus
from app.services.contract_order_sync import resync_contract_safely
from app.services.critical_events import record_executed
from app.services.order_gaps import refresh_order_gaps_safely

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0325_cez_standalone_md_duplicates"
DETAILS_KEY = "repair_details_0325_cez_standalone_md_duplicates"
SOURCE = REPAIR_MARKER

_OPEN_ORDER_STATUSES = (
    ClientOrderStatus.draft,
    ClientOrderStatus.active,
    ClientOrderStatus.paused,
)
_LIVE_CONTRACT_STATUSES = (ContractStatus.active, ContractStatus.ending)


@dataclass(frozen=True)
class StandaloneDuplicate:
    """Kontrakt, którego samodzielne zamówienia dublują linię grupy."""

    client_id: int
    contract_id: int
    group_order_number: str


# Zgłoszenie 17.09.2026: dwie osoby u Centrum e-Zdrowia (klient 115) — obie są
# liniami zamówienia grupowego CeZ/242/2025 z importu danych startowych.
TICKET_DUPLICATES: tuple[StandaloneDuplicate, ...] = (
    StandaloneDuplicate(
        client_id=115, contract_id=407, group_order_number="CeZ/242/2025"
    ),
    StandaloneDuplicate(
        client_id=115, contract_id=408, group_order_number="CeZ/242/2025"
    ),
)


async def _live_group_line_ids(
    db: AsyncSession, spec: StandaloneDuplicate
) -> list[int]:
    rows = await db.execute(
        select(ClientOrder.id)
        .join(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
        .where(
            ClientOrder.contract_id == spec.contract_id,
            ClientOrder.client_id == spec.client_id,
            ClientOrder.status == ClientOrderStatus.active,
            ClientOrderGroup.client_id == spec.client_id,
            ClientOrderGroup.order_number == spec.group_order_number,
            ClientOrderGroup.status == "active",
        )
        .order_by(ClientOrder.id)
    )
    return list(rows.scalars())


def _skip(spec: StandaloneDuplicate, reason: str) -> dict[str, Any]:
    return {
        "contract_id": spec.contract_id,
        "skipped": reason,
        "cancelled_order_ids": [],
    }


async def _cancel_one(
    db: AsyncSession, spec: StandaloneDuplicate
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    contract = await db.scalar(
        select(Contract).where(Contract.id == spec.contract_id).with_for_update()
    )
    if contract is None:
        return _skip(spec, "contract_missing"), []
    if contract.client_id != spec.client_id:
        return _skip(spec, "contract_client_mismatch"), []
    if contract.status not in _LIVE_CONTRACT_STATUSES:
        return _skip(spec, "contract_not_live"), []

    group_line_ids = await _live_group_line_ids(db, spec)
    if not group_line_ids:
        return _skip(spec, "no_live_group_line"), []

    standalone = list(
        (
            await db.execute(
                select(ClientOrder)
                .where(
                    ClientOrder.contract_id == spec.contract_id,
                    ClientOrder.client_id == spec.client_id,
                    ClientOrder.order_group_id.is_(None),
                    ClientOrder.status.in_(_OPEN_ORDER_STATUSES),
                )
                .order_by(ClientOrder.id)
                .with_for_update()
            )
        ).scalars()
    )
    if not standalone:
        return _skip(spec, "no_open_standalone_order"), []

    snapshots: list[dict[str, Any]] = []
    cancelled: list[dict[str, Any]] = []
    for order in standalone:
        previous = getattr(order.status, "value", order.status)
        snapshots.append(
            {
                "order_id": order.id,
                "contract_id": order.contract_id,
                "status": previous,
                "title": order.title,
                "order_type": getattr(order.order_type, "value", order.order_type),
                "start_date": order.start_date.isoformat()
                if order.start_date
                else None,
                "end_date": order.end_date.isoformat() if order.end_date else None,
                "has_file": order.file_path is not None,
            }
        )
        order.status = ClientOrderStatus.cancelled
        cancelled.append({"order_id": order.id, "previous_status": previous})
        db.add(
            Activity(
                entity_type="client",
                entity_id=spec.client_id,
                action="order_cancelled",
                user_id=None,
                external_source=SOURCE,
                external_id=f"cancel:{order.id}",
                details={
                    "order_id": order.id,
                    "source": SOURCE,
                    "duplicate_of_group_line_ids": group_line_ids,
                },
            )
        )
        await record_executed(
            db,
            actor=None,
            event_type="order.delete",
            entity_type="order",
            entity_id=order.id,
            entity_label=f"Zamówienie #{order.id}",
            client_id=spec.client_id,
            reason_code="duplicate_of_group_line",
            reason=(
                "Zamówienie anulowane — dublowało linię zamówienia grupowego "
                f"{spec.group_order_number} tej samej osoby (korekta danych "
                "ze zgłoszenia). Rekord zostaje w historii."
            ),
            details={
                "previous_status": previous,
                "group_line_ids": group_line_ids,
                "source": SOURCE,
            },
        )
    await db.flush()
    await resync_contract_safely(db, contract, actor_id=None)
    await refresh_order_gaps_safely(db, contract_ids=[contract.id])

    return (
        {
            "contract_id": spec.contract_id,
            "skipped": None,
            "cancelled_order_ids": [item["order_id"] for item in cancelled],
            "previous_statuses": [item["previous_status"] for item in cancelled],
            "group_line_ids": group_line_ids,
        },
        snapshots,
    )


async def run_cez_standalone_md_duplicate_repair(
    db: AsyncSession,
    *,
    duplicates: tuple[StandaloneDuplicate, ...] = TICKET_DUPLICATES,
    marker: str = REPAIR_MARKER,
    details_key: str = DETAILS_KEY,
) -> Optional[dict[str, Any]]:
    """Anuluj duplikaty ze zgłoszenia. ``None`` = już było. Wołający commituje."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    # Stary kontener przy wdrożeniu trzyma blokady zamówień; bez limitu start
    # czekałby w nieskończoność. Przekroczenie = rollback, następny start ponawia.
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    if await db.get(AppSetting, marker) is not None:
        return None

    results: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    for spec in duplicates:
        item, snapshot = await _cancel_one(db, spec)
        results.append(item)
        snapshots.extend(snapshot)

    applied = [item for item in results if item["skipped"] is None]
    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "contracts_requested": len(duplicates),
        "contracts_applied": len(applied),
        "orders_cancelled": sum(len(item["cancelled_order_ids"]) for item in applied),
        "applied": applied,
        "skipped": [
            {"contract_id": item["contract_id"], "reason": item["skipped"]}
            for item in results
            if item["skipped"] is not None
        ],
    }
    db.add(AppSetting(key=marker, value=summary))
    db.add(AppSetting(key=details_key, value={"cancelled_orders": snapshots}))
    await db.flush()
    logger.info(
        "cez standalone md duplicates: %s orders cancelled on %s/%s contracts",
        summary["orders_cancelled"],
        len(applied),
        len(duplicates),
    )
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    cancelled = ", ".join(
        f"{item['contract_id']}:{item['cancelled_order_ids']}"
        for item in summary["applied"]
    )
    skipped = ", ".join(
        f"{item['contract_id']}:{item['reason']}" for item in summary["skipped"]
    )
    return (
        f"cancelled {summary['orders_cancelled']} order(s) on "
        f"{summary['contracts_applied']}/{summary['contracts_requested']} contracts"
        + (f" [{cancelled}]" if cancelled else "")
        + (f" (skipped {skipped})" if skipped else "")
    )
