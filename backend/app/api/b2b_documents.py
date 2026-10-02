"""Generator dokumentów pochodnych: aneksy, rozwiązania, umowa przedwstępna.

Trasy pod ``/api/b2b-generator`` obok generatora umów — ten sam moduł w UI,
te same bramki (``B2BGeneratorAccess``, zakres klienta, widoczność stawek,
uprawnienie „Oznaczanie podpisu umowy B2B”). Definicje typów i pól:
``services/b2b_documents/registry.py``; skutki podpisu: ``effects.py``.

Dane wrażliwe (PESEL, dowód, adres zamieszkania) są przyjmowane w żądaniu
i trafiają wyłącznie do pliku — ``render_payload`` zapisuje wartości bez nich.
Ponowne pobranie takiego dokumentu wymaga podania ich jeszcze raz.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.b2b_contract_generator import (
    _DOCX_MEDIA,
    _ascii_filename,
    _assert_generator_client_access,
    _assert_signature_client_access,
    _generator_unscoped,
    _has_signature_permission,
    _load_legal_scoped_job,
    _require_contract_generation,
    _require_generated_contract_management,
    _require_generator_rate_content,
    _require_signature_confirmation,
    _scope_generator_query,
    _validate_candidate_job_link,
)
from app.api.contract_access import (
    B2BGeneratorAccess,
    assert_b2b_generator_action_access,
)
from app.api.financial_access import can_manage_finance_amounts
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.b2b_contract_document import B2BContractDocument
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.user import User, UserRole
from app.services.access_scope import resolve_delivery_lead_finance_client_ids
from app.services.action_permissions import (
    ActionAccess,
    ProductAction,
    has_permission,
)
from app.services import ezdrowie
from app.services.b2b_documents import annex_register, effects
from app.services.b2b_documents.context import (
    BaseContractInfo,
    build_document_context,
)
from app.services.b2b_documents.contract_versions import (
    COMPANY_VERSION,
    CURRENT_VERSION,
    VERSIONS,
    ContractVersionRefs,
    default_refs,
    notice_end_date,
    refs_for,
)
from app.services.client_access import assert_client_assignable
from app.services.permission_denial import ensure_permission
from app.services.b2b_documents.registry import (
    REF_LABELS,
    TYPES,
    DocumentType,
    invalid_values,
    missing_required,
    strip_sensitive,
)
from app.services.b2b_documents.render import (
    render_docx,
    render_html,
    template_key,
)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

RATE_ANNEX_TYPE = "annex_rate_change"


# ── schematy ─────────────────────────────────────────────────────────────────


class DocumentRequest(BaseModel):
    document_type: str
    language: str = "pl"
    parent_generated_contract_id: Optional[int] = None
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    values: dict[str, Any] = Field(default_factory=dict)
    #: Numery paragrafów, gdy wersja wzoru umowy bazowej jest nieznana.
    refs: Optional[dict[str, str]] = None


class SensitiveValues(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class PartnerNoticeRequest(BaseModel):
    parent_generated_contract_id: int
    delivered_on: date
    termination_date: Optional[date] = None


class DocumentItem(BaseModel):
    id: int
    document_type: str
    type_label: str
    family: str
    language: str
    label: str
    document_date: date
    parent_generated_contract_id: Optional[int] = None
    parent_contract_number: Optional[str] = None
    contract_id: Optional[int] = None
    candidate_id: Optional[int] = None
    partner_name: Optional[str] = None
    client_name: Optional[str] = None
    status: str
    signature_status: str
    signed_at: Optional[str] = None
    effect_applied_at: Optional[str] = None
    effect_summary: Optional[dict] = None
    created_by_name: Optional[str] = None
    created_at: Optional[str] = None
    requires_sensitive_input: bool = False
    sensitive_fields: list[str] = []
    can_edit: bool = False
    can_delete: bool = False
    can_confirm_signed: bool = False
    cancelled_reason: Optional[str] = None


# ── pomocnicze ───────────────────────────────────────────────────────────────


def _type_or_422(key: str) -> DocumentType:
    doc_type = TYPES.get(key)
    if doc_type is None:
        raise HTTPException(status_code=422, detail="Nieznany typ dokumentu.")
    return doc_type


def _language(doc_type: DocumentType, language: str) -> str:
    lang = "en" if (language or "pl").lower().startswith("en") else "pl"
    if lang not in doc_type.languages:
        raise HTTPException(
            status_code=422,
            detail=f"„{doc_type.label}” nie ma wersji w tym języku.",
        )
    return lang


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


async def _load_parent(
    db: AsyncSession, parent_id: int, *, lock: bool = False
) -> B2BGeneratedContract:
    stmt = select(B2BGeneratedContract).where(B2BGeneratedContract.id == parent_id)
    if lock:
        # `populate_existing`: wiersz bywa już w sesji (odczyt bez blokady
        # wcześniej w tym żądaniu) — bez tego blokada zwróciłaby stare pola.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=404, detail="Umowa bazowa nie istnieje.")
    return row


async def _authorize_parent(
    db: AsyncSession, user: User, parent: B2BGeneratedContract
) -> None:
    await _assert_generator_client_access(db, user, parent.client_id, write=True)
    await _require_generator_rate_content(
        db,
        user,
        parent.client_id,
        created_by=parent.created_by,
        job_id=parent.job_id,
    )


async def _base_info(
    db: AsyncSession, parent: B2BGeneratedContract | None
) -> BaseContractInfo:
    if parent is None:
        return BaseContractInfo()
    payload = parent.render_payload or {}
    legal_name = None
    if parent.client_id is not None:
        client = await db.get(Client, parent.client_id)
        legal_name = getattr(client, "legal_name", None) if client else None
    return BaseContractInfo(
        contract_number=parent.contract_number
        or getattr(parent, "raw_contract_number", None),
        signing_date=parent.signing_date,
        start_date=parent.start_date,
        start_date_mode=payload.get("start_date_mode")
        or getattr(parent, "start_date_mode", None),
        client_name=parent.client_name,
        client_legal_name=legal_name or parent.client_name,
        currency=str(payload.get("currency") or "PLN"),
        template_version=getattr(parent, "template_version", None),
    )


def _base_from_snapshot(snapshot: dict | None) -> BaseContractInfo:
    snapshot = snapshot or {}
    return BaseContractInfo(
        contract_number=snapshot.get("contract_number"),
        signing_date=_date(snapshot.get("signing_date")),
        start_date=_date(snapshot.get("start_date")),
        start_date_mode=snapshot.get("start_date_mode"),
        client_name=snapshot.get("client_name"),
        client_legal_name=snapshot.get("client_legal_name"),
        currency=snapshot.get("currency") or "PLN",
        template_version=snapshot.get("template_version"),
    )


def _base_snapshot(base: BaseContractInfo) -> dict[str, Any]:
    return {
        "contract_number": base.contract_number,
        "signing_date": base.signing_date.isoformat() if base.signing_date else None,
        "start_date": base.start_date.isoformat() if base.start_date else None,
        "start_date_mode": base.start_date_mode,
        "client_name": base.client_name,
        "client_legal_name": base.client_legal_name,
        "currency": base.currency,
        "template_version": base.template_version,
    }


def _needs_refs(doc_type: DocumentType, base: BaseContractInfo) -> bool:
    return doc_type.uses_refs and refs_for(base.template_version) is None


def _validate_values(
    doc_type: DocumentType,
    values: dict[str, Any],
    base: BaseContractInfo,
    refs: dict[str, str] | None,
) -> None:
    missing = missing_required(doc_type, values)
    if _needs_refs(doc_type, base) and not refs:
        missing.append("Numery paragrafów umowy bazowej")
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "document_fields_missing",
                "message": "Uzupełnij: " + ", ".join(missing) + ".",
                "missing": missing,
            },
        )
    problems = invalid_values(doc_type, values)
    if problems:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "document_values_invalid",
                "message": " ".join(problems),
                "problems": problems,
            },
        )


def _context(
    doc_type: DocumentType,
    values: dict[str, Any],
    language: str,
    base: BaseContractInfo,
    refs: dict[str, str] | None,
) -> dict[str, Any]:
    version_refs: ContractVersionRefs | None = refs_for(base.template_version)
    return build_document_context(
        doc_type,
        values,
        language=language,
        base=base,
        refs=version_refs or default_refs(),
        ref_overrides=refs if version_refs is None else None,
    )


def _document_label(doc: B2BContractDocument, doc_type: DocumentType) -> str:
    number = (doc.render_payload or {}).get("base", {}).get("contract_number")
    when = doc.document_date.strftime("%d.%m.%Y")
    if number:
        return f"{doc_type.label} z dnia {when} do umowy {number}"
    return f"{doc_type.label} z dnia {when}"


def _filename(doc_type: DocumentType, values: dict, doc_date: date | None) -> str:
    who = values.get("partner_name") or ""
    when = doc_date.isoformat() if doc_date else ""
    return _ascii_filename(f"{doc_type.label} {who} {when}".strip()) + ".docx"


def _docx_response(data: bytes, filename: str, doc_id: int | None) -> Response:
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Access-Control-Expose-Headers": "Content-Disposition, X-Document-Id",
    }
    if doc_id is not None:
        headers["X-Document-Id"] = str(doc_id)
    return Response(content=data, media_type=_DOCX_MEDIA, headers=headers)


async def _render_bytes(
    doc_type: DocumentType,
    language: str,
    context: dict[str, Any],
) -> bytes:
    key = template_key(doc_type.key, language)
    try:
        return await run_in_threadpool(render_docx, key, context)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500, detail="Brak szablonu tego dokumentu."
        ) from exc


async def _resolve_subject(
    db: AsyncSession, user: User, doc_type: DocumentType, request: DocumentRequest
) -> tuple[B2BGeneratedContract | None, BaseContractInfo, dict[str, Any]]:
    """Umowa bazowa (albo kandydat + rekrutacja) i kolumny wiązań dokumentu."""

    links: dict[str, Any] = {
        "contract_id": None,
        "candidate_id": request.candidate_id,
        "job_id": request.job_id,
        "client_id": None,
    }
    parent: B2BGeneratedContract | None = None
    if request.parent_generated_contract_id is not None:
        parent = await _load_parent(db, request.parent_generated_contract_id)
        await _authorize_parent(db, user, parent)
        links.update(
            contract_id=parent.contract_id,
            candidate_id=parent.candidate_id,
            job_id=parent.job_id,
            client_id=parent.client_id,
        )
    elif doc_type.parent == "b2b" and not doc_type.allows_external:
        raise HTTPException(status_code=422, detail="Wybierz umowę bazową z rejestru.")

    if doc_type.key == "preliminary_cez":
        if request.candidate_id is None or request.job_id is None:
            raise HTTPException(
                status_code=422,
                detail="Wybierz kandydata i rekrutację Centrum e-Zdrowia.",
            )
        job = await _load_legal_scoped_job(db, user, request.job_id, write=True)
        _, job = await _validate_candidate_job_link(
            db, candidate_id=request.candidate_id, job_id=job.id
        )
        if job.client_id != ezdrowie.EZDROWIE_CLIENT_ID:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Umowa przedwstępna dotyczy wyłącznie rekrutacji Centrum e-Zdrowia."
                ),
            )
        links.update(client_id=job.client_id)
    elif parent is None and (
        request.candidate_id is not None or request.job_id is not None
    ):
        # Dokument bez umowy bazowej (np. zlecenie) podpina się pod osobę
        # wyłącznie przez rekrutację, do której wołający ma dostęp — inaczej
        # dowolne `candidate_id` z żądania trafiałoby do wiersza bez kontroli
        # (a nieistniejące kończyło się 500 na kluczu obcym).
        if request.candidate_id is None or request.job_id is None:
            raise HTTPException(
                status_code=422,
                detail="Wybierz kandydata razem z rekrutacją, w której uczestniczy.",
            )
        job = await _load_legal_scoped_job(db, user, request.job_id, write=True)
        await _validate_candidate_job_link(
            db, candidate_id=request.candidate_id, job_id=job.id
        )
        links.update(client_id=job.client_id)
    base = _with_value_overrides(doc_type, await _base_info(db, parent), request.values)
    return parent, base, links


def _is_external(doc_type: DocumentType, parent: B2BGeneratedContract | None) -> bool:
    """Aneks do umowy spoza NEXUSA: dane umowy wpisane ręcznie, bez wiersza
    rejestru — dokumentu nie zapisujemy (ticket „Generator aneksów”, pkt 7.2)."""
    return parent is None and doc_type.allows_external and doc_type.parent == "b2b"


def _with_value_overrides(
    doc_type: DocumentType, base: BaseContractInfo, values: dict[str, Any]
) -> BaseContractInfo:
    """Generator aneksów: numer i data zawarcia umowy są polami formularza —
    migawka ``base`` ma pokazywać to, co trafiło do dokumentu."""
    if not doc_type.allows_external:
        return base
    number = str(values.get("contract_number") or "").strip()
    if number:
        base.contract_number = number
    signing = _date(values.get("contract_signing_date"))
    if signing is not None:
        base.signing_date = signing
    return base


async def _resolve_rate_clients(
    db: AsyncSession, values: dict[str, Any]
) -> dict[str, Any]:
    """Pełna nazwa klienta pozycji stawki — z NEXUSA, nie z żądania.

    Ticket: „Wpisuj pełną nazwę klienta z Nexusa, np. Bank Pocztowy S.A.”.
    Nazwa z przeglądarki mogłaby wpisać do aneksu dowolny tekst jako klienta."""
    items = values.get("rate_items")
    if not isinstance(items, list):
        return values
    resolved: list[Any] = []
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            resolved.append(item)
            continue
        entry = {**item, "client_name": None}
        client_id = item.get("client_id")
        if client_id not in (None, ""):
            try:
                cid = int(client_id)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=422,
                    detail=f"Pozycja stawki {number}: nieprawidłowy klient.",
                ) from None
            client = await assert_client_assignable(db, cid)
            if client is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Pozycja stawki {number}: klienta nie ma w NEXUSIE.",
                )
            entry["client_id"] = cid
            entry["client_name"] = (
                getattr(client, "legal_name", None) or client.name or ""
            ).strip() or None
        else:
            entry["client_id"] = None
        resolved.append(entry)
    return {**values, "rate_items": resolved}


async def _users(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows.all()}


async def _serialize(
    db: AsyncSession, rows: list[B2BContractDocument], user: User
) -> list[DocumentItem]:
    parent_ids = {
        r.parent_generated_contract_id for r in rows if r.parent_generated_contract_id
    }
    parents: dict[int, B2BGeneratedContract] = {}
    if parent_ids:
        result = await db.execute(
            select(B2BGeneratedContract).where(B2BGeneratedContract.id.in_(parent_ids))
        )
        parents = {p.id: p for p in result.scalars().all()}
    names = await _users(db, {r.created_by for r in rows if r.created_by})
    is_admin = user.has_role(UserRole.admin)
    try:
        _require_signature_confirmation(user)
        can_sign = True
    except HTTPException:
        can_sign = False
    # Aneks stawki potwierdza też posiadacz „Stawki i kwoty: zmiana” bez
    # uprawnienia do oznaczania podpisu (domyślnie Finanse, decyzja Artura
    # 27.09.2026). Konto z rolą Delivery Leada — tylko u klienta
    # z przypisania, stąd granica i klient każdego wiersza.
    rate_boundary = await resolve_delivery_lead_finance_client_ids(user, db)
    try:
        _require_generated_contract_management(user)
        can_manage = True
    except HTTPException:
        can_manage = False
    items: list[DocumentItem] = []
    for row in rows:
        doc_type = TYPES.get(row.document_type)
        if doc_type is None:
            continue
        payload = row.render_payload or {}
        values = payload.get("values") or {}
        parent = parents.get(row.parent_generated_contract_id or -1)
        open_unsigned = row.status == "issued" and row.signature_status != "signed_both"
        own = is_admin or row.created_by == user.id
        items.append(
            DocumentItem(
                id=row.id,
                document_type=row.document_type,
                type_label=doc_type.label,
                family=doc_type.family,
                language=row.language,
                label=_document_label(row, doc_type),
                document_date=row.document_date,
                parent_generated_contract_id=row.parent_generated_contract_id,
                parent_contract_number=(payload.get("base") or {}).get(
                    "contract_number"
                ),
                contract_id=row.contract_id,
                candidate_id=row.candidate_id,
                partner_name=values.get("partner_name"),
                client_name=(payload.get("base") or {}).get("client_name")
                or (parent.client_name if parent else None),
                status=row.status,
                signature_status=row.signature_status,
                signed_at=row.signed_at.isoformat() if row.signed_at else None,
                effect_applied_at=(
                    row.effect_applied_at.isoformat() if row.effect_applied_at else None
                ),
                effect_summary=row.effect_summary,
                created_by_name=names.get(row.created_by or -1),
                created_at=row.created_at.isoformat() if row.created_at else None,
                requires_sensitive_input=bool(doc_type.sensitive_keys),
                sensitive_fields=sorted(doc_type.sensitive_keys),
                can_edit=can_manage and open_unsigned and own,
                can_delete=can_manage and open_unsigned and own,
                can_confirm_signed=open_unsigned
                and (
                    can_sign
                    or (
                        row.document_type == RATE_ANNEX_TYPE
                        and can_manage_finance_amounts(
                            user,
                            client_id=row.client_id,
                            delivery_lead_finance_client_ids=rate_boundary,
                        )
                    )
                ),
                cancelled_reason=row.cancelled_reason,
            )
        )
    return items


async def _load_document(
    db: AsyncSession, user: User, doc_id: int, *, lock: bool = False
) -> tuple[B2BContractDocument, DocumentType, B2BGeneratedContract | None]:
    stmt = select(B2BContractDocument).where(B2BContractDocument.id == doc_id)
    if lock:
        stmt = stmt.with_for_update()
    doc = await db.scalar(stmt)
    if doc is None:
        raise HTTPException(status_code=404, detail="Dokument nie istnieje.")
    doc_type = _type_or_422(doc.document_type)
    parent = None
    if doc.parent_generated_contract_id is not None:
        parent = await _load_parent(db, doc.parent_generated_contract_id, lock=lock)
    if not _generator_unscoped(user):
        await _assert_generator_client_access(db, user, doc.client_id, write=False)
    if doc_type.carries_money:
        # Aneks stawki i umowa przedwstępna niosą kwotę — ta sama reguła
        # widoczności stawek co DOCX umowy bazowej (CLAUDE.md, audyt 22.09).
        await _require_generator_rate_content(
            db,
            user,
            doc.client_id,
            created_by=parent.created_by if parent else doc.created_by,
            job_id=parent.job_id if parent else doc.job_id,
        )
    return doc, doc_type, parent


async def _lock_contract_first(
    db: AsyncSession, *, doc_id: int | None = None, parent_id: int | None = None
) -> int | None:
    """Zablokuj kontrakt ZANIM zablokujesz dokument i wiersz rejestru.

    ``/terminate`` i nocny cron blokują kontrakt, a potem wiersze rejestru
    (``contract_termination_sync._rows_for_contract``); „Oznacz jako podpisany”
    i wypowiedzenie Partnera blokowały odwrotnie — wiersz, potem kontrakt —
    więc równoległe zakończenie tej samej osoby kończyło się zakleszczeniem
    (runda 6 audytu, LOCK-1). Odczyt powiązania idzie samymi kolumnami (bez
    encji w mapie tożsamości), więc blokada wiersza niżej wczyta świeży stan;
    wołający porównuje potem powiązanie z zablokowanym kontraktem."""
    contract_id: int | None = None
    if doc_id is not None:
        found = (
            await db.execute(
                select(
                    B2BContractDocument.contract_id,
                    B2BContractDocument.parent_generated_contract_id,
                ).where(B2BContractDocument.id == doc_id)
            )
        ).first()
        if found is None:
            return None
        contract_id = found.contract_id
        parent_id = found.parent_generated_contract_id
    if parent_id is not None:
        contract_id = await db.scalar(
            select(B2BGeneratedContract.contract_id).where(
                B2BGeneratedContract.id == parent_id
            )
        )
    if contract_id is not None:
        await db.execute(
            select(Contract.id).where(Contract.id == contract_id).with_for_update()
        )
    return contract_id


def _assert_same_locked_contract(locked: int | None, current: int | None) -> None:
    if locked != current:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Umowa została w międzyczasie powiązana z innym kontraktem — "
                "odśwież stronę i spróbuj ponownie."
            ),
        )


def _assert_editable(doc: B2BContractDocument, user: User) -> None:
    _require_generated_contract_management(user)
    if doc.status != "issued" or doc.signature_status == "signed_both":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Podpisanego albo anulowanego dokumentu nie można zmienić — "
                "jest zapisem tego, co strony podpisały."
            ),
        )
    if not user.has_role(UserRole.admin) and doc.created_by != user.id:
        raise HTTPException(
            status_code=403,
            detail="Poprawić albo usunąć dokument może jego autor albo administrator.",
        )


# ── trasy ────────────────────────────────────────────────────────────────────


@router.get("/document-types")
async def document_types(current_user: B2BGeneratorAccess) -> dict:
    """Definicje typów i pól — front buduje z nich jeden formularz."""
    return {
        "types": [t.to_public() for t in TYPES.values()],
        "ref_labels": REF_LABELS,
        "ref_defaults": default_refs().as_context(),
    }


@router.get("/documents/prefill")
async def document_prefill(
    current_user: B2BGeneratorAccess,
    document_type: str = Query(...),
    parent_generated_contract_id: Optional[int] = Query(None),
    candidate_id: Optional[int] = Query(None),
    job_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Wartości startowe formularza z umowy bazowej (albo z kandydata)."""
    doc_type = _type_or_422(document_type)
    today = business_today()
    values: dict[str, Any] = {"document_date": today.isoformat()}
    parent: B2BGeneratedContract | None = None
    if parent_generated_contract_id is not None:
        parent = await _load_parent(db, parent_generated_contract_id)
        await _authorize_parent(db, current_user, parent)
        # Kandydat umowy bazowej — nie ten z parametru, który mógłby wskazać
        # dowolną osobę obok umowy, do której wołający ma dostęp.
        candidate_id = parent.candidate_id
    elif candidate_id is not None:
        # Dane firmy kandydata (NIP, REGON, adres) tylko przez rekrutację,
        # do której wołający ma dostęp — inaczej `candidate_id` byłby
        # wyliczanką danych każdej osoby w bazie.
        if job_id is None:
            raise HTTPException(
                status_code=422,
                detail="Wybierz rekrutację, w której uczestniczy kandydat.",
            )
        job = await _load_legal_scoped_job(db, current_user, job_id, write=True)
        await _validate_candidate_job_link(db, candidate_id=candidate_id, job_id=job.id)
    base = await _base_info(db, parent)
    payload = (parent.render_payload if parent else None) or {}
    for key in (
        "gender",
        "partner_name",
        "partner_instrumental",
        "partner_legal_name",
        "partner_business_address",
        "partner_nip",
        "partner_regon",
    ):
        if payload.get(key):
            values[key] = payload[key]
    # Runda 10 (R10-N14-8): `render_payload` to zapis PODPISANEJ umowy — po
    # aneksie „dane firmy” niesie starą firmę. Bieżące dane Partnera mają
    # kolumny wiersza (aktualizuje je podpisany aneks) i — po takim aneksie —
    # profil kandydata (aneks zapisuje tam też REGON i adres). Wygrywają
    # z payloadem, gdy są niepuste.
    annex_done = parent is not None and bool(
        getattr(parent, "business_data_annex_done_at", None)
    )
    if parent is not None:
        values.setdefault("partner_name", parent.partner_name)
        if parent.partner_legal_name:
            values["partner_legal_name"] = parent.partner_legal_name
        if parent.partner_nip:
            values["partner_nip"] = parent.partner_nip
    if candidate_id is not None:
        candidate = await db.get(Candidate, candidate_id)
        if candidate is not None:
            full = f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            values.setdefault("partner_name", full or None)
            company = {
                "partner_legal_name": candidate.legal_name,
                "partner_business_address": candidate.business_address,
                "partner_nip": candidate.nip,
                "partner_regon": candidate.regon,
            }
            for key, value in company.items():
                if annex_done and value:
                    values[key] = value
                else:
                    values.setdefault(key, value)
    values.setdefault("gender", "m")
    values = {k: v for k, v in values.items() if v not in (None, "")}

    field_keys = {f.key for f in doc_type.fields}
    if "effective_date" in field_keys:
        values["effective_date"] = today.isoformat()
    if "currency" in field_keys:
        values["currency"] = base.currency or "PLN"
    if "termination_date" in field_keys:
        refs = refs_for(base.template_version)
        if doc_type.key != "termination_notice":
            values["termination_date"] = today.isoformat()
        elif refs is not None:
            values["termination_date"] = notice_end_date(today, refs).isoformat()
        # Umowa bez znanej wersji wzoru: okresu wypowiedzenia nie zgadujemy
        # z umowy 2026 — pole zostaje puste do wpisania (runda 6 audytu, DOC-3).
    if "last_service_date" in field_keys and values.get("termination_date"):
        values["last_service_date"] = values["termination_date"]
    if "delivery_date" in field_keys:
        values["delivery_date"] = today.isoformat()
    if "non_compete_client_name" in field_keys and base.client_legal_name:
        values["non_compete_client_name"] = base.client_legal_name
    if "new_start_date_mode" in field_keys:
        values["new_start_date_mode"] = base.start_date_mode or "exact"
    if "valid_until" in field_keys:
        values["valid_until"] = (today + timedelta(days=60)).isoformat()
    if "entity_type" in field_keys:
        values["entity_type"] = "sole_trader"
    if "base_signing_date" in field_keys and base.signing_date:
        values["base_signing_date"] = base.signing_date.isoformat()
    paragraph_defaults: dict[str, list[str]] = {}
    if doc_type.allows_external:
        paragraph_defaults = _annex_paragraph_defaults(doc_type, base)
        values = await _annex_prefill(db, doc_type, parent, base, payload, values)
    # Pola wrażliwe nigdy nie wracają z serwera — nawet gdyby były w payloadzie.
    values = strip_sensitive(doc_type, values)
    return {
        "values": values,
        "base": _base_snapshot(base),
        "paragraph_defaults": paragraph_defaults,
        "needs_refs": _needs_refs(doc_type, base),
        "ref_defaults": default_refs().as_context(),
        "languages": list(doc_type.languages),
        "default_language": (
            (payload.get("language") or "pl")
            if (payload.get("language") or "pl") in doc_type.languages
            else doc_type.languages[0]
        ),
    }


