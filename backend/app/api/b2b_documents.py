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

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.b2b_contract_generator import (
    _DOCX_MEDIA,
    _SIGNS_EVERY_CONTRACT_ROLES,
    _ascii_filename,
    _assert_generator_client_access,
    _assert_link_same_person,
    _assert_signature_client_access,
    _generated_search_clause,
    _generator_unscoped,
    _has_signature_permission,
    _jobs_run_by,
    _like_needle,
    _load_legal_scoped_job,
    _may_confirm_row_signature,
    _rate_visibility,
    _require_contract_generation,
    _require_generated_contract_management,
    _require_generator_rate_content,
    _require_signature_confirmation,
    _scope_generator_query,
    _validate_candidate_job_link,
    apply_contract_link,
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
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.user import User, UserRole
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.action_permissions import (
    ActionAccess,
    ProductAction,
    has_permission,
)
from app.services import ezdrowie
from app.services.b2b_documents import (
    annex_register,
    contract_annexes,
    effects,
    signed_scan,
)
from app.services.b2b_documents.annex_summary import annex_change
from app.services.b2b_documents.mandate_forms import FORMS_BY_KEY, MANDATE_FORMS
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
from app.services.polish_ilike import polish_folded_ilike
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
    stored_or_current_key,
    template_key,
)
from app.services.cv_pdf_preview import PdfPreviewUnavailable, pdf_from_docx

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

RATE_ANNEX_TYPE = "annex_rate_change"

#: Kara umowna z wzoru umowy o udziale w procesie rekrutacyjnym (10 000 zł) —
#: podpowiedź formularza, człowiek może ją zmienić.
PARTICIPATION_PENALTY_DEFAULT = 10000


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
    #: Kontrakt aneksu bez umowy w rejestrze (umowa spoza NEXUSA, zlecenie)
    #: albo kontrakt wskazany dla umowy z rejestru, która nie ma powiązania.
    #: Osobę, rekrutację i klienta dokumentu serwer bierze z kontraktu.
    contract_id: Optional[int] = None
    #: Klient aneksu bez umowy i bez kontraktu („Bez kontraktu”).
    client_id: Optional[int] = None


class SubjectContract(BaseModel):
    """Kontrakt widoczny przy wyborze, dla kogo jest aneks — bez stawek."""

    contract_id: int
    status: str
    start_date: Optional[date] = None


class DocumentSubject(BaseModel):
    """Pozycja wyszukiwania „Dla kogo jest aneks?”.

    ``agreement`` = umowa z rejestru (z powiązanym kontraktem albo z listą
    kontraktów do wskazania, gdy powiązania nie ma); ``contract`` = kontrakt
    bez umowy w rejestrze (umowa spoza NEXUSA, zlecenie). Bez kwot: wybór
    podmiotu nie jest wglądem w stawki."""

    kind: str
    parent_generated_contract_id: Optional[int] = None
    contract_number: Optional[str] = None
    source: Optional[str] = None
    agreement_status: Optional[str] = None
    contract_id: Optional[int] = None
    contract_status: Optional[str] = None
    contract_start_date: Optional[date] = None
    contract_options: list[SubjectContract] = Field(default_factory=list)
    candidate_id: Optional[int] = None
    person_name: Optional[str] = None
    partner_name: Optional[str] = None
    partner_nip: Optional[str] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None


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
    # Rejestr aneksów (13.10.2026): dla kogo, jaki aneks, od kiedy, w jakim stanie.
    client_id: Optional[int] = None
    person_name: Optional[str] = None
    partner_legal_name: Optional[str] = None
    partner_nip: Optional[str] = None
    #: Aneks bez umowy w rejestrze (umowa spoza NEXUSA, zlecenie).
    external: bool = False
    effective_date: Optional[date] = None
    #: ``effects.ANNEX_STATES`` — jeden stan zamiast pary status + podpis.
    state: str = "waiting"
    #: Skrót zmiany (``annex_summary.annex_change``); kwoty pod bramką stawek.
    change: Optional[dict] = None
    can_restore: bool = False
    can_link_contract: bool = False
    #: Skan podpisanego aneksu w Dokumentach kontraktu (``signed_scan.attach``).
    signed_scan_document_id: Optional[int] = None


class LinkContractRequest(BaseModel):
    contract_id: int


class DocumentHistoryEntry(BaseModel):
    action: str
    at: Optional[str] = None
    by_name: Optional[str] = None
    note: Optional[str] = None


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


async def _authorize_document_write(
    db: AsyncSession,
    user: User,
    doc: B2BContractDocument,
    parent: B2BGeneratedContract | None,
) -> None:
    """Zapis u klienta dokumentu — także gdy dokument nie ma umowy bazowej.

    Do 13.10.2026 dokument bez umowy bazowej nie miał klienta (aneks do umowy
    spoza NEXUSA nie był zapisywany), więc ponowne pobranie i poprawka pytały
    o zapis wyłącznie przez umowę."""
    if parent is not None:
        await _authorize_parent(db, user, parent)
    else:
        await _assert_generator_client_access(db, user, doc.client_id, write=True)


def _binds_contracts(user: User) -> bool:
    """Kto wiąże aneks z kontraktem: wybiera kontrakt bez umowy w rejestrze,
    dowiązuje do niego wiersz rejestru albo aneks „Bez kontraktu”.

    Generator stoi za sekcją Sourcing i jest otwarty dla każdej roli
    operacyjnej, a kontrakt to dane Delivery. Bez tej bramki rekruter widział
    w wyszukiwarce cudze kontrakty i wiązał z nimi aneksy samym ``contract_id``
    (przegląd bezpieczeństwa 13.10.2026). Para jak przy trasie ``/amendments``
    modułu Kontrakty i przy skutku podpisu
    (``effects.contract_effect_permission`` + ``can_write_delivery``)."""
    return has_permission(
        user, ProductAction.contracts_orders_edit
    ) and effects.can_write_delivery(user)


def _require_contract_binding(user: User) -> None:
    ensure_permission(user, ProductAction.contracts_orders_edit)
    if not effects.can_write_delivery(user):
        raise HTTPException(status_code=403, detail=effects.DELIVERY_WRITE_BLOCKER)


def _in_delivery_scope(client_id: int | None, allowed: frozenset[int] | None) -> bool:
    """``allowed`` z ``resolve_delivery_lead_client_ids``: ``None`` = konto bez
    granicy portfela Delivery Leada."""
    return allowed is None or (client_id is not None and client_id in allowed)


def _client_label(client: Client | None) -> str | None:
    if client is None:
        return None
    return (getattr(client, "legal_name", None) or client.name or "").strip() or None


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


def _current_key(doc_type: DocumentType, language: str) -> str:
    """Klucz szablonu NOWEGO dokumentu — bieżąca rewizja wzoru."""
    return template_key(doc_type.key, language, doc_type.template_revision)


