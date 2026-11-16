"""Środki trwałe (K6): odczyt ekranu — ewidencja w miesiącu, karta środka, opcje.

Zapis ewidencji, dokumenty środka i AM miesiąca są w ``assets.py``; tu tylko
to, co pokazuje zakładka „Środki trwałe”: wartości na koniec miesiąca, plan
bilansowy i podatkowy ze stanem AM w księdze, dokumenty z zapisami oraz
pozycje „Sprzętu” i faktury z kolejki kosztów do podpięcia.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import EquipmentItem, EquipmentModel
from app.models.finance_ledger import FinanceCostEntry
from app.models.ledger import LedgerDocument
from app.models.ledger_assets import LedgerAsset, LedgerAssetOperation
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.costs import _sources as cost_sources
from app.services.ledger import depreciation
from app.services.ledger.allocation import Mpk
from app.services.ledger.assets import (
    KIND_LABELS,
    OPERATION_LABELS,
    POSTED_TYPES,
    STATUS_LABELS,
    AmState,
    am_documents,
    booked_reason,
    mpk_labels,
    operation_documents,
    operations_of,
    plan_input,
)
from app.services.ledger.depreciation import PlanRow
from app.services.ledger.documents import Viewer
from app.services.ledger.settings import LedgerSettings

OPTIONS_MAX = 20


# ── Odczyt ekranu ────────────────────────────────────────────────────────────


def _month_iso(month: Optional[date]) -> Optional[str]:
    return f"{month.year}-{month.month:02d}" if month else None


def _rate(value: Decimal) -> str:
    return f"{Decimal(value).normalize():f}"


def _last_day(month: date) -> date:
    return date.fromordinal(depreciation.add_months(month, 1).toordinal() - 1)


@dataclass(frozen=True)
class Position:
    """Środek w miesiącu: wartość, umorzenie i odpis bilansowy."""

    value: int
    accumulated: int
    amount: int
    accepted: bool
    present: bool
    in_register: bool

    @property
    def net(self) -> int:
        return self.value - self.accumulated


def position(
    asset: LedgerAsset, operations: list[LedgerAssetOperation], month: date
) -> Position:
    plan = plan_input(asset, operations)
    rows = depreciation.schedule(plan, until=month)
    row = depreciation.row_for(rows, month)
    end = _last_day(month)
    accepted = asset.accepted_on <= end
    present = accepted and (asset.disposed_on is None or asset.disposed_on >= month)
    in_register = accepted and (asset.disposed_on is None or asset.disposed_on > end)
    if not accepted:
        return Position(0, 0, 0, False, False, False)
    value = depreciation.value_at(plan, month)
    accumulated = min(depreciation.accumulated_at(plan, rows, month), value)
    return Position(
        value=value,
        accumulated=accumulated,
        amount=row.amount if row is not None else 0,
        accepted=True,
        present=present,
        in_register=in_register,
    )


def _document_ref(doc: Optional[LedgerDocument]) -> Optional[dict[str, Any]]:
    if doc is None:
        return None
    return {
        "id": doc.id,
        "number": doc.number,
        "status": doc.status,
        "journal_no": doc.journal_no,
    }


async def _unlinked_equipment(db: AsyncSession) -> int:
    linked = select(LedgerAsset.equipment_item_id).where(
        LedgerAsset.equipment_item_id.is_not(None)
    )
    return int(
        await db.scalar(
            select(func.count())
            .select_from(EquipmentItem)
            .where(
                EquipmentItem.ownership == "nasz",
                EquipmentItem.status.not_in(("wycofany", "zgubiony")),
                EquipmentItem.id.not_in(linked),
            )
        )
        or 0
    )


async def overview(
    db: AsyncSession,
    *,
    month: date,
    scope: str,
    settings: LedgerSettings,
    viewer: Viewer,
) -> dict[str, Any]:
    assets = list(
        await db.scalars(select(LedgerAsset).order_by(LedgerAsset.inventory_number))
    )
    operations = await operations_of(db, [asset.id for asset in assets])
    labels = await mpk_labels(db, {asset.mpk for asset in assets})
    items: list[dict[str, Any]] = []
    stats = {"count": 0, "value": 0, "accumulated": 0, "net": 0, "month_amount": 0}
    for asset in assets:
        ops = operations.get(asset.id, [])
        pos = position(asset, ops, month)
        stats["month_amount"] += pos.amount
        if pos.in_register:
            stats["count"] += 1
            stats["value"] += pos.value
            stats["accumulated"] += pos.accumulated
            stats["net"] += pos.net
        if scope != "all" and not pos.present:
            continue
        mpk = labels.get(asset.mpk) or Mpk(asset.mpk, "unknown", asset.mpk)
        items.append(
            {
                "id": asset.id,
                "inventory_number": asset.inventory_number,
                "name": asset.name,
                "kind": asset.kind,
                "kind_label": KIND_LABELS[asset.kind],
                "kst": asset.kst,
                "accepted_on": asset.accepted_on.isoformat(),
                "status": asset.status,
                "status_label": STATUS_LABELS[asset.status],
                "disposed_on": (
                    asset.disposed_on.isoformat() if asset.disposed_on else None
                ),
                "mpk": asset.mpk,
                "mpk_label": mpk.label,
                "balance_method": asset.balance_method,
                "method_label": depreciation.METHOD_LABELS[asset.balance_method],
                "balance_rate": _rate(asset.balance_rate),
                "accepted": pos.accepted,
                "value": pos.value,
                "accumulated": pos.accumulated,
                "net": pos.net,
                "month_amount": pos.amount,
                "fully_depreciated": pos.accepted
                and pos.net == 0
                and asset.balance_method != "none",
                "equipment_linked": asset.equipment_item_id is not None,
                "from_symfonia": asset.opening_month is not None,
            }
        )
    am = (await am_documents(db)).get(month)
    return {
        "month": _month_iso(month),
        "scope": scope,
        "stats": {**stats, "equipment_unlinked": await _unlinked_equipment(db)},
        "items": items,
        "am": (
            {
                "id": am.document_id,
                "number": am.number,
                "status": am.status,
                "journal_no": am.journal_no,
                "total": sum(value[0] for value in am.detail.values()),
            }
            if am is not None
            else None
        ),
        "accounts": {
            "cost_account": settings.assets.cost_account,
            "intake_account": settings.assets.intake_account,
            "disposal_account": settings.assets.disposal_account,
        },
        "allocation_complete": settings.allocation.complete(),
        "can_manage": viewer.approver,
        "can_configure": viewer.admin,
    }


async def _cost_entries(db: AsyncSession, ids: set[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    src = cost_sources()
    rows = await db.execute(
        select(
            FinanceCostEntry.id,
            src.c.invoice_number,
            src.c.seller_name,
            src.c.issue_date,
            src.c.currency,
            src.c.net_amount,
        )
        .join(
            src,
            and_(
                src.c.source_type == FinanceCostEntry.source_type,
                src.c.source_id == FinanceCostEntry.source_id,
            ),
        )
        .where(
            FinanceCostEntry.id.in_(ids),
            FinanceCostEntry.source_type != "payroll_invoice",
        )
    )
    return {
        entry_id: {
            "id": entry_id,
            "invoice_number": number,
            "seller_name": seller,
            "issue_date": issue.isoformat() if issue else None,
            "currency": currency,
            "net_amount": int(net * 100) if net is not None else None,
        }
        for entry_id, number, seller, issue, currency, net in rows.all()
    }


async def _equipment_info(
    db: AsyncSession, item_id: Optional[int]
) -> Optional[dict[str, Any]]:
    if item_id is None:
        return None
    row = (
        await db.execute(
            select(EquipmentItem, EquipmentModel.name, EquipmentModel.category)
            .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
            .where(EquipmentItem.id == item_id)
        )
    ).first()
    if row is None:
        return None
    item, model, category = row
    return {
        "id": item.id,
        "inventory_number": item.inventory_number,
        "serial_number": item.serial_number,
        "model": model,
        "category": category,
        "status": item.status,
    }


def _plan_rows(
    rows: list[PlanRow],
    states: dict[date, AmState],
    asset_id: int,
) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        state = states.get(row.month)
        booked = state is not None and asset_id in state.detail
        out.append(
            {
                "month": _month_iso(row.month),
                "amount": row.amount,
                "accumulated": row.accumulated,
                "net": row.net,
                "value": row.value,
                "degressive": row.degressive,
                "state": state.status if booked and state is not None else "plan",
                "journal_no": state.journal_no
                if booked and state is not None
                else None,
            }
        )
    return out


async def card(
    db: AsyncSession,
    asset_id: int,
    *,
    month: date,
    viewer: Viewer,
) -> dict[str, Any]:
    asset = await db.get(LedgerAsset, asset_id)
    if asset is None:
        raise LedgerError("Nie ma takiego środka.", status=404)
    operations = (await operations_of(db, [asset.id])).get(asset.id, [])
    states = await am_documents(db)
    docs = await operation_documents(db, [op.id for op in operations])
    balance_plan = plan_input(asset, operations)
    tax_plan = plan_input(asset, operations, tax=True)
    balance_rows = depreciation.schedule(balance_plan)
    tax_rows = depreciation.schedule(tax_plan)
    codes = {asset.mpk} | {
        code for op in operations for code in (op.mpk_from, op.mpk_to) if code
    }
    labels = await mpk_labels(db, codes)
    entries = await _cost_entries(
        db, {op.cost_entry_id for op in operations if op.cost_entry_id}
    )
    pos = position(asset, operations, month)
    current = depreciation.row_for(balance_rows, month)
    reason = await booked_reason(db, asset, operations)
    last_op = operations[-1] if operations else None

    def label(code: Optional[str]) -> Optional[str]:
        return labels[code].label if code and code in labels else code

    return {
        "id": asset.id,
        "inventory_number": asset.inventory_number,
        "name": asset.name,
        "kind": asset.kind,
        "kind_label": KIND_LABELS[asset.kind],
        "kst": asset.kst,
        "accepted_on": asset.accepted_on.isoformat(),
        "initial_value": asset.initial_value,
        "asset_account": asset.asset_account,
        "depreciation_account": asset.depreciation_account,
        "mpk": asset.mpk,
        "mpk_label": label(asset.mpk),
        "balance_method": asset.balance_method,
        "balance_rate": _rate(asset.balance_rate),
        "tax_method": asset.tax_method,
        "tax_rate": _rate(asset.tax_rate),
        "coefficient": _rate(asset.coefficient),
        "method_labels": dict(depreciation.METHOD_LABELS),
        "status": asset.status,
        "status_label": STATUS_LABELS[asset.status],
        "disposed_on": asset.disposed_on.isoformat() if asset.disposed_on else None,
        "note": asset.note,
        "opening": (
            {
                "month": _month_iso(asset.opening_month),
                "balance": asset.opening_balance,
                "tax": asset.opening_tax,
                "balance_year": asset.opening_balance_year,
                "tax_year": asset.opening_tax_year,
            }
            if asset.opening_month is not None
            else None
        ),
        "equipment": await _equipment_info(db, asset.equipment_item_id),
        "position": {
            "month": _month_iso(month),
            "value": pos.value,
            "accumulated": pos.accumulated,
            "net": pos.net,
            "amount": pos.amount,
            "monthly": current.amount if current is not None else None,
            "plan_end": _month_iso(depreciation.last_month(balance_rows)),
            "tax_plan_end": _month_iso(depreciation.last_month(tax_rows)),
        },
        "balance_plan": _plan_rows(balance_rows, states, asset.id),
        "tax_plan": [
            {
                "month": _month_iso(row.month),
                "amount": row.amount,
                "accumulated": row.accumulated,
                "net": row.net,
            }
            for row in tax_rows
        ],
        "operations": [
            {
                "id": op.id,
                "op_type": op.op_type,
                "label": OPERATION_LABELS[op.op_type],
                "number": op.number,
                "op_date": op.op_date.isoformat(),
                "amount": op.amount,
                "mpk_from": label(op.mpk_from),
                "mpk_to": label(op.mpk_to),
                "counter_account": op.counter_account,
                "posted": op.op_type in POSTED_TYPES
                and not (op.op_type == "OT" and op.counter_account is None),
                "cost_entry": entries.get(op.cost_entry_id or 0),
                "note": op.note,
                "document": _document_ref(docs.get(op.id)),
                "can_delete": viewer.approver
                and op is last_op
                and op.op_type != "OT"
                and not (
                    docs.get(op.id) is not None and docs[op.id].status == "approved"
                ),
            }
            for op in operations
        ],
        "locked": reason,
        "can_manage": viewer.approver,
        "can_delete": viewer.approver and reason is None,
    }


async def equipment_options(db: AsyncSession, needle: str) -> list[dict[str, Any]]:
    """Pozycje „Sprzętu” firmy bez karty środka (numer, numer seryjny, model)."""

    needle = " ".join((needle or "").split())[:60]
    linked = select(LedgerAsset.equipment_item_id).where(
        LedgerAsset.equipment_item_id.is_not(None)
    )
    query = (
        select(EquipmentItem, EquipmentModel.name, EquipmentModel.category)
        .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
        .where(EquipmentItem.ownership == "nasz", EquipmentItem.id.not_in(linked))
    )
    if needle:
        pattern = f"%{needle}%"
        query = query.where(
            or_(
                EquipmentItem.inventory_number.ilike(pattern),
                EquipmentItem.serial_number.ilike(pattern),
                EquipmentModel.name.ilike(pattern),
                EquipmentModel.category.ilike(pattern),
            )
        )
    rows = await db.execute(
        query.order_by(EquipmentItem.inventory_number, EquipmentItem.id).limit(
            OPTIONS_MAX
        )
    )
    return [
        {
            "id": item.id,
            "inventory_number": item.inventory_number,
            "serial_number": item.serial_number,
            "model": model,
            "category": category,
            "status": item.status,
            "purchase_date": item.purchase_date.isoformat()
            if item.purchase_date
            else None,
        }
        for item, model, category in rows.all()
    ]


async def cost_entry_options(db: AsyncSession, needle: str) -> list[dict[str, Any]]:
    """Faktury z kolejki kosztów (bez faktur osób zespołu) do OT i ulepszenia."""

    needle = " ".join((needle or "").split())[:60]
    src = cost_sources()
    query = (
        select(
            FinanceCostEntry.id,
            FinanceCostEntry.stage,
            src.c.invoice_number,
            src.c.seller_name,
            src.c.issue_date,
            src.c.currency,
            src.c.net_amount,
        )
        .join(
            src,
            and_(
                src.c.source_type == FinanceCostEntry.source_type,
                src.c.source_id == FinanceCostEntry.source_id,
            ),
        )
        .where(
            FinanceCostEntry.source_type != "payroll_invoice",
            FinanceCostEntry.stage != "rejected",
        )
    )
    if needle:
        pattern = f"%{needle}%"
        query = query.where(
            or_(src.c.invoice_number.ilike(pattern), src.c.seller_name.ilike(pattern))
        )
    rows = await db.execute(
        query.order_by(FinanceCostEntry.received_at.desc()).limit(OPTIONS_MAX)
    )
    return [
        {
            "id": entry_id,
            "stage": stage,
            "invoice_number": number,
            "seller_name": seller,
            "issue_date": issue.isoformat() if issue else None,
            "currency": currency,
            "net_amount": int(net * 100) if net is not None else None,
        }
        for entry_id, stage, number, seller, issue, currency, net in rows.all()
    ]
