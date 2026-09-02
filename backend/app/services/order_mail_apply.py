"""Writer zamówień z maila — JEDEN dla auto-zapisu i dla „Zastosuj" z kolejki.

Reużywa dokładnie te helpery, które ma endpoint ``POST /clients/{id}/orders``
(``_activate_complete_draft``, ``_materialize_group_after_activation``,
``sync_contract_to_live_order``, ``_attach_po_bytes``, ``commit_order_write``),
zamiast przepisywać 200-liniowy handler multipart na serwis — to jest „jeden
mechanizm" na poziomie funkcji serwisowych, bez refaktoru routera, którego
sygnatura (Form) jest kontraktem frontu.

Trzy inwarianty, których writer pilnuje niezależnie od bramki:
* ``rate_candidate`` NIGDY z PDF-a — dokument opisuje stronę przychodową;
  stawkę kosztową dziedziczy z harmonogramu kontraktu (``_activation_candidate_rate``),
  a gdy jej tam nie ma, zamówienie zostaje SZKICEM (nie aktywuje się);
* ``sync_contract_to_live_order`` jest wołany zawsze (inwariant repo; 0243/0250
  naprawiały writerów, którzy go pomijali) — bramka po prostu nie wpuszcza
  automatu tam, gdzie miałby coś wskrzeszać;
* ``HTTPException`` z ``commit_order_write`` (409 po polsku z nazwy więzu) jest
  tu mapowany na wynik ``failed`` — w tasku nie ma komu go rzucić.

Wersja 1 obsługuje zamówienia SAMODZIELNE (``fill_draft`` / ``future`` / ``new``).
Linie grup (BIK/Polkomtel/BNP) idą do kolejki i są zakładane istniejącym UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, RateUnit
from app.models.order_mail import OrderMailDocument
from app.services import storage_service
from app.services.contract_lifecycle import sync_contract_to_live_order
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.order_engagement_separation import assert_no_open_md_group_line
from app.services.order_mail_planner import (
    ACTION_FILL_DRAFT,
    ACTION_FUTURE,
    ACTION_NEW,
    AUTO_ACTIONS,
)
from app.services.order_write_errors import commit_order_write

logger = logging.getLogger(__name__)

_RATE_UNIT = {"hour": "hourly", "day": "daily", "month": "monthly"}


@dataclass
class AppliedRow:
    row_index: int
    action: str
    order_id: Optional[int] = None
    activated: bool = False
    contract_revived: bool = False
    error: Optional[str] = None


@dataclass
class ApplyResult:
    rows: list[AppliedRow] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and all(r.error is None for r in self.rows)

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.error, "rows": [r.__dict__ for r in self.rows]}


def _rate_unit(value: Optional[str]) -> Optional[RateUnit]:
    if not value:
        return None
    mapped = _RATE_UNIT.get(value, value)
    try:
        return RateUnit(mapped)
    except ValueError:
        return None


def _dec(value: Optional[str]) -> Optional[Decimal]:
    return Decimal(value) if value not in (None, "") else None


def _date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


async def apply_document(
    db: AsyncSession,
    doc: OrderMailDocument,
    *,
    actor_user_id: Optional[int],
    only_actions: frozenset[str] = AUTO_ACTIONS,
) -> ApplyResult:
    """Wykonaj plan z ``doc.proposal``. Nie rzuca; wynik w ``ApplyResult``."""
    from app.api.client_orders import (  # import lokalny: router importuje serwisy
        _activate_complete_draft,
        _attach_po_bytes,
        _materialize_group_after_activation,
    )

    result = ApplyResult()
    proposal = doc.proposal or {}
    rows = proposal.get("rows") or []
    if not rows:
        result.error = "Brak planu zapisu"
        return result
    actor = SimpleNamespace(id=actor_user_id)
    pdf_bytes: Optional[bytes] = None
    if doc.storage_path:
        try:
            pdf_bytes = storage_service.get_order_mail_attachment_path(
                doc.storage_path
            ).read_bytes()
        except OSError as exc:
            logger.warning(
                "order_mail apply: cannot read PDF %s: %s", doc.storage_path, exc
            )

    for rp in rows:
        applied = AppliedRow(
            row_index=rp.get("row_index", 0), action=rp.get("action", "")
        )
        result.rows.append(applied)
        if applied.action not in only_actions:
            applied.error = f"Akcja {applied.action!r} poza zakresem writera"
            continue
        contract_id = rp.get("contract_id")
        if not contract_id:
            applied.error = "Brak kontraktu w planie"
            continue
        try:
            contract = await db.scalar(
                select(Contract)
                .options(*RATE_SCHEDULE_LOADS)
                .where(Contract.id == contract_id)
            )
            if contract is None or contract.client_id != doc.client_id:
                applied.error = "Kontrakt nie należy do tego klienta"
                continue
            start = _date(rp.get("start_date"))
            end = _date(rp.get("end_date"))
            effective = effective_rate_fields(contract, start or date.today())
            unit = _rate_unit(rp.get("rate_unit")) or contract.rate_unit

            if applied.action == ACTION_FILL_DRAFT and rp.get("target_order_id"):
                order = await db.scalar(
                    select(ClientOrder).where(
                        ClientOrder.id == rp["target_order_id"],
                        ClientOrder.contract_id == contract.id,
                        ClientOrder.status == ClientOrderStatus.draft,
                    )
                )
                if order is None:
                    applied.error = "Szkic do uzupełnienia już nie istnieje"
                    continue
                order.title = rp.get("title") or order.title
                order.start_date = start or order.start_date
                order.end_date = end
                order.rate_client = _dec(rp.get("rate_client")) or order.rate_client
                order.rate_unit = unit
                order.contract = contract
            else:
                await assert_no_open_md_group_line(db, contract.id)
                order = ClientOrder(
                    client_id=doc.client_id,
                    contract_id=contract.id,
                    contract=contract,
                    title=rp.get("title") or "(bez numeru)",
                    status=ClientOrderStatus.draft,
                    order_type="periodic",
                    start_date=start,
                    end_date=end,
                    rate_client=_dec(rp.get("rate_client")),
                    rate_candidate=None,  # NIGDY z PDF-a
                    rate_unit=unit,
                    rate_client_currency=effective.get("rate_client_currency"),
                    rate_candidate_currency=effective.get("rate_candidate_currency"),
                    created_by_user_id=actor_user_id,
                    notes=f"Zamówienie z maila (dokument #{doc.id})",
                )
                db.add(order)
                await db.flush()

            if pdf_bytes is not None and order.file_path is None:
                _attach_po_bytes(
                    order,
                    payload=pdf_bytes,
                    filename=doc.attachment_name or "zamowienie.pdf",
                    content_type="application/pdf",
                    user=actor,
                )
            applied.activated = bool(_activate_complete_draft(order))
            if order.status == ClientOrderStatus.active:
                await db.flush()
                await _materialize_group_after_activation(
                    db, order, actor_id=actor_user_id
                )
            if order.status not in (
                ClientOrderStatus.draft,
                ClientOrderStatus.cancelled,
            ):
                applied.contract_revived = await sync_contract_to_live_order(
                    db,
                    contract,
                    order_start=order.start_date,
                    order_end=order.end_date,
                    actor_id=actor_user_id,
                )
            await db.flush()
            await commit_order_write(db)
            applied.order_id = order.id
        except HTTPException as exc:
            await db.rollback()
            applied.error = str(exc.detail)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.exception(
                "order_mail apply failed (doc=%s row=%s)", doc.id, applied.row_index
            )
            applied.error = repr(exc)[:500]

    first_ok = next((r for r in result.rows if r.order_id), None)
    doc.applied_order_id = first_ok.order_id if first_ok else None
    doc.applied_at = datetime.now(timezone.utc)
    doc.applied_by_user_id = actor_user_id
    doc.proposal = {**proposal, "apply_result": result.as_dict()}
    return result


__all__ = [
    "ACTION_FILL_DRAFT",
    "ACTION_FUTURE",
    "ACTION_NEW",
    "ApplyResult",
    "apply_document",
]