#: Domyślne paragrafy z ticketu (umowy sprzed wzoru 2026, umowy spoza
#: NEXUSA): data startu § 12 ust. 2 (JDG) / § 13 ust. 2 (spółka — nowy § 12
#: „Osoby skierowane do realizacji Usług” przesuwa numerację), stawka § 6 ust. 1.
_TICKET_PARAGRAPHS: dict[str, dict[str, tuple[str, str]]] = {
    "annex_start_date": {"sole_trader": ("12", "2"), "company": ("13", "2")},
    "annex_rate_change": {"sole_trader": ("6", "1"), "company": ("6", "1")},
}

_REF_ATTR = {
    "annex_start_date": "start_paragraph",
    "annex_rate_change": "rate_paragraph",
}


def _split_ref(ref: str) -> tuple[str, str] | None:
    """„§ 13 ust. 2” → („13”, „2”)."""
    match = re.match(r"§\s*([0-9]+[a-zA-Z]?)\s+ust\.\s*([0-9]+)", ref or "")
    return (match.group(1), match.group(2)) if match else None


def _annex_paragraph_defaults(
    doc_type: DocumentType, base: BaseContractInfo
) -> dict[str, list[str]]:
    """Podpowiedź „§ X ust. Y” dla obu wariantów Partnera.

    Umowa wydana w NEXUSIE (znana wersja wzoru 2026) cytuje paragrafy TEGO
    wzoru: data startu § 13 ust. 2 (JDG) / § 14 ust. 2 (spółka). Umowa z Excela
    działu albo spoza NEXUSA — domyślne z ticketu (starszy wzór). Pole zostaje
    edytowalne, bo o numerze rozstrzyga podpisana umowa."""
    ticket = _TICKET_PARAGRAPHS.get(doc_type.key)
    if not ticket:
        return {}
    out = {variant: list(pair) for variant, pair in ticket.items()}
    attr = _REF_ATTR[doc_type.key]
    if refs_for(base.template_version) is not None:
        for variant, version in (
            ("sole_trader", CURRENT_VERSION),
            ("company", COMPANY_VERSION),
        ):
            pair = _split_ref(getattr(VERSIONS[version], attr))
            if pair:
                out[variant] = list(pair)
    return out


