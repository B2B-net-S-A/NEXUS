"""Kształt zgody w odpowiedziach tras (skrzynka, „Moje zgody”, szczegół)."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_approval import ApprovalRequest
from app.models.user import User
from app.services.hr.approvals.service import (
    KIND_LABELS,
    amount_text,
    can_decide,
)
from app.services.hr_approvals_schema import PENDING_STATUSES

STATUS_LABELS: dict[str, str] = {
    "pending_supervisor": "U przełożonego",
    "pending_final": "Czeka na zatwierdzającego",
    "approved": "Zatwierdzona",
    "rejected": "Odrzucona",
    "returned": "Pytanie do Ciebie",
    "withdrawn": "Wycofana",
}


async def names_for(
    db: AsyncSession, requests: list[ApprovalRequest], extra: tuple[int, ...] = ()
) -> dict[int, str]:
    ids = set(extra)
    for request in requests:
        ids.update(
            uid
            for uid in (
                request.requester_user_id,
                request.beneficiary_user_id,
                request.supervisor_user_id,
                request.endorsed_by,
                request.decided_by,
            )
            if uid is not None
        )
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {int(uid): str(name) for uid, name in rows.all()}


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def request_payload(
    request: ApprovalRequest,
    names: dict[int, str],
    *,
    viewer: User,
    finals: list[int],
) -> dict[str, Any]:
    is_author = request.requester_user_id == viewer.id
    open_for_author = request.status in ("returned", *PENDING_STATUSES)
    return {
        "id": request.id,
        "kind": request.kind,
        "kind_label": KIND_LABELS[request.kind],
        "status": request.status,
        "status_label": STATUS_LABELS[request.status],
        "title": request.title,
        "purpose": request.purpose,
        "amount": str(request.amount),
        "decided_amount": str(request.decided_amount)
        if request.decided_amount is not None
        else None,
        "currency": request.currency,
        "amount_basis": request.amount_basis,
        "recurrence": request.recurrence,
        "amount_text": amount_text(request),
        "payer": request.payer,
        "link_url": request.link_url,
        "needed_by": _iso(request.needed_by),
        "starts_on": _iso(request.starts_on),
        "ends_on": _iso(request.ends_on),
        "beneficiary_user_id": request.beneficiary_user_id,
        "beneficiary_name": names.get(request.beneficiary_user_id)
        if request.beneficiary_user_id
        else None,
        "payout_year": request.payout_year,
        "payout_month": request.payout_month,
        "contract_basis": request.contract_basis,
        "requester_user_id": request.requester_user_id,
        "requester_name": names.get(request.requester_user_id),
        "supervisor_user_id": request.supervisor_user_id,
        "supervisor_name": names.get(request.supervisor_user_id)
        if request.supervisor_user_id
        else None,
        "needs_final": request.needs_final,
        "final_approver_names": [names[uid] for uid in finals if uid in names],
        "endorsed_by_name": names.get(request.endorsed_by)
        if request.endorsed_by
        else None,
        "endorsed_at": _iso(request.endorsed_at),
        "endorse_note": request.endorse_note,
        "decided_by_name": names.get(request.decided_by)
        if request.decided_by
        else None,
        "decided_at": _iso(request.decided_at),
        "decision_note": request.decision_note,
        "decision_channel": request.decision_channel,
        "bonus_id": request.bonus_id,
        "submitted_at": _iso(request.submitted_at),
        "can_decide": can_decide(viewer.id, request, finals),
        # Przełożony ponad próg popiera, nie zatwierdza (front zmienia napis).
        "decides_as": "final"
        if viewer.id in finals
        else ("supervisor" if viewer.id == request.supervisor_user_id else None),
        "can_edit": is_author and open_for_author,
        "can_withdraw": is_author and open_for_author,
    }


__all__ = ["STATUS_LABELS", "names_for", "request_payload"]
