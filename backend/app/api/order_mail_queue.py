"""Kolejka zamówień z maila: lista, szczegół, PDF, „Zastosuj", „Odrzuć",
„Pobierz zamówienia z maila" i stan ostatniego sprawdzenia skrzynki.

To powierzchnia Delivery. Admin i Finance widzą organizację, Delivery Lead
wyłącznie jawnie przypisany portfel, a Talent Community Manager globalną,
bezpieczną projekcję bez kwot, surowego PDF-u i komunikatów mogących cytować
stawki. Pozostałe role, w tym Head of Recruitment, odcina bramka sekcji.

„Zastosuj" i „Odrzuć" wymagają zapisu Delivery oraz
``_can_manage_order_finance``: Admina albo przypisanego Delivery Leada.
"""

# Bez `from __future__ import annotations` (PEP 563 vs FastAPI/slowapi).
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.client_orders import (
    _can_manage_order_finance,
    _dl_assigned_to_client,
    _order_finance_visible,
)
from app.api.deps import require_roles
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.client import Client
from app.models.order_mail import (
    OUTCOME_APPLIED,
    OUTCOME_DISMISSED,
    OUTCOME_NEEDS_REVIEW,
    OUTCOMES,
    OrderMailDocument,
)
from app.models.user import User, UserRole
from app.services import storage_service
from app.services.access_scope import resolve_delivery_lead_client_ids
from app.services.order_mail_apply import apply_document
from app.services.order_mail_ingest import (
    ingest_is_running,
    read_state,
    start_ingest_task,
    sync_snapshot,
)

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

# Bramka klasy roli jako ZALEŻNOŚĆ (widoczna w grafie FastAPI i w kontrakcie
# `test_route_authz_contract`), lustro sidebara/middleware `/order-mail`.
# Drobniejsze zawężenie — do własnego portfela (DL) i do prawa zapisu kwot
# („Zastosuj") — jest per dokument i zostaje w handlerach.
OrderMailUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.finance,
            UserRole.delivery_lead,
            UserRole.talent_community_manager,
        )
    ),
]

OrderMailFileUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.finance,
            UserRole.delivery_lead,
        )
    ),
]

# „Pobierz zamówienia z maila" dotyczy CAŁEJ skrzynki, nie jednego dokumentu,
# więc bramka jest rolowa, nie per klient: role, które w tej kolejce pracują
# (Admin, Finance, Delivery Lead). Talent Community Manager ma tu wyłącznie
# bezpieczny odczyt — stan sprawdzenia widzi (żeby wiedzieć, jak świeża jest
# kolejka), przycisku nie dostaje.
# Jedno źródło prawdy dla bramki HTTP i dla ``can_trigger`` w statusie —
# rozjazd tych dwóch dałby przycisk widoczny komuś, kto po kliknięciu dostaje 403.
_SYNC_TRIGGER_ROLES = (UserRole.admin, UserRole.finance, UserRole.delivery_lead)
OrderMailSyncUser = Annotated[User, Depends(require_roles(*_SYNC_TRIGGER_ROLES))]

_FINANCE_KEYS = (
    "rate_client",
    "rate_client_md",
    "rate_client_gross",
    "total_value",
    "currency",
)
_ORG_WIDE_ROLES = {
    UserRole.admin,
    UserRole.finance,
    UserRole.talent_community_manager,
}


def _user_roles(user) -> set:
    roles = {user.role}
    for r in getattr(user, "roles", None) or []:
        try:
            roles.add(UserRole(r))
        except ValueError:
            continue
    return roles


def _is_read_only_tcm(user) -> bool:
    """TCM ceiling for Delivery mail, irrespective of HoR/TAC secondary roles.

    HoR and TAC do not independently enter Delivery, so only Admin, assigned
    Delivery Lead, or Finance can supersede the TCM read-only projection here.
    """

    roles = _user_roles(user)
    return UserRole.talent_community_manager in roles and not roles.intersection(
        {UserRole.admin, UserRole.finance, UserRole.delivery_lead}
    )


async def _visible_client_ids(db: AsyncSession, user) -> Optional[set[int]]:
    """None = wszyscy klienci; zbiór = tylko ci; pusty zbiór = nic."""
    delivery_client_ids = await resolve_delivery_lead_client_ids(user, db)
    if delivery_client_ids is not None:
        return set(delivery_client_ids)
    roles = _user_roles(user)
    if roles & _ORG_WIDE_ROLES:
        return None
    return set()


