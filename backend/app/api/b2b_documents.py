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
    _load_legal_scoped_job,
    _require_contract_generation,
    _require_generated_contract_management,
    _require_generator_rate_content,
    _require_signature_confirmation,
    _scope_generator_query,
    _validate_candidate_job_link,
)
from app.api.contract_access import B2BGeneratorAccess
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
from app.services import ezdrowie
from app.services.b2b_documents import effects
from app.services.b2b_documents.context import (
    BaseContractInfo,
    build_document_context,
)
from app.services.b2b_documents.contract_versions import (
    ContractVersionRefs,
    default_refs,
    notice_end_date,
    refs_for,
)
from app.services.b2b_documents.registry import (
    REF_LABELS,
    TYPES,
    DocumentType,
    missing_required,
    strip_sensitive,
)
from app.services.b2b_documents.render import (
    render_docx,
    render_html,
    template_key,
)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


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
        stmt = stmt.with_for_update()
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
    elif doc_type.parent == "b2b":
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
    return parent, await _base_info(db, parent), links


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
                can_confirm_signed=can_sign and open_unsigned,
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
    if any(f.kind == "money" for f in doc_type.fields):
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
    if parent is not None:
        values.setdefault("partner_name", parent.partner_name)
        values.setdefault("partner_legal_name", parent.partner_legal_name)
        values.setdefault("partner_nip", parent.partner_nip)
    if candidate_id is not None:
        candidate = await db.get(Candidate, candidate_id)
        if candidate is not None:
            full = f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            values.setdefault("partner_name", full or None)
            values.setdefault("partner_legal_name", candidate.legal_name)
            values.setdefault("partner_business_address", candidate.business_address)
            values.setdefault("partner_nip", candidate.nip)
            values.setdefault("partner_regon", candidate.regon)
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
    # Pola wrażliwe nigdy nie wracają z serwera — nawet gdyby były w payloadzie.
    values = strip_sensitive(doc_type, values)
    return {
        "values": values,
        "base": _base_snapshot(base),
        "needs_refs": _needs_refs(doc_type, base),
        "ref_defaults": default_refs().as_context(),
        "languages": list(doc_type.languages),
        "default_language": (
            (payload.get("language") or "pl")
            if (payload.get("language") or "pl") in doc_type.languages
            else doc_type.languages[0]
        ),
    }


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
    context = _context(doc_type, request.values, language, base, request.refs)
    try:
        html = await run_in_threadpool(
            render_html, template_key(doc_type.key, language), context
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500, detail="Brak szablonu tego dokumentu."
        ) from exc
    return {"html": html, "missing": missing_required(doc_type, request.values)}


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
    _validate_values(doc_type, request.values, base, request.refs)
    context = _context(doc_type, request.values, language, base, request.refs)
    # Render przed zapisem: błąd szablonu nie zostawia wiersza bez dokumentu.
    data = await _render_bytes(doc_type, language, context)
    doc_date = _date(request.values.get("document_date")) or business_today()
    doc = B2BContractDocument(
        document_type=doc_type.key,
        language=language,
        parent_generated_contract_id=parent.id if parent else None,
        document_date=doc_date,
        render_payload={
            "values": strip_sensitive(doc_type, request.values),
            "refs": request.refs,
            "base": _base_snapshot(base),
        },
        template_key=template_key(doc_type.key, language),
        created_by=current_user.id,
        **links,
    )
    db.add(doc)
    await db.flush()
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="generated",
            user_id=current_user.id,
            details={
                "document_type": doc_type.key,
                "parent_generated_contract_id": doc.parent_generated_contract_id,
            },
        )
    )
    await db.commit()
    return _docx_response(data, _filename(doc_type, request.values, doc_date), doc.id)


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
        "values": payload.get("values") or {},
        "refs": payload.get("refs"),
        "base": payload.get("base") or {},
        "sensitive_fields": sorted(doc_type.sensitive_keys),
    }


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
    _validate_values(doc_type, request.values, base, request.refs)
    context = _context(doc_type, request.values, language, base, request.refs)
    data = await _render_bytes(doc_type, language, context)
    doc.language = language
    doc.template_key = template_key(doc_type.key, language)
    doc.document_date = _date(request.values.get("document_date")) or doc.document_date
    doc.render_payload = {
        "values": strip_sensitive(doc_type, request.values),
        "refs": request.refs,
        "base": _base_snapshot(base),
    }
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
    return _docx_response(
        data, _filename(doc_type, request.values, doc.document_date), doc.id
    )


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
    _require_signature_confirmation(current_user)
    locked_contract_id = await _lock_contract_first(db, doc_id=doc_id)
    doc, doc_type, parent = await _load_document(db, current_user, doc_id, lock=True)
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
    doc, _doc_type, _parent = await _load_document(db, current_user, doc_id, lock=True)
    _assert_editable(doc, current_user)
    doc.status = "cancelled"
    doc.cancelled_reason = body.reason.strip()
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="cancelled",
            user_id=current_user.id,
            details={"document_type": doc.document_type},
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
    doc, _doc_type, _parent = await _load_document(db, current_user, doc_id, lock=True)
    _assert_editable(doc, current_user)
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="deleted",
            user_id=current_user.id,
            details={"document_type": doc.document_type},
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
    parent = await _load_parent(db, body.parent_generated_contract_id, lock=True)
    _assert_same_locked_contract(locked_contract_id, parent.contract_id)
    await _assert_signature_client_access(db, current_user, parent.client_id)
    await _assert_generator_client_access(
        db, current_user, parent.client_id, write=True
    )
    if parent.contract_id is not None and not effects._can_change_contracts(
        current_user
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Wypowiedzenie w kontrakcie rejestruje admin albo Delivery Lead "
                "z prawem zapisu w sekcji Delivery."
            ),
        )
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
    )
    await db.commit()
    return summary
