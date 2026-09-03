"""Daily scanner — flippuje statusy + emituje notyfikacje expiry dla framework
contracts i client orders.

Lifecycle:
1. ``ClientFrameworkContract``: status=active, expiry_date<today → status=expired
2. ``ClientOrder``: status=active, end_date<today → status=completed
   (POZA liniami MD — te kończy budżet, nie kalendarz; patrz ``_promote_statuses``)
3. ``Contract``: ended/ending + aktywny Order obejmujący dziś → active
4. Dispatch notyfikacji expiry:
   - 30/14/7 dni przed ``ClientFrameworkContract.expiry_date`` (status=active)
   - 30/14/7 dni przed ``ClientOrder.end_date`` (status=active)

Odbiorcy: aktywni admini globalnie oraz aktywni Delivery Leadzi wyłącznie dla
przypisanych klientów i tylko z effective ``delivery >= read``.

Dedup: ``Notification.related_entity_*`` + ``notification_type`` per próg
(jeden alert 30d + jeden 14d + jeden 7d na entity per timeline).

Wzorzec: `app/tasks/contract_alerts.py` — daily loop z 24h sleep.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract
from app.models.notification import Notification, NotificationType
from app.services.contract_lifecycle import (
    reconcile_contracts_to_live_orders,
)
from app.services.client_identity import client_display_name_expression
from app.services.delivery_alert_recipients import (
    DeliveryAlertRecipientScope,
    load_delivery_alert_recipient_scope,
)
from app.services.order_group_lifecycle import materialize_scheduled_order_groups

logger = logging.getLogger(__name__)


_INTERVAL_HOURS = 24.0
_THRESHOLDS_DAYS = (30, 14, 7)

_FC_NTYPE_BY_DAY = {
    30: NotificationType.framework_contract_expiring_30d,
    14: NotificationType.framework_contract_expiring_14d,
    7: NotificationType.framework_contract_expiring_7d,
}
_ORDER_NTYPE_BY_DAY = {
    30: NotificationType.client_order_ending_30d,
    14: NotificationType.client_order_ending_14d,
    7: NotificationType.client_order_ending_7d,
}


async def _already_notified(
    db: AsyncSession,
    *,
    user_id: int,
    related_entity_type: str,
    related_entity_id: int,
    ntype: NotificationType,
) -> bool:
    res = await db.execute(
        select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.related_entity_type == related_entity_type,
            Notification.related_entity_id == related_entity_id,
            Notification.notification_type == ntype,
        )
    )
    return res.scalar_one_or_none() is not None


async def _promote_statuses(
    db: AsyncSession, *, business_day: date | None = None
) -> tuple[int, int, int, int]:
    """Materializuj dzienne przejścia FC, Order i przyszłych grup."""
    today = business_day or business_today()

    fc_expired = await db.execute(
        update(ClientFrameworkContract)
        .where(
            ClientFrameworkContract.status == FrameworkContractStatus.active,
            ClientFrameworkContract.expiry_date.is_not(None),
            ClientFrameworkContract.expiry_date < today,
        )
        .values(status=FrameworkContractStatus.expired)
    )
    order_completed = await db.execute(
        update(ClientOrder)
        .where(
            ClientOrder.status == ClientOrderStatus.active,
            ClientOrder.end_date.is_not(None),
            ClientOrder.end_date < today,
            # Zamówienie rozliczane w MD kończy BUDŻET, nie kalendarz. Data
            # nadal opisuje okres obowiązywania i steruje alertami wygasania
            # niżej, ale nie domyka linii: konsultant z niewykorzystanymi MD
            # pracuje dalej, a zamknięty przez skaner wypadał z importu
            # zużycia (`active_md_lines` pyta o linie aktywne), czyli MD
            # przestawały się odejmować i budżet zamierał na ostatniej
            # wartości. Statusem linii MD steruje wyłącznie
            # `client_order_lines.sync_md_line_status`.
            ClientOrder.md_total.is_(None),
        )
        .values(status=ClientOrderStatus.completed)
    )
    groups_promoted = await materialize_scheduled_order_groups(db, today=today)
    contracts_reconciled = await reconcile_contracts_to_live_orders(
        db,
        today=today,
    )
    return (
        fc_expired.rowcount or 0,
        order_completed.rowcount or 0,
        groups_promoted,
        contracts_reconciled,
    )


async def _scan_framework_contracts(
    db: AsyncSession, recipient_scope: DeliveryAlertRecipientScope
) -> int:
    """Zwraca # nowych notyfikacji."""
    today = date.today()
    sent = 0
    for days in _THRESHOLDS_DAYS:
        target_date = today + timedelta(days=days)
        rows = list(
            (
                await db.execute(
                    select(ClientFrameworkContract).where(
                        ClientFrameworkContract.status
                        == FrameworkContractStatus.active,
                        ClientFrameworkContract.expiry_date == target_date,
                    )
                )
            ).scalars()
        )
        ntype = _FC_NTYPE_BY_DAY[days]
        for fc in rows:
            for user_id in recipient_scope.for_client(fc.client_id):
                if await _already_notified(
                    db,
                    user_id=user_id,
                    related_entity_type="client_framework_contract",
                    related_entity_id=fc.id,
                    ntype=ntype,
                ):
                    continue
                db.add(
                    Notification(
                        user_id=user_id,
                        title=f"Umowa ramowa wygasa za {days} dni",
                        message=(
                            f"'{fc.name}' wygasa {fc.expiry_date.isoformat()}. "
                            "Skontaktuj się z klientem, aby przedyskutować przedłużenie."
                        ),
                        notification_type=ntype,
                        related_entity_type="client_framework_contract",
                        related_entity_id=fc.id,
                        link=f"/clients/{fc.client_id}?tab=framework-contracts",
                    )
                )
                sent += 1
    return sent


