"""Kształt rozliczenia zgody i dokumentu wydatku w odpowiedziach tras (0486)."""

from __future__ import annotations

from typing import Any, Optional

from app.models.hr_approval import ApprovalDocument, ApprovalRequest
from app.models.user import User
from app.services.hr.approvals import settlement
from app.services.hr_approval_settlement_schema import (
    OPEN_SETTLEMENT_STATUSES,
    TOPUP_TOLERANCE_PERCENT,
)

DOC_STATUS_LABELS: dict[str, str] = {
    "pinned": "do rozliczenia",
    "settled": "rozliczona",
    "unmatched": "bez zgody",
    "fixed_cost": "stały koszt",
    "dismissed": "zamknięta",
}
MATCH_REASON_LABELS: dict[str, str] = {
    "auto": "przypięta sama (KSeF)",
    "manual": "przypięta przez Finanse",
    "upload": "dołączona do zgody",
    "no_approval": "żadna zgoda nie ma tego sprzedawcy",
    "several": "kilka zgód tego sprzedawcy — wybierz",
    "correction": "korekta faktury — przypnij ręcznie",
    "unpinned": "odpięta od zgody",
    "fixed_cost": "sprzedawca na liście stałych kosztów",
}


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _money(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def document_payload(
    doc: ApprovalDocument,
    *,
    viewer: User,
    request: Optional[ApprovalRequest] = None,
    docs: Optional[list[ApprovalDocument]] = None,
    finals: tuple[int, ...] = (),
    names: Optional[dict[int, str]] = None,
) -> dict[str, Any]:
    names = names or {}
    finance = settlement.is_finance(viewer)
    open_request = (
        request is not None and request.settlement_status in OPEN_SETTLEMENT_STATUSES
    )
    is_author = request is not None and viewer.id == request.requester_user_id
    editable = doc.status == "pinned" and doc.topup_status != "pending"
    comparison = None
    if request is not None and request.recurrence != "once":
        comparison = settlement.compare(request, docs or [doc], doc=doc).as_json()
    elif request is not None:
        comparison = settlement.compare(request, docs or [doc]).as_json()
    over = comparison is not None and comparison["status"] == "over"
    return {
        "id": doc.id,
        "source": doc.source,
        "doc_type": doc.doc_type,
        "status": doc.status,
        "status_label": DOC_STATUS_LABELS[doc.status],
        "approval_request_id": doc.approval_request_id,
        "match_reason": doc.match_reason,
        "match_reason_label": MATCH_REASON_LABELS.get(doc.match_reason or ""),
        "ksef_number": doc.ksef_number,
        "seller_nip": doc.seller_nip,
        "seller_name": doc.seller_name,
        "invoice_number": doc.invoice_number,
        "issue_date": _iso(doc.issue_date),
        "currency": doc.currency,
        "net_amount": _money(doc.net_amount),
        "vat_amount": _money(doc.vat_amount),
        "gross_amount": _money(doc.gross_amount),
        "file_name": doc.file_name,
        "has_file": doc.file_path is not None,
        "read_status": doc.read_status,
        "topup": {
            "status": doc.topup_status,
            "amount": _money(doc.topup_amount),
            "requested_at": _iso(doc.topup_requested_at),
            "decided_at": _iso(doc.topup_decided_at),
            "decided_by_name": names.get(doc.topup_decided_by)
            if doc.topup_decided_by
            else None,
            "note": doc.topup_note,
        }
        if doc.topup_status
        else None,
        "settled_at": _iso(doc.settled_at),
        "settled_by_name": names.get(doc.settled_by) if doc.settled_by else None,
        "settle_note": doc.settle_note,
        "close_note": doc.close_note,
        "comparison": comparison,
        "can_edit": editable and (finance or viewer.id == doc.added_by),
        "can_remove": editable
        and (finance or (viewer.id == doc.added_by and doc.file_path is not None)),
        "can_request_topup": editable
        and open_request
        and over
        and doc.topup_status is None
        and (finance or is_author),
        "can_decide_topup": doc.topup_status == "pending"
        and viewer.id in finals
        and not is_author,
        "can_settle": finance and not is_author and doc.status == "pinned",
    }


def settlement_block(
    request: ApprovalRequest,
    docs: list[ApprovalDocument],
    *,
    viewer: User,
    finals: tuple[int, ...] = (),
    names: Optional[dict[int, str]] = None,
    client_name: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    if request.settlement_status is None:
        return None
    names = names or {}
    finance = settlement.is_finance(viewer)
    is_author = viewer.id == request.requester_user_id
    open_now = request.settlement_status in OPEN_SETTLEMENT_STATUSES
    attached = [d for d in docs if d.status in ("pinned", "settled")]
    return {
        "status": request.settlement_status,
        "status_label": settlement.STATUS_LABELS[request.settlement_status],
        "expires_on": _iso(settlement.expiry(request)),
        "renews_on": _iso(request.renews_on),
        "renewal_asked_for": _iso(request.renewal_asked_for),
        "renewal_confirmed_for": _iso(request.renewal_confirmed_for),
        "ended_on": _iso(request.ended_on),
        "settled_at": _iso(request.settled_at),
        "settled_by_name": names.get(request.settled_by)
        if request.settled_by
        else None,
        "seller_nip": request.seller_nip,
        "client_id": request.client_id,
        "client_name": client_name,
        "tolerance_percent": TOPUP_TOLERANCE_PERCENT,
        "comparison": settlement.compare(request, attached).as_json()
        if request.recurrence == "once"
        else None,
        "documents": [
            document_payload(
                doc,
                viewer=viewer,
                request=request,
                docs=attached,
                finals=finals,
                names=names,
            )
            for doc in attached
        ],
        "can_add_document": open_now and (is_author or finance),
        "can_answer_renewal": request.settlement_status == "active"
        and request.renews_on is not None
        and (is_author or finance),
        "can_end": request.settlement_status == "active" and (is_author or finance),
    }


__all__ = ["DOC_STATUS_LABELS", "document_payload", "settlement_block"]