async def _annex_prefill(
    db: AsyncSession,
    doc_type: DocumentType,
    parent: B2BGeneratedContract | None,
    base: BaseContractInfo,
    payload: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    """Wartości startowe generatora aneksów: dane umowy, wariant Partnera,
    komparycja spółki, obecna data startu i stawki (ticket, pkt 1.3)."""
    out = dict(values)
    if base.contract_number:
        out["contract_number"] = base.contract_number
    if base.signing_date:
        out["contract_signing_date"] = base.signing_date.isoformat()
    company = bool(
        (parent is not None and parent.partner_entity_type == "company")
        or payload.get("contract_variant") == "company"
    )
    out["partner_variant"] = "company" if company else "sole_trader"
    for key in (
        "partner_regon",
        "partner_business_address",
        "partner_krs",
        "partner_seat_locative",
        "partner_registry_court",
        "partner_share_capital",
        "partner_representative_name",
        "partner_representative_function",
        "partner_representation",
    ):
        if payload.get(key) and not out.get(key):
            out[key] = payload[key]
    defaults = _annex_paragraph_defaults(doc_type, base)
    if defaults:
        paragraph, section = defaults[out["partner_variant"]]
        out["paragraph"], out["paragraph_section"] = paragraph, section
    if doc_type.key == "annex_start_date" and base.start_date:
        out["current_start_date"] = base.start_date.isoformat()
    if doc_type.key == "annex_rate_change":
        items: list[dict[str, Any]] = []
        if parent is not None:
            client_name = None
            if parent.client_id is not None:
                client = await db.get(Client, parent.client_id)
                if client is not None:
                    client_name = (
                        client.legal_name or client.name or ""
                    ).strip() or None
            for item in annex_register.rate_items_from_register(parent):
                entry = dict(item)
                if not entry.get("client_id") and parent.client_id is not None:
                    # Klient umowy z rejestru — pozycja startowa „dla klienta”.
                    entry["client_id"] = parent.client_id
                    entry["client_name"] = client_name
                items.append(entry)
        out["rate_items"] = items or [{"rate": None, "from": None, "to": None}]
    if doc_type.key == "annex_party_data":
        # Uzupełnienie danych firmy: nową firmą jest JDG — NIP i REGON, jeśli
        # są już w profilu kandydata, podpowiadamy do „Pobierz z CEIDG”.
        for src, dst in (
            ("partner_nip", "new_nip"),
            ("partner_regon", "new_regon"),
            ("partner_legal_name", "new_legal_name"),
            ("partner_business_address", "new_business_address"),
        ):
            if values.get(src) and not out.get(dst):
                out[dst] = values[src]
    return out


@router.post("/documents/preview")
async def preview_document(
    request: DocumentRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Podgląd HTML — niczego nie zapisuje."""
    doc_type = _type_or_422(request.document_type)
    language = _language(doc_type, request.language)
    _, base, _ = await _resolve_subject(db, current_user, doc_type, request)
    values = await _resolve_rate_clients(db, request.values)
    context = _context(doc_type, values, language, base, request.refs)
    try:
        html = await run_in_threadpool(
            render_html, template_key(doc_type.key, language), context
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500, detail="Brak szablonu tego dokumentu."
        ) from exc
    return {
        "html": html,
        "missing": missing_required(doc_type, values),
        "invalid": invalid_values(doc_type, values),
    }


@router.post("/documents")
async def create_document(
    request: DocumentRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Wygeneruj dokument: DOCX w odpowiedzi + wiersz w rejestrze dokumentów."""
    _require_contract_generation(current_user)
    doc_type = _type_or_422(request.document_type)
    language = _language(doc_type, request.language)
    parent, base, links = await _resolve_subject(db, current_user, doc_type, request)
    values = await _resolve_rate_clients(db, request.values)
    _validate_values(doc_type, values, base, request.refs)
    context = _context(doc_type, values, language, base, request.refs)
    # Render przed zapisem: błąd szablonu nie zostawia wiersza bez dokumentu.
    data = await _render_bytes(doc_type, language, context)
    doc_date = _date(values.get("document_date")) or business_today()
    if _is_external(doc_type, parent):
        # Umowy nie ma w NEXUSIE — nie ma przy czym zapisać aneksu (ticket,
        # pkt 7.2). Plik idzie do przeglądarki, baza zostaje nietknięta.
        response = _docx_response(data, _filename(doc_type, values, doc_date), None)
        response.headers["X-Document-Saved"] = "0"
        return response
    if parent is not None and doc_type.allows_external:
        # Wiersz rejestru zmienia się teraz — blokada, żeby dwa aneksy do tej
        # samej umowy nie zapisały sobie nawzajem stanu „sprzed”.
        parent = await _load_parent(db, parent.id, lock=True)
    doc = B2BContractDocument(
        document_type=doc_type.key,
        language=language,
        parent_generated_contract_id=parent.id if parent else None,
        document_date=doc_date,
        render_payload={
            "values": strip_sensitive(doc_type, values),
            "refs": request.refs,
            "base": _base_snapshot(base),
        },
        template_key=template_key(doc_type.key, language),
        created_by=current_user.id,
        **links,
    )
    db.add(doc)
    await db.flush()
    register_fields: list[str] = []
    if parent is not None and doc_type.allows_external:
        await annex_register.apply(db, doc, parent, values)
        register_fields = sorted(doc.render_payload.get("register_applied") or {})
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="generated",
            user_id=current_user.id,
            details={
                "document_type": doc_type.key,
                "parent_generated_contract_id": doc.parent_generated_contract_id,
                **({"register_fields": register_fields} if register_fields else {}),
            },
        )
    )
    await db.commit()
    return _docx_response(data, _filename(doc_type, values, doc_date), doc.id)