async def _scan_orders(
    db: AsyncSession, recipient_scope: DeliveryAlertRecipientScope
) -> int:
    today = date.today()
    sent = 0
    for days in _THRESHOLDS_DAYS:
        target_date = today + timedelta(days=days)
        # Join Order → Contract → Candidate + Client dla candidate_name + client_name w treści
        rows = list(
            (
                await db.execute(
                    select(
                        ClientOrder,
                        Candidate.name.label("candidate_name"),
                        client_display_name_expression().label("client_name"),
                    )
                    .join(Contract, Contract.id == ClientOrder.contract_id)
                    .join(Candidate, Candidate.id == Contract.candidate_id)
                    .join(Client, Client.id == ClientOrder.client_id)
                    .where(
                        ClientOrder.status == ClientOrderStatus.active,
                        ClientOrder.end_date == target_date,
                    )
                )
            )
        )
        ntype = _ORDER_NTYPE_BY_DAY[days]
        for row in rows:
            o: ClientOrder = row[0]
            cand_name: str = row.candidate_name or "kontraktor"
            cli_name: str = row.client_name or "klient"

            for user_id in recipient_scope.for_client(o.client_id):
                if await _already_notified(
                    db,
                    user_id=user_id,
                    related_entity_type="client_order",
                    related_entity_id=o.id,
                    ntype=ntype,
                ):
                    continue
                db.add(
                    Notification(
                        user_id=user_id,
                        title=f"Zamówienie {cand_name} kończy się za {days} dni",
                        message=(
                            f"Zamówienie dla {cand_name} u {cli_name} kończy się "
                            f"{o.end_date.isoformat()}. Skontaktuj się z klientem, "
                            "aby przedyskutować przedłużenie."
                        ),
                        notification_type=ntype,
                        related_entity_type="client_order",
                        related_entity_id=o.id,
                        link=f"/clients/{o.client_id}?tab=zamowienia",
                    )
                )
                sent += 1
    return sent


async def run_once() -> dict:
    """Uruchom scan + status promotions raz; zwraca summary dict."""
    async with AsyncSessionLocal() as db:
        try:
            (
                fc_expired,
                order_completed,
                groups_promoted,
                contracts_reconciled,
            ) = await _promote_statuses(db)
            recipient_scope = await load_delivery_alert_recipient_scope(db)
            fc_alerts = await _scan_framework_contracts(db, recipient_scope)
            order_alerts = await _scan_orders(db, recipient_scope)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            raise

    summary = {
        "fc_expired": fc_expired,
        "orders_completed": order_completed,
        "order_groups_promoted": groups_promoted,
        "contracts_reconciled": contracts_reconciled,
        "fc_alerts_dispatched": fc_alerts,
        "order_alerts_dispatched": order_alerts,
    }
    logger.info("DL portal expiry scan: %s", summary)
    return summary


async def dl_portal_expiry_loop() -> None:
    """Daily loop — first run on startup, potem co 24h."""
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("dl_portal_expiry_loop iteration failed")
        try:
            await asyncio.sleep(_INTERVAL_HOURS * 3600)
        except asyncio.CancelledError:
            raise