async def _render_bytes(
    doc_type: DocumentType,
    language: str,
    context: dict[str, Any],
    *,
    stored_key: str | None = None,
) -> bytes:
    """DOCX dokumentu. ``stored_key`` = klucz z wiersza wydanego dokumentu:
    ponowne pobranie i plik do kontraktu idą wzorem, z którego dokument
    wydano, a nie bieżącą rewizją (21.10.2026)."""
    key = stored_or_current_key(stored_key, _current_key(doc_type, language))
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

    if doc_type.family == "preliminary":
        if request.candidate_id is None or request.job_id is None:
            raise HTTPException(
                status_code=422,
                detail="Wybierz kandydata i rekrutację, której dotyczy umowa.",
            )
        job = await _load_legal_scoped_job(db, user, request.job_id, write=True)
        _, job = await _validate_candidate_job_link(
            db, candidate_id=request.candidate_id, job_id=job.id
        )
        if doc_type not in _preliminary_types_for(job.client_id):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Umowa przedwstępna Centrum e-Zdrowia dotyczy wyłącznie jego "
                    "rekrutacji."
                    if doc_type.preliminary_scope == "cez"
                    else "W rekrutacji Centrum e-Zdrowia wystaw umowę przedwstępną "
                    "Centrum e-Zdrowia."
                ),
            )
        links.update(client_id=job.client_id)
    elif (
        parent is None and request.contract_id is not None and _takes_contract(doc_type)
    ):
        contract = await _load_subject_contract(db, user, doc_type, request.contract_id)
        links.update(
            contract_id=contract.id,
            candidate_id=contract.candidate_id,
            job_id=contract.job_id,
            client_id=contract.client_id,
        )
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
    if (
        parent is None
        and links["client_id"] is None
        and request.client_id is not None
        and _takes_contract(doc_type)
    ):
        # Aneks „Bez kontraktu”: klient z NEXUSA, żeby dokument miał zakres —
        # bez klienta widziałby go tylko admin i Head of Recruitment.
        client = await assert_client_assignable(db, request.client_id)
        if client is None:
            raise HTTPException(status_code=422, detail="Klienta nie ma w NEXUSIE.")
        await _assert_generator_client_access(db, user, client.id, write=True)
        links.update(client_id=client.id)
    base = _with_value_overrides(doc_type, await _base_info(db, parent), request.values)
    return parent, base, links


def _preliminary_types_for(client_id: int | None) -> list[DocumentType]:
    """Umowy przedwstępne dozwolone u klienta (decyzja Artura, 21.10.2026):
    Centrum e-Zdrowia ma własny wzór, każdy inny klient — umowę o udziale
    w procesie rekrutacyjnym (kandydat z działalnością albo osoba fizyczna).
    Stała czytana przy wywołaniu — testy podmieniają ``EZDROWIE_CLIENT_ID``."""
    scope = (
        "cez"
        if client_id is not None and client_id == ezdrowie.EZDROWIE_CLIENT_ID
        else "general"
    )
    return [t for t in TYPES.values() if t.preliminary_scope == scope]


def _takes_contract(doc_type: DocumentType) -> bool:
    return effects.annex_takes_contract(doc_type)


def _subject_contract_type(doc_type: DocumentType) -> ContractType:
    return ContractType.uzlecenie if doc_type.parent == "mandate" else ContractType.b2b


async def _load_subject_contract(
    db: AsyncSession, user: User, doc_type: DocumentType, contract_id: int
) -> Contract:
    """Kontrakt wskazany jako podmiot aneksu bez umowy w rejestrze.

    Do 13.10.2026 aneks do umowy spoza NEXUSA nie był zapisywany wcale, więc
    nie było go w żadnej liście i podpis nie zmieniał kontraktu. Żądanie niesie
    samo id — osobę, rekrutację i klienta dokumentu bierze serwer z kontraktu,
    żeby nie dało się podpiąć aneksu pod dowolną osobę albo klienta spoza
    zakresu wołającego. Prawo edycji kontraktów sprawdzamy PRZED odczytem —
    odmowa nie zdradza, czy kontrakt o tym id istnieje."""
    _require_contract_binding(user)
    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(selectinload(Contract.b2b_detail))
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Kontrakt nie istnieje.")
    # Portfel Delivery Leada jak w module Kontrakty (`_assert_contract`),
    # potem zapis u klienta w domenie generatora.
    assert_delivery_lead_client_visible(
        contract.client_id, await resolve_delivery_lead_client_ids(user, db)
    )
    await _assert_generator_client_access(db, user, contract.client_id, write=True)
    if contract.status == ContractStatus.void:
        raise HTTPException(
            status_code=422,
            detail="Ten kontrakt jest unieważniony — wybierz inny.",
        )
    if contract.contract_type != _subject_contract_type(doc_type):
        raise HTTPException(
            status_code=422,
            detail=(
                "Aneks do umowy zlecenie wymaga kontraktu zlecenie."
                if doc_type.parent == "mandate"
                else "Ten aneks dotyczy umowy B2B — wybierz kontrakt B2B."
            ),
        )
    return contract


async def _reject_contract_with_own_agreement(
    db: AsyncSession, contract_id: int
) -> None:
    """Kontrakt z żywą umową w rejestrze dostaje aneks przez tę umowę.

    Wyszukiwarka osoby (``document_subjects``) takiego kontraktu nie pokazuje,
    ale trasy przyjmowały go samym ``contract_id`` — aneks omijał wtedy wiersz
    rejestru i kolejkę „Aneks uzupełnienia danych” (audyt 13.10.2026)."""
    number = await db.scalar(
        select(B2BGeneratedContract.contract_number)
        .where(
            B2BGeneratedContract.contract_id == contract_id,
            B2BGeneratedContract.contract_status.in_(_LIVE_AGREEMENT_STATUSES),
        )
        .limit(1)
    )
    if number is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Ten kontrakt ma umowę w rejestrze ({number}) — przygotuj aneks "
                "do tej umowy, wtedy zmieni się też wiersz rejestru."
            ),
        )


_ANNEX_LINK_OTHER_PERSON = (
    "Kontrakt dotyczy innej osoby niż aneks. Jeśli to ta sama osoba zapisana "
    "w dwóch rekordach, najpierw scal duplikaty kandydata (profil → „Scal z…”)."
)
_ANNEX_LINK_OTHER_CLIENT = (
    "Kontrakt jest u innego klienta niż aneks — wybierz kontrakt u klienta "
    "aneksu albo przygotuj nowy aneks."
)


async def _assert_annex_link_same_subject(
    db: AsyncSession, doc: B2BContractDocument, contract: Contract
) -> None:
    """Powiązanie nie przenosi aneksu na inną osobę ani do innego klienta.

    Do 14.10.2026 „Powiąż z kontraktem” przy aneksie bez umowy w rejestrze
    sprawdzało tylko dostęp wołającego, a potem nadpisywało osobę i klienta
    dokumentu kontraktem — podpis zapisywał firmę, NIP i stawkę z aneksu
    osoby A w kontrakcie osoby B (audyt 13.10.2026, pkt 7). Osobę porównujemy
    jak „Powiąż z kontraktem” w rejestrze umów (zdublowany rekord tej samej
    osoby przechodzi), klienta — jak aneks do umowy z rejestru. Aneks „Bez
    kontraktu” nie zna osoby; zna klienta, przy którym go zapisano. Scalenie
    klientów nie przenosi dokumentów generatora, więc duplikat wiąże się
    z kontraktem klienta kanonicznego."""
    if doc.client_id is not None and doc.client_id != contract.client_id:
        client = await db.get(Client, doc.client_id)
        if getattr(client, "merged_into_client_id", None) != contract.client_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=_ANNEX_LINK_OTHER_CLIENT
            )
    try:
        # Porównuje wyłącznie ``candidate_id`` — dokument ma tę samą kolumnę
        # co wiersz rejestru.
        await _assert_link_same_person(db, doc, contract)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_ANNEX_LINK_OTHER_PERSON
        ) from exc