@router.get("/documents", response_model=list[DocumentItem])
async def list_documents(
    current_user: B2BGeneratorAccess,
    parent_generated_contract_id: Optional[int] = Query(None),
    document_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    q: Optional[str] = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(B2BContractDocument)
    query = await _scope_generator_query(
        query, B2BContractDocument.client_id, db, current_user
    )
    if parent_generated_contract_id is not None:
        query = query.where(
            B2BContractDocument.parent_generated_contract_id
            == parent_generated_contract_id
        )
    if document_type:
        _type_or_422(document_type)
        query = query.where(B2BContractDocument.document_type == document_type)
    if status_filter:
        if status_filter == "unsigned":
            query = query.where(
                B2BContractDocument.status == "issued",
                B2BContractDocument.signature_status == "unsigned",
            )
        elif status_filter in ("issued", "signed", "cancelled"):
            query = query.where(B2BContractDocument.status == status_filter)
        else:
            raise HTTPException(status_code=422, detail="Nieznany status dokumentu.")
    needle = (q or "").strip()
    if needle:
        like = f"%{needle.lower()}%"
        query = query.where(
            or_(
                func.lower(
                    B2BContractDocument.render_payload["values"]["partner_name"].astext
                ).like(like),
                func.lower(
                    B2BContractDocument.render_payload["base"]["contract_number"].astext
                ).like(like),
            )
        )
    rows = list(
        (
            await db.execute(
                query.order_by(
                    B2BContractDocument.created_at.desc(), B2BContractDocument.id.desc()
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return await _serialize(db, rows, current_user)


@router.get("/documents/{doc_id}/form")
async def document_form(
    doc_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Zapisany formularz dokumentu — „Popraw” (bez pól wrażliwych)."""
    doc, doc_type, _parent = await _load_document(db, current_user, doc_id)
    _assert_editable(doc, current_user)
    payload = doc.render_payload or {}
    return {
        "id": doc.id,
        "document_type": doc.document_type,
        "language": doc.language,
        "parent_generated_contract_id": doc.parent_generated_contract_id,
        "candidate_id": doc.candidate_id,
        "job_id": doc.job_id,
        "values": _legacy_form_values(doc_type, payload.get("values") or {}),
        "refs": payload.get("refs"),
        "base": payload.get("base") or {},
        "sensitive_fields": sorted(doc_type.sensitive_keys),
    }


def _legacy_form_values(
    doc_type: DocumentType, values: dict[str, Any]
) -> dict[str, Any]:
    """Formularz aneksu zapisanego przed generatorem aneksów (29.09.2026).

    Stary aneks stawki niesie jedną stawkę w ``new_rate`` — bez przełożenia na
    pozycję formularz podstawiłby bieżącą stawkę z rejestru i „Popraw”
    zmieniłby kwotę, której nikt nie ruszał."""
    out = dict(values)
    if (
        doc_type.key == "annex_rate_change"
        and not out.get("rate_items")
        and out.get("new_rate") not in (None, "")
    ):
        out["rate_items"] = [
            {"rate": out["new_rate"], "client_id": None, "from": None, "to": None}
        ]
    return out


@router.post("/documents/{doc_id}/docx")
async def redownload_document(
    doc_id: int,
    body: SensitiveValues,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz ponownie. Dla dokumentów z danymi wrażliwymi body niesie te dane
    (nie przechowujemy ich) — bez nich 422 z listą pól."""
    _require_contract_generation(current_user)
    doc, doc_type, parent = await _load_document(db, current_user, doc_id)
    if parent is not None:
        await _authorize_parent(db, current_user, parent)
    payload = doc.render_payload or {}
    values = {**(payload.get("values") or {})}
    supplied = {k: v for k, v in body.values.items() if k in doc_type.sensitive_keys}
    values.update(supplied)
    missing = [
        f.label
        for f in doc_type.fields
        if f.sensitive and f.required and not values.get(f.key)
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "sensitive_values_required",
                "message": (
                    "Tych danych nie przechowujemy — podaj je, żeby pobrać "
                    "dokument: " + ", ".join(missing) + "."
                ),
                "missing": missing,
            },
        )
    base = _base_from_snapshot(payload.get("base"))
    context = _context(doc_type, values, doc.language, base, payload.get("refs"))
    data = await _render_bytes(doc_type, doc.language, context)
    return _docx_response(data, _filename(doc_type, values, doc.document_date), doc.id)


@router.post("/documents/{doc_id}/rerender")
async def rerender_document(
    doc_id: int,
    request: DocumentRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Popraw niepodpisany dokument — ten sam wiersz, nowa treść."""
    _require_contract_generation(current_user)
    doc, doc_type, parent = await _load_document(db, current_user, doc_id, lock=True)
    _assert_editable(doc, current_user)
    if request.document_type != doc.document_type:
        raise HTTPException(
            status_code=422, detail="Zmiana typu dokumentu to nowy dokument."
        )
    if parent is not None:
        await _authorize_parent(db, current_user, parent)
    language = _language(doc_type, request.language)
    base = (
        await _base_info(db, parent)
        if parent
        else _base_from_snapshot((doc.render_payload or {}).get("base"))
    )
    base = _with_value_overrides(doc_type, base, request.values)
    stored_values = (doc.render_payload or {}).get("values") or {}
    request_values = dict(request.values)
    if stored_values.get("currency") and not request_values.get("currency"):
        # Aneks sprzed generatora aneksów w walucie innej niż PLN — formularz
        # nie ma już pola waluty, a poprawka nie może zmienić EUR w złotówki.
        request_values["currency"] = stored_values["currency"]
    values = await _resolve_rate_clients(db, request_values)
    _validate_values(doc_type, values, base, request.refs)
    context = _context(doc_type, values, language, base, request.refs)
    data = await _render_bytes(doc_type, language, context)
    doc.language = language
    doc.template_key = template_key(doc_type.key, language)
    doc.document_date = _date(values.get("document_date")) or doc.document_date
    previous = doc.render_payload or {}
    payload: dict[str, Any] = {
        "values": strip_sensitive(doc_type, values),
        "refs": request.refs,
        "base": _base_snapshot(base),
    }
    if "register_before" in previous:
        # Stan wiersza sprzed PIERWSZEGO wygenerowania — poprawka go nie zmienia.
        payload["register_before"] = previous["register_before"]
    doc.render_payload = payload
    if parent is not None and doc_type.allows_external:
        await annex_register.apply(db, doc, parent, values)
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="regenerated",
            user_id=current_user.id,
            details={"document_type": doc_type.key},
        )
    )
    await db.commit()
    return _docx_response(data, _filename(doc_type, values, doc.document_date), doc.id)


@router.get("/documents/{doc_id}/effects")
async def document_effects_preview(
    doc_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Co zmieni „Oznacz jako podpisany” — liczone przez serwer, bez zapisu."""
    doc, doc_type, parent = await _load_document(db, current_user, doc_id)
    plan = await effects.describe(db, doc, doc_type, parent, user=current_user)
    return {
        "effect_label": doc_type.effect_label,
        "changes": plan.changes,
        "warnings": plan.warnings,
        "blockers": plan.blockers,
    }


@router.post("/documents/{doc_id}/confirm-signed", response_model=DocumentItem)
async def confirm_document_signed(
    doc_id: int,
    current_user: B2BGeneratorAccess,
    body: Optional[SensitiveValues] = None,
    db: AsyncSession = Depends(get_db),
):
    """Oznacz jako podpisany obustronnie i zastosuj skutki (idempotentnie)."""
    # Aneks stawki potwierdza też posiadacz „Stawki i kwoty: zmiana” bez
    # uprawnienia „Umowy B2B: oznaczanie jako podpisane” (domyślnie Finanse,
    # decyzja Artura 27.09.2026). Wpuszczamy go wyłącznie do aneksu stawki
    # u klienta, u którego zmienia kwoty — typ i klienta znamy dopiero po
    # odczycie dokumentu; resztę bramek i blokad liczy `effects.describe`.
    amounts_only = not _has_signature_permission(current_user) and has_permission(
        current_user, ProductAction.amounts_edit
    )
    if amounts_only:
        assert_b2b_generator_action_access(current_user, ActionAccess.view)
    else:
        _require_signature_confirmation(current_user)
    locked_contract_id = await _lock_contract_first(db, doc_id=doc_id)
    doc, doc_type, parent = await _load_document(db, current_user, doc_id, lock=True)
    if amounts_only and not (
        doc_type.key == RATE_ANNEX_TYPE
        and can_manage_finance_amounts(
            current_user,
            client_id=doc.client_id,
            delivery_lead_finance_client_ids=(
                await resolve_delivery_lead_finance_client_ids(current_user, db)
            ),
        )
    ):
        _require_signature_confirmation(current_user)
    _assert_same_locked_contract(
        locked_contract_id, effects.current_contract_id(doc, parent)
    )
    await _assert_signature_client_access(db, current_user, doc.client_id)
    if doc.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Anulowanego dokumentu nie można oznaczyć jako podpisanego.",
        )
    if doc.signature_status == "signed_both" and doc.effect_applied_at is not None:
        return (await _serialize(db, [doc], current_user))[0]
    plan = await effects.describe(db, doc, doc_type, parent, user=current_user)
    effects.ensure_no_blockers(plan)
    payload = doc.render_payload or {}
    values = {**(payload.get("values") or {})}
    supplied = (body.values if body else {}) or {}
    values.update({k: v for k, v in supplied.items() if k in doc_type.sensitive_keys})
    # Dane wrażliwe nie są przechowywane — bez ich ponownego podania plik
    # z pustym PESEL-em/adresem nie trafia do dokumentów kontraktu jako
    # „podpisany” (skutki podpisu i tak się stosują).
    complete = all(
        values.get(f.key) for f in doc_type.fields if f.sensitive and f.required
    )
    data: bytes | None = None
    if complete:
        base = _base_from_snapshot(payload.get("base"))
        context = _context(doc_type, values, doc.language, base, payload.get("refs"))
        data = await _render_bytes(doc_type, doc.language, context)
    await effects.apply(db, doc, doc_type, parent, user=current_user, docx=data)
    doc.signature_status = "signed_both"
    doc.status = "signed"
    doc.signed_at = datetime.now(timezone.utc)
    doc.signed_by_user_id = current_user.id
    await db.commit()
    await db.refresh(doc)
    return (await _serialize(db, [doc], current_user))[0]


@router.post("/documents/{doc_id}/cancel", response_model=DocumentItem)
async def cancel_document(
    doc_id: int,
    body: CancelRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Dokument, który nie doszedł do skutku — zostaje w historii."""
    doc, _doc_type, parent = await _load_document(db, current_user, doc_id, lock=True)
    _assert_editable(doc, current_user)
    doc.status = "cancelled"
    doc.cancelled_reason = body.reason.strip()
    # Aneks, który nie doszedł do skutku, nie zostawia w rejestrze swoich danych.
    restored = await annex_register.revert(db, doc, parent)
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="cancelled",
            user_id=current_user.id,
            details={
                "document_type": doc.document_type,
                **({"register_restored": restored} if restored else {}),
            },
        )
    )
    await db.commit()
    await db.refresh(doc)
    return (await _serialize(db, [doc], current_user))[0]


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    doc, _doc_type, parent = await _load_document(db, current_user, doc_id, lock=True)
    _assert_editable(doc, current_user)
    restored = await annex_register.revert(db, doc, parent)
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="deleted",
            user_id=current_user.id,
            details={
                "document_type": doc.document_type,
                **({"register_restored": restored} if restored else {}),
            },
        )
    )
    await db.delete(doc)
    await db.commit()


@router.post("/documents/partner-notice")
async def register_partner_notice(
    body: PartnerNoticeRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Zarejestruj wypowiedzenie złożone przez Partnera (bez dokumentu)."""
    _require_signature_confirmation(current_user)
    locked_contract_id = await _lock_contract_first(
        db, parent_id=body.parent_generated_contract_id
    )
    matched_contract_id: int | None = None
    if locked_contract_id is None:
        # Runda 10 (R10-N14-3): umowa bez powiązania (wiersz z Excela) —
        # kontrakt osoby u klienta umowy, blokowany PRZED wierszem rejestru.
        owner = (
            await db.execute(
                select(
                    B2BGeneratedContract.candidate_id,
                    B2BGeneratedContract.client_id,
                ).where(B2BGeneratedContract.id == body.parent_generated_contract_id)
            )
        ).first()
        if owner is not None:
            live = await effects.live_contract_ids_for_unlinked_row(
                db,
                row_id=body.parent_generated_contract_id,
                candidate_id=owner.candidate_id,
                client_id=owner.client_id,
            )
            if len(live) > 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "partner_notice_contract_ambiguous",
                        "message": effects.PARTNER_NOTICE_AMBIGUOUS,
                    },
                )
            if live:
                matched_contract_id = live[0]
                await db.execute(
                    select(Contract.id)
                    .where(Contract.id == matched_contract_id)
                    .with_for_update()
                )
    parent = await _load_parent(db, body.parent_generated_contract_id, lock=True)
    _assert_same_locked_contract(locked_contract_id, parent.contract_id)
    await _assert_signature_client_access(db, current_user, parent.client_id)
    await _assert_generator_client_access(
        db, current_user, parent.client_id, write=True
    )
    if parent.contract_id is not None or matched_contract_id is not None:
        # Wypowiedzenie kończy współpracę w kontrakcie — to samo uprawnienie
        # co okno „Zakończ współpracę”; samo oznaczanie podpisu nie wystarcza.
        ensure_permission(current_user, ProductAction.contract_status)
    refs = refs_for(getattr(parent, "template_version", None))
    if body.termination_date is None and refs is None:
        # Umowa bez znanej wersji wzoru (wiersz z Excela działu) — okresu
        # wypowiedzenia nie znamy, a zgadywanie z umowy 2026 zapisywało
        # kontraktowi i rejestrowi datę, której nikt nie potwierdził (runda 6
        # audytu, DOC-3).
        raise HTTPException(
            status_code=422,
            detail=(
                "Ta umowa nie ma w NEXUSIE wersji wzoru, więc okresu "
                "wypowiedzenia nie da się policzyć — podaj datę rozwiązania "
                "umowy."
            ),
        )
    termination_date = body.termination_date or notice_end_date(body.delivered_on, refs)
    if termination_date < body.delivered_on:
        raise HTTPException(
            status_code=422,
            detail="Data rozwiązania nie może być wcześniejsza niż doręczenie.",
        )
    summary = await effects.register_partner_notice(
        db,
        parent,
        delivered_on=body.delivered_on,
        termination_date=termination_date,
        user=current_user,
        matched_contract_id=matched_contract_id,
    )
    await db.commit()
    return summary
