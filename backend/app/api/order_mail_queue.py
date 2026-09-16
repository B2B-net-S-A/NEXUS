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
from pydantic import BaseModel, Field
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
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_SCHEDULED,
    ClientOrderGroup,
)
from app.models.order_mail import (
    OUTCOME_APPLIED,
    OUTCOME_DISMISSED,
    OUTCOME_NEEDS_REVIEW,
    OUTCOMES,
    OrderMailDocument,
    OrderMailRecheckRun,
)
from app.models.user import User, UserRole
from app.services import storage_service
from app.services.access_scope import resolve_delivery_lead_client_ids
from app.services.order_mail_apply import apply_document
from app.services.order_mail_ingest import (
    ingest_is_running,
    read_state,
    replan_and_apply,
    start_ingest_task,
    sync_snapshot,
)
from app.services.order_mail_planner import DECIDE_PERSON_ORDER_TYPES, titles_collide
from app.services.order_pdf_parser import polish_gate_reason

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

#: Grupy przyjmujące nowych konsultantów — lustro bramki ``add_line``.
_GROUP_STATUSES_ACCEPTING_LINES = (GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED, "draft")

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

    HoR and TAC do not independently enter Delivery, so only Admin, Delivery
    Lead, or Finance can supersede the TCM read-only projection here.
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

    def redact_rows(rows: list) -> list:
        return [
            {
                **r,
                **{key: None for key in _FINANCE_KEYS if key in r},
                "uncertain_reason": (
                    "Sprawdź odczytane dane przed zapisem."
                    if r.get("uncertain_reason")
                    else None
                ),
            }
            for r in rows
        ]

    out["consultant_rows"] = redact_rows(extraction.get("consultant_rows") or [])
    # Niezależny odczyt modelu (Alior) niesie te same kwoty co wiersze osób.
    if extraction.get("model_rows") is not None:
        out["model_rows"] = redact_rows(extraction["model_rows"])
    out["confidence"] = {
        k: v
        for k, v in (extraction.get("confidence") or {}).items()
        if k not in _FINANCE_KEYS
    }
    out["uncertain_reasons"] = (
        ["Sprawdź odczytane dane przed zapisem."] if extraction.get("uncertain") else []
    )
    return out


def _redact_proposal(
    proposal: Optional[dict], *, show_finance: bool, read_only_tcm: bool = False
) -> Optional[dict]:
    if proposal is None or (show_finance and not read_only_tcm):
        return proposal
    rows = []
    for r in proposal.get("rows") or []:
        row = {**r}
        if not show_finance:
            row["rate_client"] = None
        if read_only_tcm and row.get("reasons"):
            # Lustro `gate_reasons` dla TCM: powody planu cytują szczegóły
            # (np. datę końca kontraktu), a TCM ma tu bezpieczną projekcję.
            row["reasons"] = ["Sprawdź odczytane dane przed zapisem."]
        rows.append(row)
    return {**proposal, "rows": rows}


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
            else [polish_gate_reason(r) for r in doc.gate_reasons or []]
        ),
        "document_meta": doc.document_meta,
        "extraction": _redact_extraction(doc.extraction, show_finance=show_finance),
        "proposal": _redact_proposal(
            doc.proposal, show_finance=show_finance, read_only_tcm=read_only_tcm
        ),
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


async def _load_visible(
    db: AsyncSession, doc_id: int, user, *, for_update=False
) -> OrderMailDocument:
    doc = (
        await db.scalar(
            select(OrderMailDocument)
            .where(OrderMailDocument.id == doc_id)
            .with_for_update()
        )
        if for_update
        else await db.get(OrderMailDocument, doc_id)
    )
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