async def _lock_parent_linking_contract(
    db: AsyncSession,
    parent: B2BGeneratedContract,
    picked_contract_id: int | None,
    *,
    may_link: bool,
    user_id: int | None,
) -> tuple[B2BGeneratedContract, int | None]:
    """Zablokuj wiersz umowy bazowej; umowę bez kontraktu dowiąż do kontraktu
    tej osoby u tego klienta. Zwraca wiersz i id właśnie dowiązanego kontraktu.

    Wiersz z Excela działu (i każdy sprzed automatyzacji podpisu) nie ma
    ``contract_id``, więc podpis aneksu zmieniał tylko rejestr umów. Reguła
    dopasowania jest ta sama, co przy zakończeniu współpracy
    (``contract_termination_sync``) i wypowiedzeniu Partnera: trwający kontrakt
    B2B tej osoby u tego klienta bez własnej umowy w rejestrze. Jeden taki
    kontrakt dowiązujemy sami, przy kilku — tylko wskazany w żądaniu.
    Kolejność blokad: kontrakt, potem wiersz (runda 6 audytu, LOCK-1).

    ``may_link`` = wołający prowadzi kontrakty tego klienta
    (``_binds_contracts`` + portfel). Bez tego aneks powstaje, a wiersz zostaje
    bez kontraktu — dowiązanie jest zapisem w Delivery, nie skutkiem ubocznym
    wygenerowania dokumentu przez dowolnego użytkownika generatora.

    Dowiązanie idzie rdzeniem „Powiąż z kontraktem” z rejestru umów
    (``apply_contract_link``): kontrakt dostaje numer umowy, a oś czasu umowy
    i kontraktu — wpis. Do 14.10.2026 ustawialiśmy samo ``contract_id``
    (audyt 13.10.2026)."""
    target: int | None = None
    if parent.contract_id is None and not may_link:
        if picked_contract_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Powiązanie umowy z kontraktem wymaga prawa edycji "
                    "kontraktów tego klienta."
                ),
            )
    elif parent.contract_id is None:
        live = await effects.live_contract_ids_for_unlinked_row(
            db,
            row_id=parent.id,
            candidate_id=parent.candidate_id,
            client_id=parent.client_id,
            contract_type=ContractType.b2b,
        )
        if picked_contract_id is not None:
            if picked_contract_id not in live:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Ten kontrakt nie należy do osoby i klienta tej umowy "
                        "albo ma już własną umowę w rejestrze."
                    ),
                )
            target = picked_contract_id
        elif len(live) == 1:
            target = live[0]
        if target is not None:
            await db.execute(
                select(Contract.id).where(Contract.id == target).with_for_update()
            )
    elif picked_contract_id is not None and picked_contract_id != parent.contract_id:
        raise HTTPException(
            status_code=422, detail="Umowa jest już powiązana z innym kontraktem."
        )
    locked = await _load_parent(db, parent.id, lock=True)
    if target is not None and locked.contract_id is None:
        contract = await db.get(Contract, target)
        await apply_contract_link(db, locked, contract, user_id=user_id)
        return locked, target
    return locked, None


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


_DOCUMENT_SIGNATURE_SCOPE_DENIED = (
    "Podpis tego dokumentu oznacza osoba, która wygenerowała dokument albo "
    "umowę, zespół rekrutacji umowy, Delivery Lead klienta albo TCM."
)


def _signature_job_id(
    doc: B2BContractDocument | None, parent: B2BGeneratedContract | None
) -> int | None:
    if parent is not None:
        return parent.job_id
    return doc.job_id if doc is not None else None


def _may_confirm_document_signature(
    user: User,
    *,
    doc: B2BContractDocument | None,
    parent: B2BGeneratedContract | None,
    team_job_ids: set[int],
) -> bool:
    """Reguła podpisu umowy (``_may_confirm_row_signature``) dla dokumentu do
    niej i wypowiedzenia Partnera (decyzja Artura 19.10.2026).

    Do 19.10 samo uprawnienie „Umowy B2B: oznaczanie jako podpisane” otwierało
    dokumenty w całej firmie, więc nie dało się go nadać roli Rekruter. Autor
    dokumentu liczy się tak samo jak autor umowy. Nikt tu nie wskazuje
    rekrutacji, więc umowa bez rekrutacji zostaje autorowi i rolom
    z ``_SIGNS_EVERY_CONTRACT_ROLES``."""
    if doc is not None and doc.created_by is not None and doc.created_by == user.id:
        return True
    return _may_confirm_row_signature(
        user,
        created_by=parent.created_by if parent is not None else None,
        job_id=_signature_job_id(doc, parent),
        team_job_ids=team_job_ids,
        open_without_job=False,
    )


async def _signature_team_job_ids(
    db: AsyncSession, user: User, job_ids: set[int]
) -> set[int]:
    if user.has_any_role(*_SIGNS_EVERY_CONTRACT_ROLES):
        return set()
    return await _jobs_run_by(db, user, job_ids)


async def _require_document_signature_scope(
    db: AsyncSession,
    user: User,
    *,
    doc: B2BContractDocument | None,
    parent: B2BGeneratedContract | None,
) -> None:
    job_id = _signature_job_id(doc, parent)
    team_job_ids = await _signature_team_job_ids(
        db, user, {job_id} if job_id is not None else set()
    )
    if not _may_confirm_document_signature(
        user, doc=doc, parent=parent, team_job_ids=team_job_ids
    ):
        raise HTTPException(status_code=403, detail=_DOCUMENT_SIGNATURE_SCOPE_DENIED)


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
    signature_team_job_ids = (
        await _signature_team_job_ids(
            db,
            user,
            {
                job_id
                for r in rows
                if (
                    job_id := _signature_job_id(
                        r, parents.get(r.parent_generated_contract_id or -1)
                    )
                )
                is not None
            },
        )
        if can_sign
        else set()
    )
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
    binds = _binds_contracts(user)
    delivery_boundary = await resolve_delivery_lead_client_ids(user, db)
    # Pola rejestru aneksów — jedno zapytanie na rodzaj danych, nie na wiersz.
    people: dict[int, str | None] = {}
    candidate_ids = {r.candidate_id for r in rows if r.candidate_id}
    if candidate_ids:
        found = await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname).where(
                Candidate.id.in_(candidate_ids)
            )
        )
        people = {cid: _full_name(name, last) for cid, name, last in found.all()}
    clients: dict[int, Client] = {}
    client_ids = {r.client_id for r in rows if r.client_id}
    if client_ids:
        found_clients = await db.scalars(
            select(Client).where(Client.id.in_(client_ids))
        )
        clients = {c.id: c for c in found_clients.all()}
    contract_of = {
        r.id: effects.current_contract_id(
            r, parents.get(r.parent_generated_contract_id or -1)
        )
        for r in rows
    }
    void_contracts: set[int] = set()
    linked_ids = {cid for cid in contract_of.values() if cid is not None}
    if linked_ids:
        found_void = await db.scalars(
            select(Contract.id).where(
                Contract.id.in_(linked_ids), Contract.status == ContractStatus.void
            )
        )
        void_contracts = set(found_void.all())
    live_scans = await signed_scan.existing_scan_ids(db, rows)
    rate_visibility = await _rate_visibility(
        db,
        user,
        {
            job_id
            for r in rows
            for job_id in (
                r.job_id,
                getattr(
                    parents.get(r.parent_generated_contract_id or -1), "job_id", None
                ),
            )
            if job_id is not None
        },
    )
    today = business_today()
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
        contract_id = contract_of[row.id]
        orphan = effects.is_unlinked_external_annex(doc_type, parent, contract_id)
        is_annex = doc_type.family == "annex"
        # Podpisany aneks: dzień zapisany przy podpisie; wcześniej — ta sama
        # reguła, którą podpis zastosuje.
        effective = (
            contract_annexes.effective_date_of(
                row,
                contract_client_id=row.client_id if contract_id is not None else None,
            )
            if is_annex
            else None
        )
        rates_visible = rate_visibility.visible(
            client_id=row.client_id,
            created_by=parent.created_by if parent else row.created_by,
            job_id=parent.job_id if parent else row.job_id,
        )
        can_link = (
            is_annex
            and can_manage
            and binds
            and _in_delivery_scope(row.client_id, delivery_boundary)
            and open_unsigned
            and (contract_id is None or contract_id in void_contracts)
            and (
                (parent is None and _takes_contract(doc_type))
                or (
                    parent is not None
                    and doc_type.parent == "b2b"
                    and contract_id is None
                )
            )
        )
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
                # Kontrakt, na który podpis faktycznie zadziała — bieżący
                # kontrakt umowy bazowej, nie migawka z chwili generowania.
                contract_id=contract_id,
                candidate_id=row.candidate_id,
                partner_name=values.get("partner_name"),
                client_name=(payload.get("base") or {}).get("client_name")
                or (parent.client_name if parent else None)
                or _client_label(clients.get(row.client_id or -1)),
                client_id=row.client_id,
                person_name=people.get(row.candidate_id or -1)
                or values.get("partner_name"),
                partner_legal_name=values.get("partner_legal_name")
                or values.get("new_legal_name"),
                partner_nip=values.get("partner_nip") or values.get("new_nip"),
                external=parent is None and _takes_contract(doc_type),
                effective_date=effective,
                state=effects.annex_state(
                    status=row.status,
                    signature_status=row.signature_status,
                    effective=effective,
                    today=today,
                ),
                change=(
                    annex_change(
                        row.document_type,
                        values,
                        rates_visible=rates_visible,
                        rates_before=(
                            annex_register.rates_before(row, parent)
                            if rates_visible and row.document_type == RATE_ANNEX_TYPE
                            else None
                        ),
                    )
                    if is_annex
                    else None
                ),
                can_restore=can_manage and own and row.status == "cancelled",
                can_link_contract=can_link,
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
                # Aneks „Bez kontraktu” czeka na powiązanie — przycisk prowadziłby
                # prosto do odmowy.
                can_confirm_signed=open_unsigned
                and not orphan
                and (
                    (
                        can_sign
                        and _may_confirm_document_signature(
                            user,
                            doc=row,
                            parent=parent,
                            team_job_ids=signature_team_job_ids,
                        )
                    )
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
                # Skan usunięty z Dokumentów kontraktu (albo z kontraktem) to
                # brak skanu, nie „Podmień skan”.
                signed_scan_document_id=(
                    scan_id
                    if (scan_id := signed_scan.signed_scan_id(row)) in live_scans
                    else None
                ),
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
        "mandate_forms": [f.to_public() for f in MANDATE_FORMS],
    }