def _redact_extraction(
    extraction: Optional[dict], *, show_finance: bool
) -> Optional[dict]:
    if extraction is None or show_finance:
        return extraction
    out = {k: (None if k in _FINANCE_KEYS else v) for k, v in extraction.items()}
    out["consultant_rows"] = [
        {
            **r,
            "rate_client": None,
            "uncertain_reason": (
                "Sprawdź odczytane dane przed zapisem."
                if r.get("uncertain_reason")
                else None
            ),
        }
        for r in (extraction.get("consultant_rows") or [])
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
    read_only_tcm = _is_read_only_tcm(user)
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
        "identification_reason": (
            "Klient rozpoznany automatycznie."
            if read_only_tcm and doc.identification_reason
            else doc.identification_reason
        ),
        "client_policy": doc.client_policy,
        "gate_verdict": doc.gate_verdict,
        "gate_reasons": (
            ["Sprawdź odczytane dane przed zapisem."]
            if read_only_tcm and doc.gate_reasons
            else (doc.gate_reasons or [])
        ),
        "document_meta": doc.document_meta,
        "extraction": _redact_extraction(doc.extraction, show_finance=show_finance),
        "proposal": _redact_proposal(doc.proposal, show_finance=show_finance),
        "applied_order_id": doc.applied_order_id,
        "applied_at": doc.applied_at.isoformat() if doc.applied_at else None,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "error": (
            "Przetwarzanie dokumentu zakończyło się błędem."
            if read_only_tcm and doc.error
            else doc.error
        ),
        "can_apply": can_finance and doc.outcome == OUTCOME_NEEDS_REVIEW,
        "has_file": bool(doc.storage_path) and not read_only_tcm,
    }


async def _load_visible(db: AsyncSession, doc_id: int, user) -> OrderMailDocument:
    doc = await db.get(OrderMailDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")
    visible = await _visible_client_ids(db, user)
    if visible is not None and (doc.client_id is None or doc.client_id not in visible):
        raise HTTPException(status_code=403, detail="Brak dostępu do tego klienta")
    return doc


@router.get("/sync/status")
async def sync_status(
    user: OrderMailUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Kiedy skrzynka była ostatnio sprawdzana i co z tego wyszło.

    Wynik ostatniego ZAKOŃCZONEGO biegu (``last_completed``: ile nowych
    wiadomości, ile zapisanych automatycznie, ile do weryfikacji) oraz to,
    czy bieg trwa albo został przerwany. Liczby dotyczą całej skrzynki —
    kolejka poniżej jest zawężona do portfela, więc DL może zobaczyć
    „2 do weryfikacji" i pustą listę.
    """
    snapshot = sync_snapshot(await read_state(db), running=ingest_is_running())
    snapshot["can_trigger"] = bool(_user_roles(user) & set(_SYNC_TRIGGER_ROLES))
    last = snapshot.get("last_completed")
    if last and _is_read_only_tcm(user):
        # Treść błędów cytuje nazwy załączników i odpowiedzi Graph — lustro
        # redakcji ``error`` w ``_serialize``.
        if last.get("error"):
            last["error"] = "Sprawdzenie skrzynki zakończyło się błędem."
        last["errors"] = (
            ["Sprawdzenie skrzynki zakończyło się błędem."] if last["errors"] else []
        )
    return snapshot


@router.post("/sync")
async def trigger_sync(_user: OrderMailSyncUser) -> Dict[str, Any]:
    """„Pobierz zamówienia z maila": sprawdź skrzynkę teraz, poza harmonogramem.

    Bieg idzie w tle (parsowanie PDF-ów modelem trwa minuty — dłużej niż
    limit proxy), a wynik czyta się z ``GET /sync/status``. 409, gdy bieg
    już trwa: front dołącza do niego zamiast startować drugi.
    """
    if not settings.ORDER_MAIL_INGEST_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pobieranie zamówień z maila jest wyłączone (ORDER_MAIL_INGEST_ENABLED=false)",
        )
    if ingest_is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sprawdzanie skrzynki już trwa",
        )
    start_ingest_task(reason="manual")
    return {"status": "started"}


@router.get("/queue")
async def list_queue(
    user: OrderMailUser,
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
    doc_id: int, user: OrderMailUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    doc = await _load_visible(db, doc_id, user)
    return await _serialize(db, doc, user)


@router.get("/queue/{doc_id}/file")
async def download_queue_file(
    doc_id: int, user: OrderMailFileUser, db: AsyncSession = Depends(get_db)
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
    doc_id: int, user: OrderMailUser, db: AsyncSession = Depends(get_db)
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
    doc_id: int, user: OrderMailUser, db: AsyncSession = Depends(get_db)
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