@router.get("/recheck-runs")
async def list_recheck_runs(
    user: OrderMailUser,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Historia automatycznej weryfikacji — co zrobił każdy godzinowy bieg.

    Zakres jak w kolejce: Delivery Lead widzi wpisy swojego portfela, a liczby
    są PRZELICZANE z widocznych wpisów. Globalne „sprawdzono 12" nad listą
    z jednym wierszem to ekran, który sam sobie przeczy.

    TCM dostaje liczby bez powodów — te cytują nazwiska i nazwy załączników
    (lustro redakcji w ``_serialize`` i w ``/sync/status``).
    """
    visible = await _visible_client_ids(db, user)
    redact = _is_read_only_tcm(user)
    rows = (
        await db.execute(
            select(OrderMailRecheckRun)
            .order_by(
                OrderMailRecheckRun.started_at.desc(), OrderMailRecheckRun.id.desc()
            )
            .limit(limit)
        )
    ).scalars()
    out: list[Dict[str, Any]] = []
    for run in rows:
        entries = [e for e in (run.details or []) if isinstance(e, dict)]
        if visible is not None:
            entries = [e for e in entries if e.get("client_id") in visible]
        scoped = visible is not None
        if redact:
            entries = [{**e, "reasons": [], "people": []} for e in entries]
        applied = sum(1 for e in entries if e.get("outcome") == "applied")
        held = len(entries) - applied
        out.append(
            {
                "id": run.id,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "trigger": run.trigger,
                "checked": len(entries) if scoped else run.checked,
                "applied": applied if scoped else run.applied,
                "held": held if scoped else run.held,
                "entries": entries,
            }
        )
    return {"items": out, "scoped": visible is not None}


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
        raise HTTPException(status_code=403, detail="Brak dostępnych klientów")
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
    dl_assigned = (
        await _dl_assigned_to_client(db, user, doc.client_id)
        if doc.client_id
        else False
    )
    can_finance = _can_manage_order_finance(user, dl_assigned=dl_assigned)
    if not _order_finance_visible(user, can_finance=can_finance):
        raise HTTPException(
            status_code=403,
            detail="Plik zamówienia z kwotami wymaga przypisania do klienta",
        )
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


@router.post("/queue/{doc_id}/refresh-plan")
async def refresh_queue_plan(
    doc_id: int, user: OrderMailUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    doc = await _load_visible(db, doc_id, user, for_update=True)
    await _require_apply_rights(db, doc, user)
    applied_rows = ((doc.proposal or {}).get("apply_result") or {}).get("rows") or []
    if (
        doc.outcome != OUTCOME_NEEDS_REVIEW
        or doc.applied_order_id
        or any(r.get("order_id") for r in applied_rows)
    ):
        raise HTTPException(
            status_code=409,
            detail="Można przeliczyć wyłącznie plan bez zapisanych zamówień",
        )
    if not doc.client_id or not doc.extraction:
        raise HTTPException(
            status_code=422, detail="Brak odczytu lub rozpoznanego klienta"
        )
    if (
        not doc.storage_path
        or not storage_service.get_order_mail_attachment_path(
            doc.storage_path
        ).is_file()
    ):
        raise HTTPException(status_code=404, detail="Brak zapisanego pliku PDF")
    # Zapis pewnego planu jest tu AUTOMATYCZNY (człowiek kliknął „Przelicz”,
    # nie „Zastosuj”) — ta sama funkcja co przeliczenie po zmianie reguły
    # klienta w biegu skrzynki. Aktor idzie wyłącznie do atrybucji: historia
    # i zamówienie mają wskazywać osobę, która zapis uruchomiła.
    try:
        await replan_and_apply(
            db,
            doc,
            actor_user_id=user.id,
            # PFRON może zmienić klienta. Prawo do starego duplikatu nie daje
            # prawa do nowego rekordu ani jego danych finansowych.
            before_apply=lambda: _require_apply_rights(db, doc, user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(doc)
    return await _serialize(db, doc, user)


async def _close_review_cards(db: AsyncSession, doc_id: int) -> None:
    """Zdejmij kartę „czeka na weryfikację" z panelu „Moi klienci" od razu.

    Dokument opuścił kolejkę, więc sprawa nie istnieje — nie czekamy na dobowy
    skaner. Status ``resolved``, nie ``handled``: to nie odhaczenie DL.
    """
    from app.services.dl_alerts import resolve_entity_alerts

    await resolve_entity_alerts(
        db, alert_type="order_mail_review", entity_key=f"order_mail:{doc_id}"
    )


@router.post("/queue/{doc_id}/apply")
async def apply_queue_item(
    doc_id: int, user: OrderMailUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    doc = await _load_visible(db, doc_id, user, for_update=True)
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
        await _close_review_cards(db, doc.id)
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


def _order_type_of(doc: OrderMailDocument) -> str:
    """Typ zamówienia z planu dokumentu — MD albo kosztowe (okno grup)."""

    for row in (doc.proposal or {}).get("rows") or []:
        if row.get("order_type") in DECIDE_PERSON_ORDER_TYPES:
            return row["order_type"]
    return "md"


@router.get("/queue/{doc_id}/order-target")
async def queue_order_target(
    doc_id: int, user: OrderMailUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Dokąd prowadzi „Rozstrzygnij w oknie zamówienia".

    Zamówienie MD/kosztowe z osobą nieaktywną albo nieznalezioną nie może być
    zapisane automatem (``ACTION_DECIDE_PERSON``) — decyzję zostaw / wznów /
    zastąp / usuń podejmuje Delivery Lead w oknie zamówienia klienta, tym samym
    co przy ręcznym wgraniu PDF-a. Jeżeli u klienta jest już otwarte zamówienie
    o tym numerze, okno otwiera się w trybie „Uzupełnij zamówienie" (dopisanie
    osób), inaczej jako „Nowe zamówienie".
    """
    doc = await _load_visible(db, doc_id, user)
    await _require_apply_rights(db, doc, user)
    if doc.outcome != OUTCOME_NEEDS_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Dokument nie czeka na weryfikację (stan: {doc.outcome})",
        )
    if not doc.client_id or not doc.storage_path:
        raise HTTPException(
            status_code=422, detail="Brak rozpoznanego klienta albo pliku PDF"
        )
    number = (doc.proposal or {}).get("order_number") or (doc.extraction or {}).get(
        "title"
    )
    group_id: Optional[int] = None
    if number:
        groups = (
            await db.execute(
                select(ClientOrderGroup.id, ClientOrderGroup.order_number)
                .where(
                    ClientOrderGroup.client_id == doc.client_id,
                    ClientOrderGroup.status.in_(_GROUP_STATUSES_ACCEPTING_LINES),
                )
                .order_by(ClientOrderGroup.id.desc())
            )
        ).all()
        group_id = next(
            (gid for gid, gnum in groups if titles_collide(gnum, number)), None
        )
    return {
        "client_id": doc.client_id,
        "order_group_id": group_id,
        "order_type": _order_type_of(doc),
        "order_number": number,
        "attachment_name": doc.attachment_name,
    }


