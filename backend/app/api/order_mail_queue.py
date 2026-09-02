"""Kolejka zamówień z maila: lista, szczegół, PDF, „Zastosuj", „Odrzuć".

Zakres widoczności = zakres portfela: admin / HoR / finance widzą wszystko,
Delivery Lead wyłącznie klientów, do których jest przypisany (ta sama
granica co ``require_dl_assigned_or_admin``). Kwoty REDAGOWANE tą samą regułą
co endpoint odczytu (``_order_finance_visible``): rola bez prawa do finansów
klienta widzi osoby, okres i powody, ale nie stawki — także w ``fields`` wiersza.

„Zastosuj" to zapis finansowy: wymaga ``_can_manage_order_finance`` (admin
albo PRZYPISANY DL). HoR przechodzi ``DlAssignedOrAdmin`` w innych miejscach,
ale tego NIE — przycisk jest dla niego ukryty, a endpoint odmawia.
"""

# Bez `from __future__ import annotations` (PEP 563 vs FastAPI/slowapi).
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.client_orders import (
    _can_manage_order_finance,
    _dl_assigned_to_client,
    _order_finance_visible,
)
from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.client import Client
from app.models.order_mail import (
    OUTCOME_APPLIED,
    OUTCOME_DISMISSED,
    OUTCOME_NEEDS_REVIEW,
    OUTCOMES,
    OrderMailDocument,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import UserRole
from app.services import storage_service
from app.services.order_mail_apply import apply_document

router = APIRouter()

_FINANCE_KEYS = (
    "rate_client",
    "rate_client_md",
    "rate_client_gross",
    "total_value",
    "currency",
)
_ORG_WIDE_ROLES = {UserRole.admin, UserRole.head_of_recruitment, UserRole.finance}


def _user_roles(user) -> set:
    roles = {user.role}
    for r in getattr(user, "roles", None) or []:
        try:
            roles.add(UserRole(r))
        except ValueError:
            continue
    return roles


async def _visible_client_ids(db: AsyncSession, user) -> Optional[set[int]]:
    """None = wszyscy klienci; zbiór = tylko ci; pusty zbiór = nic."""
    roles = _user_roles(user)
    if roles & _ORG_WIDE_ROLES:
        return None
    if UserRole.delivery_lead in roles:
        ids = (
            await db.execute(
                select(DeliveryLeadClientAssignment.client_id).where(
                    DeliveryLeadClientAssignment.delivery_lead_user_id == user.id
                )
            )
        ).scalars()
        return set(ids)
    return set()


def _redact_extraction(
    extraction: Optional[dict], *, show_finance: bool
) -> Optional[dict]:
    if extraction is None or show_finance:
        return extraction
    out = {k: (None if k in _FINANCE_KEYS else v) for k, v in extraction.items()}
    out["consultant_rows"] = [
        {**r, "rate_client": None} for r in (extraction.get("consultant_rows") or [])
    ]
    out["confidence"] = {
        k: v
        for k, v in (extraction.get("confidence") or {}).items()
        if k not in _FINANCE_KEYS
    }
    out["uncertain_reasons"] = (
        ["Sprawdź odczytane dane przed zapisem."] if extraction.get("uncertain") else []
    )
    return out


def _redact_proposal(proposal: Optional[dict], *, show_finance: bool) -> Optional[dict]:
    if proposal is None or show_finance:
        return proposal
    return {
        **proposal,
        "rows": [{**r, "rate_client": None} for r in (proposal.get("rows") or [])],
    }


async def _serialize(db: AsyncSession, doc: OrderMailDocument, user) -> Dict[str, Any]:
    dl_assigned = (
        await _dl_assigned_to_client(db, user, doc.client_id)
        if doc.client_id
        else False
    )
    can_finance = _can_manage_order_finance(user, dl_assigned=dl_assigned)
    show_finance = _order_finance_visible(user, can_finance=can_finance)
    # Nazwa klienta osobnym zapytaniem — relacja `doc.client` w sesji async to
    # lazy load, czyli MissingGreenlet i 500 bez CORS („Network Error").
    client_name = (
        await db.scalar(select(Client.name).where(Client.id == doc.client_id))
        if doc.client_id
        else None
    )
    return {
        "id": doc.id,
        "received_at": doc.received_at.isoformat() if doc.received_at else None,
        "sender_email": doc.sender_email,
        "subject": doc.subject,
        "attachment_name": doc.attachment_name,
        "outcome": doc.outcome,
        "client_id": doc.client_id,
        "client_name": client_name,
        "identification_method": doc.identification_method,
        "identification_reason": doc.identification_reason,
        "client_policy": doc.client_policy,
        "gate_verdict": doc.gate_verdict,
        "gate_reasons": doc.gate_reasons or [],
        "document_meta": doc.document_meta,
        "extraction": _redact_extraction(doc.extraction, show_finance=show_finance),
        "proposal": _redact_proposal(doc.proposal, show_finance=show_finance),
        "applied_order_id": doc.applied_order_id,
        "applied_at": doc.applied_at.isoformat() if doc.applied_at else None,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "error": doc.error,
        "can_apply": can_finance and doc.outcome == OUTCOME_NEEDS_REVIEW,
        "has_file": bool(doc.storage_path),
    }


async def _load_visible(db: AsyncSession, doc_id: int, user) -> OrderMailDocument:
    doc = await db.get(OrderMailDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")
    visible = await _visible_client_ids(db, user)
    if visible is not None and (doc.client_id is None or doc.client_id not in visible):
        raise HTTPException(status_code=403, detail="Brak dostępu do tego klienta")
    return doc


@router.get("/queue")
async def list_queue(
    user: CurrentUser,
    outcome: str = Query(OUTCOME_NEEDS_REVIEW),
    client_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if outcome not in OUTCOMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nieznany wynik {outcome!r}; dozwolone: {', '.join(OUTCOMES)}",
        )
    visible = await _visible_client_ids(db, user)
    if visible is not None and not visible:
        raise HTTPException(status_code=403, detail="Brak przypisanych klientów")
    stmt = select(OrderMailDocument).where(OrderMailDocument.outcome == outcome)
    count_stmt = (
        select(func.count())
        .select_from(OrderMailDocument)
        .where(OrderMailDocument.outcome == outcome)
    )
    if visible is not None:
        stmt = stmt.where(OrderMailDocument.client_id.in_(visible))
        count_stmt = count_stmt.where(OrderMailDocument.client_id.in_(visible))
    if client_id is not None:
        stmt = stmt.where(OrderMailDocument.client_id == client_id)
        count_stmt = count_stmt.where(OrderMailDocument.client_id == client_id)
    total = await db.scalar(count_stmt)
    docs = (
        (
            await db.execute(
                stmt.order_by(
                    OrderMailDocument.received_at.desc().nullslast(),
                    OrderMailDocument.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {"total": total or 0, "items": [await _serialize(db, d, user) for d in docs]}


@router.get("/queue/{doc_id}")
async def get_queue_item(
    doc_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    doc = await _load_visible(db, doc_id, user)
    return await _serialize(db, doc, user)


@router.get("/queue/{doc_id}/file")
async def download_queue_file(
    doc_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    doc = await _load_visible(db, doc_id, user)
    if not doc.storage_path:
        raise HTTPException(status_code=404, detail="Brak pliku")
    path = storage_service.get_order_mail_attachment_path(doc.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plik nie istnieje na dysku")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=doc.attachment_name or "zamowienie.pdf",
    )


async def _require_apply_rights(db: AsyncSession, doc: OrderMailDocument, user) -> None:
    dl_assigned = (
        await _dl_assigned_to_client(db, user, doc.client_id)
        if doc.client_id
        else False
    )
    if not _can_manage_order_finance(user, dl_assigned=dl_assigned):
        raise HTTPException(
            status_code=403,
            detail="Zapis zamówienia wymaga uprawnień admina lub przypisanego Delivery Leada",
        )


@router.post("/queue/{doc_id}/apply")
async def apply_queue_item(
    doc_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    doc = await _load_visible(db, doc_id, user)
    await _require_apply_rights(db, doc, user)
    if doc.outcome != OUTCOME_NEEDS_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Dokument nie czeka na weryfikację (stan: {doc.outcome})",
        )
    if not doc.proposal or not (doc.proposal.get("rows") or []):
        raise HTTPException(
            status_code=422, detail="Brak planu zapisu — uzupełnij zamówienie ręcznie"
        )
    result = await apply_document(db, doc, actor_user_id=user.id)
    doc.reviewed_by_user_id = user.id
    doc.reviewed_at = datetime.now(timezone.utc)
    if result.ok:
        doc.outcome = OUTCOME_APPLIED
        doc.error = None
    else:
        doc.error = (
            result.error or "; ".join(r.error for r in result.rows if r.error)
        )[:2000]
    await db.commit()
    await db.refresh(doc)
    return {
        "ok": result.ok,
        "result": result.as_dict(),
        "document": await _serialize(db, doc, user),
    }


@router.post("/queue/{doc_id}/dismiss")
async def dismiss_queue_item(
    doc_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    doc = await _load_visible(db, doc_id, user)
    await _require_apply_rights(db, doc, user)
    if doc.outcome != OUTCOME_NEEDS_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Dokument nie czeka na weryfikację (stan: {doc.outcome})",
        )
    doc.outcome = OUTCOME_DISMISSED
    doc.reviewed_by_user_id = user.id
    doc.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(doc)
    return await _serialize(db, doc, user)
