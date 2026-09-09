"""One transactional writer for automatic import and manual queue application.

Lock the client, replan against the current roster, then save all people and
the document receipt in one transaction. Drafts are filled in place, ended
orders are reactivated with history, first engagements notify DL once. Cost
rates come exclusively from the contractor agreement and its schedule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.client import Client
from app.models.candidate import Candidate
from app.models.activity import Activity
from app.models.order_mail import OrderMailDocument
from app.services import storage_service
from app.services.contract_lifecycle import sync_contract_to_live_order
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.order_engagement_separation import assert_no_open_md_group_line
from app.services.order_mail_planner import (
    ACTION_FILL_DRAFT,
    ACTION_FUTURE,
    ACTION_NEW,
    ACTION_NEW_DRAFT,
    ACTION_REACTIVATE,
    ACTION_UNCHANGED,
    AUTO_ACTIONS,
)
from app.services.order_pdf_parser import _names_exactly_equivalent
from app.services.order_rate_snapshots import convert_order_rate

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


async def _new_person_contract(db, doc, rp):
    """Create the initial client engagement, with no inferred cost or signature.

    Client lock held by the writer serializes imports. Only a single exact
    global name may be reused; ambiguous global names must be resolved before
    associating personal records. Never guess an email or cost.
    """
    tokens = rp["row_name"].strip().split()
    if len(tokens) < 2:
        raise ValueError("Brak pełnego imienia i nazwiska nowego kontraktora")
    candidates = (
        await db.scalars(
            select(Candidate).where(
                func.lower(Candidate.lastname).in_(
                    [tokens[-1].lower(), tokens[0].lower()]
                ),
                Candidate.external_deleted_at.is_(None),
            )
        )
    ).all()
    matches = [
        c
        for c in candidates
        if _names_exactly_equivalent(rp["row_name"], f"{c.name} {c.lastname}")
    ]
    if len(matches) > 1:
        raise ValueError("Kilka osób o tym imieniu i nazwisku w bazie — wybierz osobę")
    if matches:
        candidate = matches[0]
    else:
        candidate = Candidate(name=" ".join(tokens[:-1]), lastname=tokens[-1])
        db.add(candidate)
        await db.flush()
    contract = Contract(
        client_id=doc.client_id,
        candidate_id=candidate.id,
        status=ContractStatus.draft,
        start_date=_date(rp.get("start_date")),
        rate_candidate=None,
        rate_client=None,
        rate_unit=_rate_unit(rp.get("rate_unit")) or RateUnit.hourly,
        currency="PLN",
        candidate_rate_schedule=[],
        client_rate_schedule=[],
        framework_rate_schedule=[],
    )
    db.add(contract)
    await db.flush()
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="auto_drafted_from_order_mail",
            details={"document_id": doc.id},
        )
    )
    return contract


async def _notify_new_draft(db, doc, order, name):
    from app.services.dl_alerts import dl_user_ids_for_client, emit

    client = await db.get(Client, doc.client_id)
    await emit(
        db,
        alert_type="draft_consultant_unassigned",
        user_ids=await dl_user_ids_for_client(db, doc.client_id),
        client_id=doc.client_id,
        entity_key=f"mail-draft:{order.id}",
        order_id=order.id,
        repeat_every_days=None,
        title=f"Nowy kontraktor {name} w {client.display_name or client.name}",
        message=f"Nowy kontraktor {name} w {client.display_name or client.name} — uzupełnij dane: stawka kosztowa.",
        link=f"/clients/{doc.client_id}?tab=orders",
    )


async def apply_document(
    db: AsyncSession,
    doc: OrderMailDocument,
    *,
    actor_user_id: Optional[int],
    only_actions: frozenset[str] = AUTO_ACTIONS,
) -> ApplyResult:
    """Wykonaj plan z ``doc.proposal``. Nie rzuca; wynik w ``ApplyResult``."""
    # Lock the client before refreshing the roster. Different incoming PDFs
    # for the same first contractor cannot both create an initial draft.
    await db.scalar(
        select(Client.id).where(Client.id == doc.client_id).with_for_update()
    )
    if not (doc.proposal or {}).get("apply_result"):
        from app.services.order_mail_ingest import current_proposal, restore_extraction

        proposal, resolved, _ = await current_proposal(
            db, restore_extraction(doc.extraction), doc.client_id
        )
        if proposal.blocking or not proposal.auto_eligible_actions:
            return ApplyResult(
                error="; ".join(
                    proposal.blocking
                    + [
                        f"{r.row_name}: {'; '.join(r.reasons)}"
                        for r in proposal.rows
                        if r.action not in only_actions
                    ]
                )
            )
        if actor_user_id is None and any(
            r.match_kind not in ("exact", "none") for r in resolved
        ):
            return ApplyResult(
                error="Dopasowanie osoby zmieniło się — wymaga potwierdzenia"
            )
        doc.proposal = {
            **(doc.proposal or {}),
            "rows": [r.__dict__ for r in proposal.rows],
            "resolved": [r.__dict__ for r in resolved],
            "blocking": proposal.blocking,
        }
    async with db.begin_nested() as transaction:
        result = await _write_document(
            db, doc, actor_user_id=actor_user_id, only_actions=only_actions
        )
        if not result.ok:
            await transaction.rollback()
    if not result.ok:
        error = result.error or "; ".join(r.error for r in result.rows if r.error)
        await db.refresh(doc)
        return ApplyResult(error=error)
    return result


async def _write_document(db, doc, *, actor_user_id, only_actions):
    from app.api.client_orders import (
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

    # Idempotencja ponowienia po częściowym niepowodzeniu: wiersz, który w
    # poprzednim biegu dostał `order_id`, jest już zapisany — drugi klik
    # „Zastosuj" nie może założyć mu drugiego zamówienia.
    previously_applied = {
        r.get("row_index"): r.get("order_id")
        for r in ((proposal.get("apply_result") or {}).get("rows") or [])
        if r.get("order_id")
    }
    for rp in rows:
        applied = AppliedRow(
            row_index=rp.get("row_index", 0), action=rp.get("action", "")
        )
        result.rows.append(applied)
        if applied.row_index in previously_applied:
            applied.order_id = previously_applied[applied.row_index]
            continue
        if applied.action not in only_actions:
            applied.error = f"Akcja {applied.action!r} poza zakresem writera"
            continue
        contract_id = rp.get("contract_id")
        if not contract_id and applied.action != ACTION_NEW_DRAFT:
            applied.error = "Brak kontraktu w planie"
            continue
        try:
            if applied.action == ACTION_NEW_DRAFT:
                contract = await _new_person_contract(db, doc, rp)
            else:
                contract = await db.scalar(
                    select(Contract)
                    .options(*RATE_SCHEDULE_LOADS)
                    .where(Contract.id == contract_id)
                    .with_for_update()
                )
            if contract is None or contract.client_id != doc.client_id:
                applied.error = "Kontrakt nie należy do tego klienta"
                continue
            start = _date(rp.get("start_date"))
            end = _date(rp.get("end_date"))
            effective = effective_rate_fields(contract, start or date.today())
            unit = _rate_unit(rp.get("rate_unit")) or contract.rate_unit

            if applied.action == ACTION_UNCHANGED:
                order = await db.scalar(
                    select(ClientOrder)
                    .where(
                        ClientOrder.id == rp["target_order_id"],
                        ClientOrder.contract_id == contract.id,
                    )
                    .with_for_update()
                )
                if order is None:
                    raise ValueError("Zamówienie już nie istnieje — przelicz plan")
                applied.order_id = order.id
                applied.activated = order.status == ClientOrderStatus.active
                continue
            is_new_person = applied.action == ACTION_NEW_DRAFT
            if applied.action in (ACTION_FILL_DRAFT, ACTION_REACTIVATE) and rp.get(
                "target_order_id"
            ):
                order = await db.scalar(
                    select(ClientOrder)
                    .where(
                        ClientOrder.id == rp["target_order_id"],
                        ClientOrder.contract_id == contract.id,
                        ClientOrder.status
                        == (
                            ClientOrderStatus.completed
                            if applied.action == ACTION_REACTIVATE
                            else ClientOrderStatus.draft
                        ),
                    )
                    .with_for_update()
                )
                if order is None:
                    applied.error = "Szkic do uzupełnienia już nie istnieje"
                    continue
                before = {
                    "title": order.title,
                    "start_date": str(order.start_date),
                    "end_date": str(order.end_date),
                    "rate_client": str(order.rate_client),
                    "file_path": order.file_path,
                }
                if applied.action == ACTION_REACTIVATE:
                    if not start or not order.end_date or start <= order.end_date:
                        raise ValueError(
                            "Nowy okres nie następuje po zakończonym zamówieniu"
                        )
                    gap = (start - order.end_date).days
                    message = (
                        f"Powrót po {gap} dniach od zakończenia poprzedniego zamówienia"
                    )
                    order.notes = "\n".join(filter(None, [order.notes, message]))
                    order.status = ClientOrderStatus.draft
                else:
                    message = "Uzupełnienie draftu z zamówienia mailowego"
                db.add(
                    Activity(
                        entity_type="client_order",
                        entity_id=order.id,
                        action="order_mail_" + applied.action,
                        user_id=actor_user_id,
                        details={
                            "document_id": doc.id,
                            "before": before,
                            "message": message,
                        },
                    )
                )
                order.title = rp.get("title") or order.title
                order.start_date = start or order.start_date
                order.end_date = end
                order.rate_client = _dec(rp.get("rate_client")) or order.rate_client
                order.rate_candidate = convert_order_rate(
                    order.rate_candidate,
                    order.rate_unit,
                    unit,
                    order.billing_hours_per_month,
                )
                order.rate_unit = unit
                order.contract = contract
            else:
                if applied.action != ACTION_FUTURE:
                    await assert_no_open_md_group_line(db, contract.id)
                # Drugi guard, gdy `apply_result` nie zdążył się zapisać (crash
                # między commitem wiersza a zapisem dokumentu): zamówienie z TEGO
                # dokumentu dla tego kontraktu i numeru już istnieje → nie dublujemy.
                marker = f"Zamówienie z maila (dokument #{doc.id})"
                existing = await db.scalar(
                    select(ClientOrder).where(
                        ClientOrder.contract_id == contract.id,
                        ClientOrder.title == (rp.get("title") or "(bez numeru)"),
                        ClientOrder.notes == marker,
                    )
                )
                if existing is not None:
                    applied.order_id = existing.id
                    applied.activated = existing.status == ClientOrderStatus.active
                    continue
                order = ClientOrder(
                    client_id=doc.client_id,
                    contract_id=contract.id,
                    contract=contract,
                    title=rp.get("title") or "(bez numeru)",
                    status=ClientOrderStatus.draft,
                    order_type=rp.get("order_type") or "periodic",
                    total_value=_dec(rp.get("total_value")),
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
                db.add(
                    Activity(
                        entity_type="client_order",
                        entity_id=order.id,
                        action="order_mail_new_draft"
                        if is_new_person
                        else "order_mail_created",
                        user_id=actor_user_id,
                        details={"document_id": doc.id},
                    )
                )

            if order.order_type == "md" and rp.get("md_total"):
                from app.api.client_orders import _apply_md_order_quantity

                _apply_md_order_quantity(order, _dec(rp["md_total"]))
            if pdf_bytes is not None and (
                order.file_path is None or applied.action == ACTION_REACTIVATE
            ):
                _attach_po_bytes(
                    order,
                    payload=pdf_bytes,
                    filename=doc.attachment_name or "zamowienie.pdf",
                    content_type="application/pdf",
                    user=actor,
                )
            # Copy a cost only from the contract's own schedule, preserving
            # unit/currency. A first unsigned engagement has no such cost.
            if order.rate_candidate is None or applied.action == ACTION_REACTIVATE:
                order.rate_candidate = convert_order_rate(
                    effective.get("rate_candidate"),
                    contract.rate_unit,
                    unit,
                    contract.billing_hours_per_month,
                )
                order.rate_candidate_currency = effective.get("rate_candidate_currency")
            from app.services.order_mail_signature import can_activate_mail_order

            applied.activated = bool(
                await can_activate_mail_order(db, contract)
                and _activate_complete_draft(order)
            )
            if is_new_person and order.status == ClientOrderStatus.draft:
                await _notify_new_draft(db, doc, order, rp["row_name"])
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
            applied.order_id = order.id
        except HTTPException as exc:
            applied.error = str(exc.detail)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "order_mail apply failed (doc=%s row=%s)", doc.id, applied.row_index
            )
            applied.error = repr(exc)[:500]
            return result

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