@router.get("/mandate-forms/{form_key}")
async def download_mandate_form(form_key: str, current_user: B2BGeneratorAccess):
    """Pusty wzór oświadczenia albo deklaracji do umowy zlecenie."""
    form = FORMS_BY_KEY.get(form_key)
    if form is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego wzoru.")
    return FileResponse(
        form.path, filename=form.download_name, media_type=form.media_type
    )


#: Ile pozycji każdego rodzaju oddaje wyszukiwanie podmiotu aneksu.
SUBJECT_LIMIT = 20
#: Umowy, do których wystawia się aneks (jak dotychczasowy wybór z rejestru).
_SUBJECT_AGREEMENT_STATUSES = ("active", "in_progress")
#: Umowa „żywa” — kontrakt z taką umową nie jest „umową spoza NEXUSA”.
_LIVE_AGREEMENT_STATUSES = ("active", "suspended", "in_progress")


def _full_name(name: str | None, lastname: str | None) -> str | None:
    return f"{name or ''} {lastname or ''}".strip() or None


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value))


@router.get("/documents/subjects", response_model=list[DocumentSubject])
async def document_subjects(
    current_user: B2BGeneratorAccess,
    document_type: str = Query(...),
    q: Optional[str] = Query(None, max_length=120),
    contract_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentSubject]:
    """Dla kogo jest aneks: umowy z rejestru i kontrakty bez umowy w rejestrze.

    Jedno wyszukiwanie zamiast przycisku „Umowa spoza Nexusa”: człowiek nie
    musi wiedzieć z góry, czy umowa jest w rejestrze, i nie wybierze „spoza
    NEXUSA” dla umowy, która w nim jest. Kontrakt osiągalny z umowy bez
    powiązania (ta sama osoba i klient) pokazuje się POD tą umową — wybrany
    osobno ominąłby wiersz rejestru i kolejkę „Aneks uzupełnienia danych”.

    ``contract_id`` = wejście z modułu Kontrakty („Wygeneruj dokument
    aneksu”): podmiot tego jednego kontraktu.

    Umowy z rejestru widzi każdy, kto generuje dokumenty (jak ``GET
    /generated``). Kontrakt to dane Delivery: wiersze ``kind="contract"``
    i kontrakty pod umową bez powiązania dostaje tylko osoba, która może je
    powiązać (``_binds_contracts``), a wejście przez ``contract_id`` — tylko
    z podglądem Delivery; w obu przypadkach Delivery Lead w granicy portfela.
    Odmowa to pusta lista, nie 403 — odpowiedź nie zdradza, czy kontrakt
    istnieje."""
    _require_contract_generation(current_user)
    doc_type = _type_or_422(document_type)
    needle = (q or "").strip()
    binds = _binds_contracts(current_user)
    delivery_boundary = await resolve_delivery_lead_client_ids(current_user, db)
    anchor: Contract | None = None
    if contract_id is not None:
        if not has_permission(current_user, ProductAction.delivery_view):
            return []
        anchor = await db.get(Contract, contract_id)
        if anchor is None or not _in_delivery_scope(
            anchor.client_id, delivery_boundary
        ):
            return []
        await _assert_generator_client_access(db, current_user, anchor.client_id)
    elif len(needle) < 2:
        return []

    subjects: list[DocumentSubject] = []
    offered_contract_ids: set[int] = set()

    if doc_type.parent in ("b2b", "mandate"):
        rows_query = await _scope_generator_query(
            select(B2BGeneratedContract, Candidate.name, Candidate.lastname),
            B2BGeneratedContract.client_id,
            db,
            current_user,
        )
        rows_query = rows_query.outerjoin(
            Candidate, Candidate.id == B2BGeneratedContract.candidate_id
        ).where(B2BGeneratedContract.contract_status.in_(_SUBJECT_AGREEMENT_STATUSES))
        if doc_type.parent == "mandate":
            rows_query = rows_query.where(
                B2BGeneratedContract.contract_kind == "mandate"
            )
        newest_first = (
            B2BGeneratedContract.created_at.desc(),
            B2BGeneratedContract.id.desc(),
        )
        if anchor is None:
            rows = (
                await db.execute(
                    rows_query.where(_generated_search_clause(needle))
                    .order_by(*newest_first)
                    .limit(SUBJECT_LIMIT)
                )
            ).all()
        else:
            # Umowa powiązana z kontraktem wygrywa. Kreator bierze pierwszy
            # wynik bez pytania, a nowsza umowa tej osoby bez powiązania
            # (wiersz z Excela ma datę importu) wypierała właściwą — dokument
            # cytował wtedy nie tę umowę (przegląd kodu 13.10.2026).
            rows = (
                await db.execute(
                    rows_query.where(B2BGeneratedContract.contract_id == anchor.id)
                    .order_by(*newest_first)
                    .limit(SUBJECT_LIMIT)
                )
            ).all()
            if not rows and doc_type.family == "annex" and anchor.candidate_id:
                # Umowa bez powiązania (ta sama osoba i klient) tylko dla
                # aneksu — dowiąże wiersz do tego kontraktu — i tylko gdy jest
                # jedna: przy kilku nie zgadujemy, człowiek wybiera w wyszukiwarce.
                rows = (
                    await db.execute(
                        rows_query.where(
                            B2BGeneratedContract.contract_id.is_(None),
                            B2BGeneratedContract.candidate_id == anchor.candidate_id,
                            B2BGeneratedContract.client_id == anchor.client_id,
                        ).limit(2)
                    )
                ).all()
                if len(rows) > 1:
                    return []

        options_by_row: dict[int, list[int]] = {}
        if doc_type.family == "annex" and doc_type.parent == "b2b":
            for row, _name, _lastname in rows:
                if (
                    row.contract_id is None
                    and binds
                    and _in_delivery_scope(row.client_id, delivery_boundary)
                ):
                    options_by_row[
                        row.id
                    ] = await effects.live_contract_ids_for_unlinked_row(
                        db,
                        row_id=row.id,
                        candidate_id=row.candidate_id,
                        client_id=row.client_id,
                        contract_type=ContractType.b2b,
                    )
        offered_contract_ids = {
            row.contract_id for row, _n, _l in rows if row.contract_id is not None
        } | {cid for ids in options_by_row.values() for cid in ids}
        contracts_by_id: dict[int, Contract] = {}
        if offered_contract_ids:
            found = await db.scalars(
                select(Contract).where(Contract.id.in_(offered_contract_ids))
            )
            contracts_by_id = {c.id: c for c in found.all()}
        for row, name, lastname in rows:
            linked = contracts_by_id.get(row.contract_id or -1)
            subjects.append(
                DocumentSubject(
                    kind="agreement",
                    parent_generated_contract_id=row.id,
                    contract_number=row.contract_number
                    or getattr(row, "raw_contract_number", None),
                    source=getattr(row, "source", None),
                    agreement_status=row.contract_status,
                    contract_id=row.contract_id,
                    # Status powiązanego kontraktu niesie już wiersz „Umów
                    # bieżących”; data startu kontraktu to dane Delivery.
                    contract_status=_status_value(linked.status) if linked else None,
                    contract_start_date=(
                        linked.start_date
                        if linked
                        and binds
                        and _in_delivery_scope(linked.client_id, delivery_boundary)
                        else None
                    ),
                    contract_options=[
                        SubjectContract(
                            contract_id=cid,
                            status=_status_value(contracts_by_id[cid].status),
                            start_date=contracts_by_id[cid].start_date,
                        )
                        for cid in options_by_row.get(row.id, [])
                        if cid in contracts_by_id
                    ],
                    candidate_id=row.candidate_id,
                    person_name=_full_name(name, lastname) or row.partner_name,
                    partner_name=row.partner_legal_name,
                    partner_nip=row.partner_nip,
                    client_id=row.client_id,
                    client_name=row.client_name,
                )
            )

    if _takes_contract(doc_type) and binds:
        live_agreement = (
            select(B2BGeneratedContract.id)
            .where(
                B2BGeneratedContract.contract_id == Contract.id,
                B2BGeneratedContract.contract_status.in_(_LIVE_AGREEMENT_STATUSES),
            )
            .exists()
        )
        contracts_query = await _scope_generator_query(
            select(Contract, Candidate, Client),
            Contract.client_id,
            db,
            current_user,
        )
        contracts_query = (
            contracts_query.join(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(
                Contract.contract_type == _subject_contract_type(doc_type),
                Contract.status != ContractStatus.void,
                ~live_agreement,
            )
        )
        if delivery_boundary is not None:
            contracts_query = contracts_query.where(
                Contract.client_id.in_(delivery_boundary)
            )
        if offered_contract_ids:
            contracts_query = contracts_query.where(
                Contract.id.notin_(offered_contract_ids)
            )
        if anchor is not None:
            contracts_query = contracts_query.where(Contract.id == anchor.id)
        else:
            clauses = [
                polish_folded_ilike(Candidate.name, needle),
                polish_folded_ilike(Candidate.lastname, needle),
                polish_folded_ilike(
                    func.concat(Candidate.name, " ", Candidate.lastname), needle
                ),
                polish_folded_ilike(Candidate.legal_name, needle),
                polish_folded_ilike(B2BContractDetail.contract_number, needle),
            ]
            nip_needle = re.sub(r"\D", "", needle)
            if len(nip_needle) >= 5:
                clauses.append(
                    Candidate.nip.ilike(_like_needle(nip_needle), escape="\\")
                )
            contracts_query = contracts_query.outerjoin(
                B2BContractDetail, B2BContractDetail.contract_id == Contract.id
            ).where(or_(*clauses))
        live_first = case(
            (
                Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
                0,
            ),
            else_=1,
        )
        found_contracts = (
            await db.execute(
                contracts_query.order_by(live_first, Contract.id.desc()).limit(
                    SUBJECT_LIMIT
                )
            )
        ).all()
        for contract, candidate, client in found_contracts:
            subjects.append(
                DocumentSubject(
                    kind="contract",
                    contract_id=contract.id,
                    contract_status=_status_value(contract.status),
                    contract_start_date=contract.start_date,
                    candidate_id=candidate.id,
                    person_name=_full_name(candidate.name, candidate.lastname),
                    partner_name=candidate.legal_name,
                    partner_nip=candidate.nip,
                    client_id=contract.client_id,
                    client_name=_client_label(client),
                )
            )
    return subjects


@router.get("/documents/preliminary-options")
async def preliminary_options(
    current_user: B2BGeneratorAccess,
    candidate_id: int = Query(...),
    job_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Umowy przedwstępne, które wolno wystawić w tej rekrutacji (po jej
    kliencie): Centrum e-Zdrowia — własny wzór, inni klienci — umowa o udziale
    w procesie rekrutacyjnym. Dostęp jak przy prefillu: przez rekrutację."""
    job = await _load_legal_scoped_job(db, current_user, job_id, write=True)
    await _validate_candidate_job_link(db, candidate_id=candidate_id, job_id=job.id)
    allowed = _preliminary_types_for(job.client_id)
    return {
        "client_id": job.client_id,
        "types": [
            {
                "key": t.key,
                "label": t.label,
                "default_validity_days": t.default_validity_days,
                "b2b_term_business_days": t.b2b_term_business_days,
            }
            for t in allowed
        ],
        "default_validity_days": allowed[0].default_validity_days if allowed else None,
        "b2b_term_business_days": allowed[0].b2b_term_business_days
        if allowed
        else None,
    }


@router.get("/documents/prefill")
async def document_prefill(
    current_user: B2BGeneratorAccess,
    document_type: str = Query(...),
    parent_generated_contract_id: Optional[int] = Query(None),
    candidate_id: Optional[int] = Query(None),
    job_id: Optional[int] = Query(None),
    contract_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Wartości startowe formularza z umowy bazowej (albo z kandydata)."""
    doc_type = _type_or_422(document_type)
    today = business_today()
    values: dict[str, Any] = {"document_date": today.isoformat()}
    parent: B2BGeneratedContract | None = None
    contract: Contract | None = None
    job = None
    if parent_generated_contract_id is not None:
        parent = await _load_parent(db, parent_generated_contract_id)
        await _authorize_parent(db, current_user, parent)
        # Kandydat umowy bazowej — nie ten z parametru, który mógłby wskazać
        # dowolną osobę obok umowy, do której wołający ma dostęp.
        candidate_id = parent.candidate_id
    elif contract_id is not None and _takes_contract(doc_type):
        # Aneks do kontraktu bez umowy w rejestrze: dane Partnera z profilu
        # osoby z TEGO kontraktu (dostęp przez zapis u jego klienta).
        contract = await _load_subject_contract(db, current_user, doc_type, contract_id)
        candidate_id = contract.candidate_id
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
        "partner_address_for_service",
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
    if annex_done:
        # Po aneksie „dane firmy” adres jest nowy, a rodzaj adresu z payloadu
        # opisuje stary — o nowym mówi „Pobierz z CEIDG”.
        values.pop("partner_address_for_service", None)
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
        days = doc_type.default_validity_days or 60
        values["valid_until"] = (today + timedelta(days=days)).isoformat()
    if "penalty_amount" in field_keys:
        values["penalty_amount"] = PARTICIPATION_PENALTY_DEFAULT
    if "project_label" in field_keys and job is not None:
        client = await db.get(Client, job.client_id) if job.client_id else None
        label = " — ".join(
            part
            for part in (
                (client.display_name or client.name or "").strip()
                if client is not None
                else "",
                (job.title or "").strip(),
            )
            if part
        )
        if label:
            values["project_label"] = label
    if "entity_type" in field_keys:
        values["entity_type"] = "sole_trader"
    if "base_signing_date" in field_keys and base.signing_date:
        values["base_signing_date"] = base.signing_date.isoformat()
    paragraph_defaults: dict[str, list[str]] = {}
    if doc_type.allows_external:
        paragraph_defaults = _annex_paragraph_defaults(doc_type, base)
        values = await _annex_prefill(db, doc_type, parent, base, payload, values)
    if contract is not None:
        # Numer i data umowy z kontraktu, jeśli ktoś je tam wpisał; stawek
        # kontraktu NIE podpowiadamy — autor aneksu nie musi mieć do nich wglądu.
        detail = contract.b2b_detail
        if detail is not None and "contract_number" in field_keys:
            if detail.contract_number and not values.get("contract_number"):
                values["contract_number"] = detail.contract_number
            if detail.signing_date and not values.get("contract_signing_date"):
                values["contract_signing_date"] = detail.signing_date.isoformat()
        if "current_start_date" in field_keys and contract.start_date:
            values.setdefault("current_start_date", contract.start_date.isoformat())
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
            render_html, _current_key(doc_type, language), context
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
    if parent is None and links["contract_id"] is not None:
        # Tu, nie w `_load_subject_contract`: podgląd i „Popraw” (prefill)
        # dzielą tamtą funkcję, a kontrakt mógł dostać umowę już po aneksie.
        await _reject_contract_with_own_agreement(db, links["contract_id"])
    values = await _resolve_rate_clients(db, request.values)
    _validate_values(doc_type, values, base, request.refs)
    if parent is None and links["client_id"] is None and _takes_contract(doc_type):
        # Tu, nie w `_resolve_subject`: podgląd dzieli tamtą funkcję i ma
        # działać, zanim człowiek wskaże kontrakt albo klienta.
        raise HTTPException(
            status_code=422,
            detail={
                "code": "document_fields_missing",
                "message": "Wybierz kontrakt albo klienta, którego dotyczy aneks.",
                "missing": ["Klient"],
            },
        )
    context = _context(doc_type, values, language, base, request.refs)
    # Render przed zapisem: błąd szablonu nie zostawia wiersza bez dokumentu.
    data = await _render_bytes(doc_type, language, context)
    doc_date = _date(values.get("document_date")) or business_today()
    linked_contract_id: int | None = None
    if parent is not None and doc_type.family == "annex" and doc_type.parent == "b2b":
        # Wiersz rejestru zmienia się teraz — blokada, żeby dwa aneksy do tej
        # samej umowy nie zapisały sobie nawzajem stanu „sprzed”.
        parent, linked_contract_id = await _lock_parent_linking_contract(
            db,
            parent,
            request.contract_id,
            may_link=_binds_contracts(current_user)
            and _in_delivery_scope(
                parent.client_id,
                await resolve_delivery_lead_client_ids(current_user, db),
            ),
            user_id=current_user.id,
        )
        links["contract_id"] = parent.contract_id
    elif parent is not None and doc_type.allows_external:
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
        template_key=_current_key(doc_type, language),
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
                "contract_id": doc.contract_id,
                **({"register_fields": register_fields} if register_fields else {}),
            },
        )
    )
    if linked_contract_id is not None and parent is not None:
        db.add(
            Activity(
                entity_type="b2b_generated_contract",
                entity_id=parent.id,
                action="contract_linked_for_annex",
                user_id=current_user.id,
                details={"contract_id": linked_contract_id, "document_id": doc.id},
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
    family: Optional[list[str]] = Query(None),
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
    if family:
        # Rejestr aneksów pyta o `annex`, zakładka „Dokumenty” o pozostałe
        # rodziny. Nieznana rodzina = 422 z nazwą pomyłki: ciche pominięcie
        # filtra oddałoby pełną listę pod nagłówkiem, który obiecuje podzbiór.
        known = {t.family for t in TYPES.values()}
        unknown = sorted(set(family) - known)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Nieznana rodzina dokumentów: {', '.join(unknown)}.",
            )
        query = query.where(
            B2BContractDocument.document_type.in_(
                [key for key, t in TYPES.items() if t.family in family]
            )
        )
    if status_filter:
        if status_filter == "unsigned":
            query = query.where(
                B2BContractDocument.status == "issued",
                B2BContractDocument.signature_status == "unsigned",
            )
        elif status_filter == "no_contract":
            # Aneks czekający na podpis bez kontraktu, na który podpis mógłby
            # zadziałać: własnego (umowa spoza NEXUSA) albo umowy bazowej.
            parent_contract = (
                select(B2BGeneratedContract.contract_id)
                .where(
                    B2BGeneratedContract.id
                    == B2BContractDocument.parent_generated_contract_id
                )
                .scalar_subquery()
            )
            query = query.where(
                B2BContractDocument.status == "issued",
                B2BContractDocument.signature_status == "unsigned",
                or_(
                    and_(
                        B2BContractDocument.parent_generated_contract_id.is_(None),
                        B2BContractDocument.contract_id.is_(None),
                    ),
                    and_(
                        B2BContractDocument.parent_generated_contract_id.is_not(None),
                        parent_contract.is_(None),
                    ),
                ),
            )
        elif status_filter in ("issued", "signed", "cancelled"):
            query = query.where(B2BContractDocument.status == status_filter)
        else:
            raise HTTPException(status_code=422, detail="Nieznany status dokumentu.")
    needle = (q or "").strip()
    if needle:
        # Osoba, firma, NIP albo numer umowy. `polish_folded_ilike` escapuje
        # `%` i `_` (do 13.10.2026 wzorzec szedł do LIKE bez escapu) i nie
        # rozróżnia polskich znaków.
        values = B2BContractDocument.render_payload["values"]
        query = query.outerjoin(
            Candidate, Candidate.id == B2BContractDocument.candidate_id
        )
        clauses = [
            polish_folded_ilike(values["partner_name"].astext, needle),
            polish_folded_ilike(values["partner_legal_name"].astext, needle),
            polish_folded_ilike(values["new_legal_name"].astext, needle),
            polish_folded_ilike(
                B2BContractDocument.render_payload["base"]["contract_number"].astext,
                needle,
            ),
            polish_folded_ilike(Candidate.name, needle),
            polish_folded_ilike(Candidate.lastname, needle),
            polish_folded_ilike(
                func.concat(Candidate.name, " ", Candidate.lastname), needle
            ),
        ]
        nip_needle = re.sub(r"\D", "", needle)
        if len(nip_needle) >= 5:
            pattern = _like_needle(nip_needle)
            clauses.append(values["partner_nip"].astext.ilike(pattern, escape="\\"))
            clauses.append(values["new_nip"].astext.ilike(pattern, escape="\\"))
        query = query.where(or_(*clauses))
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
    client = await db.get(Client, doc.client_id) if doc.client_id is not None else None
    return {
        "id": doc.id,
        "document_type": doc.document_type,
        "language": doc.language,
        "parent_generated_contract_id": doc.parent_generated_contract_id,
        "candidate_id": doc.candidate_id,
        "job_id": doc.job_id,
        # Aneks bez umowy w rejestrze: „Popraw” wraca do formularza bez
        # wyboru umowy — kontrakt i klient zostają te z zapisu.
        "contract_id": doc.contract_id,
        "client_id": doc.client_id,
        "client_name": _client_label(client),
        "external": doc.parent_generated_contract_id is None
        and doc_type.allows_external,
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


async def _issued_document_bytes(
    db: AsyncSession, user: User, doc_id: int, body: SensitiveValues
) -> tuple[B2BContractDocument, DocumentType, dict[str, Any], bytes]:
    """DOCX wydanego dokumentu jego własnym wzorem (zapisany ``template_key``).

    Dla dokumentów z danymi wrażliwymi body niesie te dane (nie
    przechowujemy ich) — bez nich 422 z listą pól."""
    _require_contract_generation(user)
    doc, doc_type, parent = await _load_document(db, user, doc_id)
    await _authorize_document_write(db, user, doc, parent)
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
    data = await _render_bytes(
        doc_type, doc.language, context, stored_key=doc.template_key
    )
    return doc, doc_type, values, data


@router.post("/documents/{doc_id}/docx")
async def redownload_document(
    doc_id: int,
    body: SensitiveValues,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz ponownie — tym samym wzorem, z którego dokument wydano."""
    doc, doc_type, values, data = await _issued_document_bytes(
        db, current_user, doc_id, body
    )
    return _docx_response(data, _filename(doc_type, values, doc.document_date), doc.id)


#: Odpowiedź, gdy LibreOffice nie zrobił PDF-u — DOCX działa zawsze.
PDF_UNAVAILABLE = "Nie udało się przygotować PDF — pobierz DOCX."


@router.post("/documents/{doc_id}/pdf")
async def document_pdf(
    doc_id: int,
    body: SensitiveValues,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """PDF wydanego dokumentu — ten sam plik Word co „Pobierz DOCX”,
    zamieniony przez LibreOffice (``cv_pdf_preview``). Bramki jak przy DOCX."""
    doc, doc_type, values, data = await _issued_document_bytes(
        db, current_user, doc_id, body
    )
    try:
        pdf = await pdf_from_docx(data)
    except PdfPreviewUnavailable as exc:
        raise HTTPException(status_code=503, detail=PDF_UNAVAILABLE) from exc
    filename = _filename(doc_type, values, doc.document_date).removesuffix(".docx")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.pdf"',
            "Access-Control-Expose-Headers": "Content-Disposition, X-Document-Id",
            "X-Document-Id": str(doc.id),
        },
    )


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
    await _authorize_document_write(db, current_user, doc, parent)
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
    doc.template_key = _current_key(doc_type, language)
    doc.document_date = _date(values.get("document_date")) or doc.document_date
    previous = doc.render_payload or {}
    payload: dict[str, Any] = {
        "values": strip_sensitive(doc_type, values),
        "refs": request.refs,
        "base": _base_snapshot(base),
    }
    payload.update(annex_register.carried(previous))
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


def _confirmer_entry(user: User) -> bool:
    """Bramka wejścia osoby potwierdzającej podpis dokumentu.

    Zwraca ``True``, gdy wołający wchodzi WYŁĄCZNIE jako posiadacz „Stawki
    i kwoty: zmiana”: aneks stawki potwierdza też on, bez uprawnienia „Umowy
    B2B: oznaczanie jako podpisane” (domyślnie Finanse, decyzja Artura
    27.09.2026). Typ i klienta dokumentu znamy dopiero po odczycie, więc
    zawężenie do aneksu stawki robi ``_assert_confirmer_of``."""
    amounts_only = not _has_signature_permission(user) and has_permission(
        user, ProductAction.amounts_edit
    )
    if amounts_only:
        assert_b2b_generator_action_access(user, ActionAccess.view)
    else:
        _require_signature_confirmation(user)
    return amounts_only


async def _assert_confirmer_of(
    db: AsyncSession,
    user: User,
    doc: B2BContractDocument,
    doc_type: DocumentType,
    parent: B2BGeneratedContract | None,
    *,
    amounts_only: bool,
) -> None:
    """Aneks stawki potwierdza posiadacz zmiany kwot u klienta, u którego
    zmienia kwoty. Każdy inny dokument — posiadacz uprawnienia podpisu w tym
    samym zakresie co podpis umowy (``_may_confirm_document_signature``,
    19.10.2026). Resztę bramek i blokad liczy ``effects.describe``."""
    if doc_type.key == RATE_ANNEX_TYPE and can_manage_finance_amounts(
        user,
        client_id=doc.client_id,
        delivery_lead_finance_client_ids=(
            await resolve_delivery_lead_finance_client_ids(user, db)
        ),
    ):
        return
    if amounts_only:
        _require_signature_confirmation(user)
    await _require_document_signature_scope(db, user, doc=doc, parent=parent)


@router.post("/documents/{doc_id}/signed-scan", response_model=DocumentItem)
async def upload_signed_scan(
    doc_id: int,
    current_user: B2BGeneratorAccess,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Dołącz skan podpisanego aneksu — trafia do Dokumentów kontraktu.

    Okno „Oznacz jako podpisany” woła najpierw podpis (JSON, bez zmian),
    potem tę trasę. Wchodzi ten, kto mógłby ten aneks potwierdzić: plik ląduje
    w kontrakcie, więc obowiązują te same bramki skutku w kontrakcie co przy
    podpisie (router generatora stoi za sekcją Sourcing — bramka zapisu
    Delivery sama tu nie działa)."""
    amounts_only = _confirmer_entry(current_user)
    locked_contract_id = await _lock_contract_first(db, doc_id=doc_id)
    doc, doc_type, parent = await _load_document(db, current_user, doc_id, lock=True)
    await _assert_confirmer_of(
        db, current_user, doc, doc_type, parent, amounts_only=amounts_only
    )
    _assert_same_locked_contract(
        locked_contract_id, effects.current_contract_id(doc, parent)
    )
    await _assert_signature_client_access(db, current_user, doc.client_id)
    if doc_type.family != "annex":
        raise HTTPException(
            status_code=422, detail="Skan dołącza się wyłącznie do aneksu."
        )
    required = effects.contract_effect_permission(doc_type)
    if required is not None:
        ensure_permission(current_user, required)
    if not effects.can_write_delivery(current_user):
        raise HTTPException(status_code=403, detail=effects.DELIVERY_WRITE_BLOCKER)
    if doc_type.key == RATE_ANNEX_TYPE and not await effects.can_confirm_rate_annex(
        db, current_user, doc.client_id
    ):
        raise HTTPException(
            status_code=403, detail=effects.RATE_ANNEX_CONFIRMER_BLOCKER
        )
    name, content_type, data = await signed_scan.read_scan(file)
    replaced_path = await signed_scan.attach(
        db,
        doc=doc,
        filename=name,
        content_type=content_type,
        data=data,
        actor_id=current_user.id,
    )
    await db.commit()
    signed_scan.discard(replaced_path)
    await db.refresh(doc)
    return (await _serialize(db, [doc], current_user))[0]


@router.post("/documents/{doc_id}/confirm-signed", response_model=DocumentItem)
async def confirm_document_signed(
    doc_id: int,
    current_user: B2BGeneratorAccess,
    body: Optional[SensitiveValues] = None,
    db: AsyncSession = Depends(get_db),
):
    """Oznacz jako podpisany obustronnie i zastosuj skutki (idempotentnie)."""
    amounts_only = _confirmer_entry(current_user)
    locked_contract_id = await _lock_contract_first(db, doc_id=doc_id)
    doc, doc_type, parent = await _load_document(db, current_user, doc_id, lock=True)
    await _assert_confirmer_of(
        db, current_user, doc, doc_type, parent, amounts_only=amounts_only
    )
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
        data = await _render_bytes(
            doc_type, doc.language, context, stored_key=doc.template_key
        )
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
                # Powód zostaje w historii także po przywróceniu aneksu,
                # które czyści go na dokumencie.
                "reason": doc.cancelled_reason,
                **({"register_restored": restored} if restored else {}),
            },
        )
    )
    await db.commit()
    await db.refresh(doc)
    return (await _serialize(db, [doc], current_user))[0]


