"""Finanse → „Wydatki ze zgodą” (etap 3 zgód, 0486): kafle, listy, rejestr.

Bramka trasy: moduł „Zgody” + uprawnienie „Moduł Finanse”. Premie poza
umową widać tu tylko jako sumę miesiąca, bez osób (decyzja Artura
20.10.2026 — szczegóły premii zostają w Płacach, reguła D2). Kwoty w innej
walucie niż PLN nie wchodzą do sum (NEXUS nie ma kursów) — liczymy je osobno.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.hr_approval import (
    ApprovalDocument,
    ApprovalFixedCostSeller,
    ApprovalRequest,
)
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr.approvals import settlement
from app.services.hr.approvals.service import KIND_LABELS, amount_text
from app.services.hr.approvals.settlement_payload import document_payload
from app.services.hr.calendar import month_range
from app.services.hr_approval_settlement_schema import TOPUP_TOLERANCE_PERCENT
from app.services.hr_approvals_schema import KINDS

_ZONE = ZoneInfo(DEFAULT_TZ)
_TOLERANCE = Decimal(100 + TOPUP_TOLERANCE_PERCENT) / Decimal(100)
MAX_SUGGESTIONS = 3


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    first, last = month_range(year, month)
    return (
        datetime.combine(first, time.min, tzinfo=_ZONE),
        datetime.combine(last + timedelta(days=1), time.min, tzinfo=_ZONE),
    )


def monthly_equivalent(request: ApprovalRequest) -> Decimal:
    amount = settlement.approved_amount(request)
    if request.recurrence == "yearly":
        return (amount / 12).quantize(Decimal("0.01"))
    return amount


async def _names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {int(uid): str(name or "") for uid, name in rows.all()}


async def summary(db: AsyncSession, year: int, month: int) -> dict[str, Any]:
    start, end = _month_bounds(year, month)
    approved = list(
        await db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.status == "approved",
                ApprovalRequest.decided_at >= start,
                ApprovalRequest.decided_at < end,
            )
        )
    )
    by_kind = {kind: Decimal(0) for kind in KINDS}
    other_currency = 0
    total = Decimal(0)
    for request in approved:
        if request.currency != "PLN":
            other_currency += 1
            continue
        value = settlement.approved_amount(request)
        by_kind[request.kind] += value
        total += value
    today = business_today()
    awaiting = list(
        await db.scalars(
            select(ApprovalRequest).where(ApprovalRequest.settlement_status == "open")
        )
    )
    awaiting_pln = sum(
        (settlement.approved_amount(r) for r in awaiting if r.currency == "PLN"),
        Decimal(0),
    )
    oldest = min((r.decided_at for r in awaiting if r.decided_at), default=None)
    active = list(
        await db.scalars(
            select(ApprovalRequest).where(ApprovalRequest.settlement_status == "active")
        )
    )
    subscriptions_monthly = sum(
        (monthly_equivalent(r) for r in active if r.currency == "PLN"), Decimal(0)
    )
    to_settle = await db.scalar(
        select(func.count(func.distinct(ApprovalDocument.approval_request_id))).where(
            ApprovalDocument.status == "pinned"
        )
    )
    unmatched = await db.scalar(
        select(func.count(ApprovalDocument.id)).where(
            ApprovalDocument.status == "unmatched"
        )
    )
    return {
        "year": year,
        "month": month,
        "approved_total": str(total),
        "approved_count": len([r for r in approved if r.kind != "bonus"]),
        "bonus_count": len([r for r in approved if r.kind == "bonus"]),
        "by_kind": [
            {"kind": kind, "label": KIND_LABELS[kind], "amount": str(by_kind[kind])}
            for kind in KINDS
        ],
        "other_currency_count": other_currency,
        "awaiting_count": len(awaiting),
        "awaiting_total": str(awaiting_pln),
        "awaiting_oldest_days": (today - oldest.astimezone(_ZONE).date()).days
        if oldest
        else None,
        "subscriptions_count": len(active),
        "subscriptions_monthly": str(subscriptions_monthly),
        "subscriptions_yearly": str(subscriptions_monthly * 12),
        "to_settle_count": int(to_settle or 0),
        "unmatched_count": int(unmatched or 0),
    }


def _request_row(
    request: ApprovalRequest,
    docs: list[ApprovalDocument],
    names: dict[int, str],
    viewer: User,
    *,
    finals: tuple[int, ...] = (),
) -> dict[str, Any]:
    attached = [d for d in docs if d.status in ("pinned", "settled")]
    return {
        "id": request.id,
        "kind": request.kind,
        "kind_label": KIND_LABELS[request.kind],
        "title": request.title,
        "requester_name": names.get(request.requester_user_id),
        "amount_text": amount_text(request),
        "approved_amount": str(settlement.approved_amount(request)),
        "currency": request.currency,
        "amount_basis": request.amount_basis,
        "recurrence": request.recurrence,
        "payer": request.payer,
        "decided_at": _iso(request.decided_at),
        "expires_on": _iso(settlement.expiry(request)),
        "settlement_status": request.settlement_status,
        "seller_nip": request.seller_nip,
        "comparison": settlement.compare(request, attached).as_json()
        if request.recurrence == "once"
        else None,
        "documents": [
            document_payload(
                d,
                viewer=viewer,
                request=request,
                docs=attached,
                finals=finals,
                names=names,
            )
            for d in attached
            if d.status == "pinned"
        ],
    }


async def to_settle(db: AsyncSession, viewer: User) -> dict[str, Any]:
    """Zgody z dokumentem do rozliczenia i zgody czekające na fakturę."""

    with_docs = list(
        await db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.id.in_(
                    select(ApprovalDocument.approval_request_id).where(
                        ApprovalDocument.status == "pinned"
                    )
                )
            )
            .order_by(ApprovalRequest.decided_at)
        )
    )
    awaiting = list(
        await db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.settlement_status == "open")
            .order_by(ApprovalRequest.decided_at, ApprovalRequest.id)
        )
    )
    docs = await settlement.documents_of(db, [r.id for r in with_docs])
    ids = {r.requester_user_id for r in [*with_docs, *awaiting]}
    ids |= {d.settled_by for ds in docs.values() for d in ds if d.settled_by}
    names = await _names(db, ids)
    return {
        "to_settle": [_request_row(r, docs[r.id], names, viewer) for r in with_docs],
        "awaiting": [_request_row(r, [], names, viewer) for r in awaiting],
    }


async def subscriptions(
    db: AsyncSession, viewer: User, *, include_ended: bool
) -> list[dict[str, Any]]:
    statuses = ("active", "ended") if include_ended else ("active",)
    rows = list(
        await db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.settlement_status.in_(statuses),
                ApprovalRequest.recurrence != "once",
            )
            .order_by(ApprovalRequest.renews_on.nulls_last(), ApprovalRequest.title)
        )
    )
    docs = await settlement.documents_of(db, [r.id for r in rows])
    names = await _names(db, {r.requester_user_id for r in rows})
    departments = (
        dict(
            (
                await db.execute(
                    select(EmployeeProfile.user_id, EmployeeProfile.department).where(
                        EmployeeProfile.user_id.in_({r.requester_user_id for r in rows})
                    )
                )
            ).all()
        )
        if rows
        else {}
    )
    today = business_today()
    out = []
    for request in rows:
        attached = [d for d in docs[request.id] if d.status in ("pinned", "settled")]
        last = max(
            attached, key=lambda d: (d.issue_date or date.min, d.id), default=None
        )
        out.append(
            {
                "id": request.id,
                "title": request.title,
                "kind": request.kind,
                "kind_label": KIND_LABELS[request.kind],
                "owner_user_id": request.requester_user_id,
                "owner_name": names.get(request.requester_user_id),
                "department": departments.get(request.requester_user_id),
                "recurrence": request.recurrence,
                "amount_text": amount_text(request),
                "monthly": str(monthly_equivalent(request)),
                "currency": request.currency,
                "renews_on": _iso(request.renews_on),
                "renews_in_days": (request.renews_on - today).days
                if request.renews_on
                else None,
                "renewal_asked": request.renews_on is not None
                and request.renewal_asked_for == request.renews_on,
                "renewal_confirmed": request.renews_on is not None
                and request.renewal_confirmed_for == request.renews_on,
                "status": request.settlement_status,
                "ended_on": _iso(request.ended_on),
                "seller_nip": request.seller_nip,
                "last_document": document_payload(
                    last, viewer=viewer, request=request, docs=attached
                )
                if last
                else None,
            }
        )
    return out


async def _suggestions(db: AsyncSession, doc: ApprovalDocument) -> list[dict[str, Any]]:
    """Otwarte zgody, do których faktura kwotą pasuje (±10%) — podpowiedź."""

    if doc.gross_amount is None:
        return []
    rows = list(
        await db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.settlement_status.in_(("open", "documented", "active")),
                ApprovalRequest.currency == doc.currency,
            )
            .order_by(ApprovalRequest.decided_at.desc())
            .limit(200)
        )
    )
    out = []
    for request in rows:
        amount = settlement.document_amount(doc, request.amount_basis)
        approved = settlement.approved_amount(request)
        if amount is None or not (
            approved / _TOLERANCE <= amount <= approved * _TOLERANCE
        ):
            continue
        out.append(
            {
                "id": request.id,
                "title": request.title,
                "kind_label": KIND_LABELS[request.kind],
                "amount_text": amount_text(request),
                "same_seller": request.seller_nip == doc.seller_nip,
            }
        )
        if len(out) >= MAX_SUGGESTIONS:
            break
    return out


async def unmatched(
    db: AsyncSession, viewer: User, *, state: str = "unmatched"
) -> list[dict[str, Any]]:
    """Kolejka „Faktury bez zgody” (albo stałe koszty / zamknięte)."""

    rows = list(
        await db.scalars(
            select(ApprovalDocument)
            .where(ApprovalDocument.status == state)
            .order_by(
                ApprovalDocument.issue_date.desc().nulls_last(),
                ApprovalDocument.id.desc(),
            )
            .limit(500)
        )
    )
    out = []
    for doc in rows:
        item = document_payload(doc, viewer=viewer)
        if state == "unmatched":
            item["suggestions"] = await _suggestions(db, doc)
        out.append(item)
    return out


async def fixed_sellers(db: AsyncSession) -> list[dict[str, Any]]:
    rows = list(
        await db.scalars(
            select(ApprovalFixedCostSeller).order_by(
                ApprovalFixedCostSeller.seller_name
            )
        )
    )
    return [
        {
            "seller_nip": row.seller_nip,
            "seller_name": row.seller_name,
            "note": row.note,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


async def open_requests(db: AsyncSession, query: str) -> list[dict[str, Any]]:
    """Wybór zgody przy „Przypnij do zgody” (tytuł, bez premii)."""

    statement = (
        select(ApprovalRequest)
        .where(ApprovalRequest.settlement_status.in_(("open", "documented", "active")))
        .order_by(ApprovalRequest.decided_at.desc())
        .limit(30)
    )
    text = query.strip()
    if text:
        statement = statement.where(ApprovalRequest.title.ilike(f"%{text}%"))
    rows = list(await db.scalars(statement))
    names = await _names(db, {r.requester_user_id for r in rows})
    return [
        {
            "id": r.id,
            "title": r.title,
            "kind_label": KIND_LABELS[r.kind],
            "requester_name": names.get(r.requester_user_id),
            "amount_text": amount_text(r),
        }
        for r in rows
    ]