class ResolvedInOrderRequest(BaseModel):
    order_group_id: int = Field(..., gt=0)


@router.post("/queue/{doc_id}/resolved-in-order")
async def mark_queue_item_resolved_in_order(
    doc_id: int,
    body: ResolvedInOrderRequest,
    user: OrderMailUser,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Dokument z maila rozstrzygnięty w oknie zamówienia — zdejmij z kolejki.

    Zapis zamówienia zrobiło już okno (``POST /order-groups`` albo
    ``…/lines/batch``). Tu wyłącznie łączymy dokument z tym zamówieniem, żeby
    kolejka nie czekała w nieskończoność na „Zastosuj", którego plan
    z ``decide_person`` i tak by nie wykonał. ``applied_order_id`` zostaje
    pusty: wskazuje zamówienie zapisane PRZEZ AUTOMAT maila (m.in. aktywacja
    szkicu po podpisie umowy, ``complete_signed_mail_drafts``), a linii grupy
    ten mechanizm dotykać nie może.
    """
    doc = await _load_visible(db, doc_id, user, for_update=True)
    await _require_apply_rights(db, doc, user)
    if doc.outcome != OUTCOME_NEEDS_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Dokument nie czeka na weryfikację (stan: {doc.outcome})",
        )
    group = await db.scalar(
        select(ClientOrderGroup).where(
            ClientOrderGroup.id == body.order_group_id,
            ClientOrderGroup.client_id == doc.client_id,
        )
    )
    if group is None:
        raise HTTPException(
            status_code=422,
            detail="To zamówienie nie należy do klienta z dokumentu",
        )
    now = datetime.now(timezone.utc)
    doc.outcome = OUTCOME_APPLIED
    doc.error = None
    doc.reviewed_by_user_id = user.id
    doc.reviewed_at = now
    doc.applied_by_user_id = user.id
    doc.applied_at = now
    doc.proposal = {
        **(doc.proposal or {}),
        "resolved_in_order": {
            "order_group_id": group.id,
            "order_number": group.order_number,
            "resolved_by_user_id": user.id,
            "resolved_at": now.isoformat(),
        },
    }
    await _close_review_cards(db, doc.id)
    db.add(
        Activity(
            entity_type="client",
            entity_id=doc.client_id,
            action="order_mail_resolved_in_order",
            user_id=user.id,
            details={"document_id": doc.id, "order_group_id": group.id},
        )
    )
    await db.commit()
    await db.refresh(doc)
    return await _serialize(db, doc, user)


@router.post("/queue/{doc_id}/dismiss")
async def dismiss_queue_item(
    doc_id: int, user: OrderMailUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    doc = await _load_visible(db, doc_id, user, for_update=True)
    await _require_apply_rights(db, doc, user)
    if doc.outcome != OUTCOME_NEEDS_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Dokument nie czeka na weryfikację (stan: {doc.outcome})",
        )
    doc.outcome = OUTCOME_DISMISSED
    doc.reviewed_by_user_id = user.id
    doc.reviewed_at = datetime.now(timezone.utc)
    await _close_review_cards(db, doc.id)
    await db.commit()
    await db.refresh(doc)
    return await _serialize(db, doc, user)
