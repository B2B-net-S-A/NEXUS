"""Jednorazowe usunięcie zdublowanego zamówienia z odwróconym okresem (28.09.2026).

Zgłoszenie: Alior, jedna osoba ma dwa przyszłe zamówienia o tym samym numerze
— poprawne 01.10–31.12.2026 (z maila) i drugie 01.01.2027 → 31.12.2026, które
16.09 założyło okno „Dodaj przedłużenie”: start podstawiło jako dzień po
ostatnim zamówieniu, a koniec wziął z tego samego PDF-a. Od 24.09 (#1787)
formularze odrzucają odwrócony okres i duplikat numeru; to zamówienie zostało.

Korekta idzie tą samą drogą co ``DELETE /api/clients/{c}/orders/{o}``:
blokada kontrakt → zamówienie, odmowa przy rozliczeniach, zamknięcie kart
braków, zdjęcie kroku stawki klienta, trwałe usunięcie, wpis w Historii
zdarzeń (``order.delete``), synchronizacja kontraktu z pozostałymi
zamówieniami. Plik PDF zamówienia kasuje wołający PO commicie (jak trasa).

Pozycja jest wykonywana WYŁĄCZNIE, gdy stan produkcji zgadza się ze
zgłoszeniem: identyfikatory, numer, obie daty, nikt nie edytował zamówienia
po założeniu i obok istnieje poprawne zamówienie o tym numerze. Inaczej
zostaje nietknięta z kodem powodu. Paragon: liczniki, ID, kody powodów.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract
from app.services.contract_lifecycle import lock_contract_then_orders
from app.services.contract_order_sync import (
    detach_order_rate_steps,
    resync_contract_safely,
)
from app.services.critical_events import record_executed
from app.services.order_gaps import (
    close_gaps_of_deleted_orders,
    refresh_order_gaps_safely,
)
from app.services.order_settlements import settlement_blockers

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0397_alior_reversed_period_order"
SOURCE = REPAIR_MARKER


@dataclass(frozen=True)
class ReversedOrderTarget:
    order_id: int
    contract_id: int
    candidate_id: int
    client_id: int
    title: str
    start_date: date
    end_date: date
    keep_order_id: int
    keep_start_date: date
    keep_end_date: date


# Zgłoszenie 28.09.2026 (Alior): zamówienie #653 dubluje #630.
TICKET_TARGETS: tuple[ReversedOrderTarget, ...] = (
    ReversedOrderTarget(
        order_id=653,
        contract_id=646,
        candidate_id=10010,
        client_id=39,
        title="OIT/0569/2026/ITVM",
        start_date=date(2027, 1, 1),
        end_date=date(2026, 12, 31),
        keep_order_id=630,
        keep_start_date=date(2026, 10, 1),
        keep_end_date=date(2026, 12, 31),
    ),
)


def _skip(target: ReversedOrderTarget, reason: str) -> dict[str, Any]:
    return {"order_id": target.order_id, "skipped": reason}


async def _delete_one(
    db: AsyncSession, target: ReversedOrderTarget
) -> tuple[dict[str, Any], Optional[str]]:
    await lock_contract_then_orders(db, order_ids=[target.order_id])
    order = await db.scalar(
        select(ClientOrder).where(ClientOrder.id == target.order_id).with_for_update()
    )
    if order is None:
        return _skip(target, "order_missing"), None
    if (
        order.contract_id != target.contract_id
        or order.client_id != target.client_id
        or order.order_group_id is not None
    ):
        return _skip(target, "identity_mismatch"), None
    if (
        order.title != target.title
        or order.start_date != target.start_date
        or order.end_date != target.end_date
    ):
        return _skip(target, "order_changed"), None
    if order.status == ClientOrderStatus.cancelled:
        return _skip(target, "order_cancelled"), None
    if (
        order.created_at is not None
        and order.updated_at is not None
        and order.updated_at != order.created_at
    ):
        return _skip(target, "edited_after_creation"), None

    contract = await db.get(Contract, target.contract_id)
    if contract is None or contract.candidate_id != target.candidate_id:
        return _skip(target, "identity_mismatch"), None

    kept = await db.get(ClientOrder, target.keep_order_id)
    if (
        kept is None
        or kept.contract_id != target.contract_id
        or kept.title != target.title
        or kept.start_date != target.keep_start_date
        or kept.end_date != target.keep_end_date
        or kept.status == ClientOrderStatus.cancelled
    ):
        return _skip(target, "correct_order_missing"), None

    if await settlement_blockers(db, [order.id]):
        return _skip(target, "has_settlements"), None

    po_path = order.file_path
    await close_gaps_of_deleted_orders(db, [order.id], actor_id=None)
    await detach_order_rate_steps(db, order)
    await db.delete(order)
    db.add(
        Activity(
            entity_type="client",
            entity_id=target.client_id,
            action="order_deleted",
            user_id=None,
            external_source=SOURCE,
            external_id=f"delete:{target.order_id}",
            details={
                "order_id": target.order_id,
                "source": SOURCE,
                "kept_order_id": target.keep_order_id,
            },
        )
    )
    await record_executed(
        db,
        actor=None,
        event_type="order.delete",
        entity_type="order",
        entity_id=target.order_id,
        entity_label=f"Zamówienie #{target.order_id}",
        client_id=target.client_id,
        reason_code="reversed_period_duplicate",
        reason=(
            "Zamówienie usunięte trwale — okres odwrócony (data od późniejsza "
            "niż data do) i ten sam numer co zamówienie "
            f"#{target.keep_order_id} tej osoby (korekta danych ze zgłoszenia)."
        ),
        details={"kept_order_id": target.keep_order_id, "source": SOURCE},
    )
    await db.flush()
    await resync_contract_safely(db, contract, actor_id=None)
    await refresh_order_gaps_safely(db, contract_ids=[contract.id])
    return (
        {
            "order_id": target.order_id,
            "skipped": None,
            "contract_id": target.contract_id,
            "kept_order_id": target.keep_order_id,
        },
        po_path,
    )


async def run_alior_reversed_order_repair(
    db: AsyncSession,
    *,
    targets: tuple[ReversedOrderTarget, ...] = TICKET_TARGETS,
    marker: str = REPAIR_MARKER,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Usuń zamówienia ze zgłoszenia.

    Zwraca (paragon albo ``None`` = już było, ścieżki plików PDF do skasowania
    po commicie). Wołający commituje (``commit_order_write``).
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    # Stary kontener przy wdrożeniu trzyma blokady zamówień; bez limitu start
    # czekałby w nieskończoność. Przekroczenie = rollback, następny start ponawia.
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    if await db.get(AppSetting, marker) is not None:
        return None, []

    results: list[dict[str, Any]] = []
    po_paths: list[str] = []
    for target in targets:
        item, po_path = await _delete_one(db, target)
        results.append(item)
        if po_path:
            po_paths.append(po_path)

    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(targets),
        "deleted_order_ids": [r["order_id"] for r in results if r["skipped"] is None],
        "skipped": [
            {"order_id": r["order_id"], "reason": r["skipped"]}
            for r in results
            if r["skipped"] is not None
        ],
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info(
        "alior reversed order repair: deleted %s/%s",
        len(summary["deleted_order_ids"]),
        len(targets),
    )
    return summary, po_paths


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    skipped = ", ".join(
        f"{item['order_id']}:{item['reason']}" for item in summary["skipped"]
    )
    return f"deleted orders {summary['deleted_order_ids']}" + (
        f"; skipped {skipped}" if skipped else ""
    )