@router.post("/documents/{doc_id}/restore", response_model=DocumentItem)
async def restore_document(
    doc_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Przywróć anulowany dokument — wraca na „czeka na podpis”.

    Aneks nie ma numeru, więc anulowany dałoby się wystawić od nowa, ale
    wtedy rejestr trzymałby dwa wpisy tego samego aneksu. „Podpisany” ustawia
    nadal wyłącznie „Oznacz jako podpisany”."""
    doc, _doc_type, parent = await _load_document(db, current_user, doc_id, lock=True)
    _require_generated_contract_management(current_user)
    if doc.status != "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Przywrócić można tylko anulowany dokument.",
        )
    if not current_user.has_role(UserRole.admin) and doc.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Przywrócić dokument może jego autor albo administrator.",
        )
    await _authorize_document_write(db, current_user, doc, parent)
    doc.status = "issued"
    doc.cancelled_reason = None
    # Wiersz rejestru wraca do wartości najnowszego aktywnego aneksu tego
    # typu — przywrócony starszy aneks nie wypiera nowszego.
    changed = await annex_register.restore(db, doc, parent)
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="restored",
            user_id=current_user.id,
            details={
                "document_type": doc.document_type,
                **({"register_changed": changed} if changed else {}),
            },
        )
    )
    await db.commit()
    await db.refresh(doc)
    return (await _serialize(db, [doc], current_user))[0]


@router.post("/documents/{doc_id}/link-contract", response_model=DocumentItem)
async def link_document_contract(
    doc_id: int,
    body: LinkContractRequest,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
):
    """Powiąż niepodpisany aneks z kontraktem, w którym podpis ma coś zmienić.

    Aneks „Bez kontraktu” (osoba nie miała kontraktu w chwili generowania)
    i aneks, którego kontrakt unieważniono, czekają tu na właściwy kontrakt.
    Przy aneksie do umowy z rejestru powiązanie dostaje WIERSZ umowy — kontrakt
    musi być jednym z trwających kontraktów tej osoby u tego klienta.

    Blokady: kontrakt docelowy, potem dokument i wiersz (runda 6 audytu,
    LOCK-1). Dotychczasowego kontraktu nie blokujemy — podpis trzyma go
    i czeka na dokument, więc blokada w odwrotnej kolejności by się zakleszczyła."""
    _require_generated_contract_management(current_user)
    # Powiązanie to zapis w Delivery — prawo generatora nie wystarcza.
    _require_contract_binding(current_user)
    await db.execute(
        select(Contract.id).where(Contract.id == body.contract_id).with_for_update()
    )
    doc, doc_type, parent = await _load_document(db, current_user, doc_id, lock=True)
    if doc.status != "issued" or doc.signature_status == "signed_both":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Powiązać z kontraktem można tylko aneks czekający na podpis.",
        )
    if doc_type.family != "annex":
        raise HTTPException(
            status_code=422, detail="Z kontraktem wiąże się wyłącznie aneksy."
        )
    if parent is not None:
        if doc_type.parent != "b2b":
            raise HTTPException(
                status_code=422, detail="Ten aneks nie ma kontraktu do powiązania."
            )
        if parent.contract_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Umowa ma już kontrakt — zmień go w rejestrze umów "
                    "(„Powiąż z kontraktem”)."
                ),
            )
        await _authorize_parent(db, current_user, parent)
        # Kontrakt z listy dopasowań jest u klienta umowy — portfel Delivery
        # Leada sprawdzamy na nim.
        assert_delivery_lead_client_visible(
            parent.client_id,
            await resolve_delivery_lead_client_ids(current_user, db),
        )
        live = await effects.live_contract_ids_for_unlinked_row(
            db,
            row_id=parent.id,
            candidate_id=parent.candidate_id,
            client_id=parent.client_id,
            contract_type=ContractType.b2b,
        )
        if body.contract_id not in live:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Ten kontrakt nie należy do osoby i klienta tej umowy "
                    "albo ma już własną umowę w rejestrze."
                ),
            )
        # Rdzeń „Powiąż z kontraktem” z rejestru umów: numer umowy na
        # kontrakcie i wpis na osi czasu (audyt 13.10.2026).
        await apply_contract_link(
            db,
            parent,
            await db.get(Contract, body.contract_id),
            user_id=current_user.id,
        )
        doc.contract_id = body.contract_id
    else:
        if not _takes_contract(doc_type):
            raise HTTPException(
                status_code=422, detail="Ten aneks nie ma kontraktu do powiązania."
            )
        await _authorize_document_write(db, current_user, doc, None)
        current = (
            await db.get(Contract, doc.contract_id)
            if doc.contract_id is not None
            else None
        )
        if current is not None and current.status != ContractStatus.void:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Aneks jest już powiązany z kontraktem.",
            )
        contract = await _load_subject_contract(
            db, current_user, doc_type, body.contract_id
        )
        await _assert_annex_link_same_subject(db, doc, contract)
        await _reject_contract_with_own_agreement(db, contract.id)
        doc.contract_id = contract.id
        doc.candidate_id = contract.candidate_id
        doc.job_id = contract.job_id
        doc.client_id = contract.client_id
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="contract_linked",
            user_id=current_user.id,
            details={
                "document_type": doc.document_type,
                "contract_id": body.contract_id,
            },
        )
    )
    await db.commit()
    await db.refresh(doc)
    return (await _serialize(db, [doc], current_user))[0]


#: Zdarzenia aneksu pokazywane w historii — reszta wpisów (i ich szczegóły)
#: zostaje w dzienniku.
_HISTORY_ACTIONS = frozenset(
    {
        "generated",
        "regenerated",
        "cancelled",
        "restored",
        "contract_linked",
        "signed_effect_applied",
        "signed_scan_attached",
    }
)


@router.get("/documents/{doc_id}/history", response_model=list[DocumentHistoryEntry])
async def document_history(
    doc_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentHistoryEntry]:
    """Historia dokumentu z dziennika zdarzeń: kto i kiedy wygenerował,
    poprawił, anulował, przywrócił, powiązał z kontraktem, podpisał.

    Bez osobnej tabeli statusów: aneks ma dwa ręczne przejścia (anuluj,
    przywróć), a każde zdarzenie zapisuje już ``Activity``. Oddajemy wyłącznie
    nazwę zdarzenia i powód anulowania — ``details`` podpisu niesie id aneksów
    kontraktu i nie jest treścią dla listy."""
    await _load_document(db, current_user, doc_id)
    found = await db.execute(
        select(Activity, User.name)
        .outerjoin(User, User.id == Activity.user_id)
        .where(
            Activity.entity_type == "b2b_contract_document",
            Activity.entity_id == doc_id,
            Activity.action.in_(_HISTORY_ACTIONS),
        )
        .order_by(Activity.created_at.asc(), Activity.id.asc())
    )
    return [
        DocumentHistoryEntry(
            action=activity.action,
            at=activity.created_at.isoformat() if activity.created_at else None,
            by_name=name,
            note=(
                (activity.details or {}).get("reason")
                if activity.action == "cancelled"
                else None
            ),
        )
        for activity, name in found.all()
    ]


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
    await _require_document_signature_scope(db, current_user, doc=None, parent=parent)
    _assert_same_locked_contract(locked_contract_id, parent.contract_id)
    await _assert_signature_client_access(db, current_user, parent.client_id)
    await _assert_generator_client_access(
        db, current_user, parent.client_id, write=True
    )
    if parent.contract_id is not None or matched_contract_id is not None:
        # Wypowiedzenie kończy współpracę w kontrakcie — to samo uprawnienie
        # co okno „Zakończ współpracę”; samo oznaczanie podpisu nie wystarcza.
        ensure_permission(current_user, ProductAction.contract_status)
        if not effects.can_write_delivery(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "section_access_denied",
                    "section": "delivery",
                    "message": effects.DELIVERY_WRITE_BLOCKER,
                },
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
        matched_contract_id=matched_contract_id,
    )
    await db.commit()
    return summary
