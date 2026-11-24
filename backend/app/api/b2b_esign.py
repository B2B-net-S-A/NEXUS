"""Podpis umowy B2B w NEXUSIE — trasy (0499, decyzja Artura 21.10.2026).

Droga obok zwykłej („Oznacz jako podpisaną”), za przełącznikiem
``app_settings['b2b_esign']``. Trasy wewnętrzne stoją pod
``/api/b2b-generator`` za tą samą bramką sekcji co generator; trasy kontraktora
pod ``/api/public/b2b-sign/{token}`` (bez konta, z limitem żądań).

Kto co może:

* wysyła i wycofuje — ten, kto poprawia umowę (``_may_correct_generated``:
  autor, zespół rekrutacji, TCM, admin) albo mógłby oznaczyć jej podpis
  (``may_confirm_row_signature``, od 22.11.2026), z poziomem „Generowanie”,
  widocznymi stawkami (PDF niesie stawkę) i dostępem do klienta; w pilotażu
  tylko wybrane konta,
* podpisuje za B2B Network — osoba wskazana przy wysyłce, z listy reprezentantów
  w ustawieniach,
* ustawienia zmienia admin.

Bez ``from __future__ import annotations``: router publiczny ma
``@limiter.limit`` (ciało żądania lądowałoby jako parametr query → 422).
"""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.b2b_contract_generator import (
    _assert_generator_client_access,
    confirm_generated_contract_fully_signed,
    _jobs_led_by,
    _lock_person_contracts_before_row,
    _may_correct_generated,
    _reject_excel_row,
    _render_generated_row_docx,
    _require_contract_generation,
    _require_generator_rate_content,
    may_confirm_row_signature,
)
from app.api.contract_access import B2BGeneratorAccess
from app.api.deps import AdminUser
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.config import settings as app_config
from app.core.database import AsyncSessionLocal, get_db
from app.core.http_headers import content_disposition
from app.core.rate_limit import limiter
from app.core.scheduling import business_date
from app.core.scheduling import business_today
from app.models.b2b_esign_remote_session import B2BEsignRemoteSession
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_signing_document import B2BSigningDocument
from app.models.b2b_signing_request import B2BSigningRequest
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.job_work_assignment import JobWorkAssignment
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.schemas.b2b_contract_generator import B2BConfirmFullySignedRequest
from app.services import storage_service
from app.services.b2b_contract_filename import contract_file_name
from app.services.m365 import sender as m365_sender
from app.services.b2b_esign import accept_code
from app.services.b2b_esign import documents as esign_docs
from app.services.b2b_esign import service
from app.services.b2b_esign import csc
from app.services.b2b_esign import mail as esign_mail
from app.services.b2b_esign import remote
from app.services.b2b_esign import settings as esign_settings
from app.services.b2b_esign.verdict import Fingerprint
from app.services.b2b_contract_generator import mandate, signed_file
from app.services.b2b_contract_generator.signed_on_evidence import SignedOnEvidence
from app.services.b2b_esign.qualified import QualifiedValidator
from app.services.notification_triggers import emit as emit_notification
from app.services.cv_pdf_preview import PdfPreviewUnavailable, pdf_from_docx
from app.services.signing.validation import ValidationService

logger = logging.getLogger(__name__)
_WARSAW = ZoneInfo("Europe/Warsaw")

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)
public_router = APIRouter()

MSG_OFF = "Podpis w NEXUSIE nie jest włączony dla Twojego konta."
MSG_MANDATE = (
    "Podpis w NEXUSIE działa dla umów B2B. Umowę zlecenia podpiszcie poza "
    "NEXUSEM i oznacz ją jako podpisaną w rejestrze."
)
MSG_SIGNER = "Wybierz osobę, która podpisze za B2Bnetwork, z listy w ustawieniach."
MSG_TAKE_OVER_MAILBOX = (
    "Połącz swoją skrzynkę Microsoft 365 z NEXUSEM, zanim przejmiesz obsługę: "
    "przypomnienia, mail do podpisu za B2Bnetwork i kopia umowy idą ze skrzynki "
    "osoby, która obsługuje wysyłkę."
)
MSG_CC = (
    "Do wiadomości dodasz tylko osoby z zespołu tej rekrutacji albo autora "
    "umowy, które same widzą tę umowę ze stawkami."
)
MSG_PDF = (
    "Nie udało się zrobić PDF-a z umowy. Spróbuj za chwilę albo wyślij umowę jak dotąd."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _pdf_disposition(
    db: AsyncSession, request: B2BSigningRequest, suffix: str = ""
) -> str:
    """„Umowa B2B 1555-2026 Kowalski Jan.pdf” (Sandra i Klaudia, 26.10.2026)."""
    row = await db.get(B2BGeneratedContract, request.generated_contract_id)
    name = contract_file_name(
        row.contract_number if row else None,
        row.partner_name if row and row.partner_name else request.contractor_name,
        ext="pdf",
        suffix=suffix,
    )
    return f'attachment; filename="{name}"'


def _sign_url(token: str) -> str:
    return f"{app_config.PUBLIC_BASE_URL.rstrip('/')}/sign/b2b/{token}"


def _validator() -> QualifiedValidator | ValidationService:
    """pyHanko z listą UE albo EU DSS — ``B2B_ESIGN_VALIDATOR``."""
    if app_config.B2B_ESIGN_VALIDATOR.strip().lower() == "dss":
        return ValidationService()
    return QualifiedValidator()


# ── Schematy ────────────────────────────────────────────────────────────────


class EsignPerson(BaseModel):
    id: int
    name: str


class EsignCcPerson(EsignPerson):
    # Prowadzący rekrutację — okno zaznacza go od razu (decyzja Artura
    # 27.10.2026: mail z własnej skrzynki, rekruter w DW).
    suggested: bool = False


class EsignSettingsOut(BaseModel):
    mode: Literal["off", "pilot", "all"]
    can_send: bool
    company_signers: list[EsignPerson]
    # Tylko dla admina — reszta nie musi znać listy pilotażu.
    pilot_user_ids: Optional[list[int]] = None


class EsignSettingsIn(BaseModel):
    mode: Literal["off", "pilot", "all"]
    pilot_user_ids: list[int] = Field(default_factory=list, max_length=200)
    company_signer_ids: list[int] = Field(default_factory=list, max_length=20)


class EsignSendIn(BaseModel):
    # Imię i nazwisko podpisującego bierze się z umowy (``partner_name``),
    # nie z formularza — przegląd bezpieczeństwa 21.10.2026.
    contractor_email: EmailStr
    company_signer_id: int
    days: int = Field(default=14, ge=1, le=30)
    # Osoby z NEXUSA w DW (27.10.2026) — tylko z ``cc_candidates`` okna.
    cc_user_ids: list[int] = Field(default_factory=list, max_length=10)
    # Paczka (0687): pozycje listy klienta „Dokumenty do startu” obok umowy.
    # ``None`` = wszystkie z ``documents`` okna; lista = wybór nadawcy.
    start_document_ids: Optional[list[int]] = Field(default=None, max_length=20)
    # 0754: dokumenty, przy których klient wymaga podpisu kwalifikowanego.
    # Reszta paczki ma wymóg „dowolny podpis” (kontraktor może zaakceptować
    # kodem z maila); umowa zawsze kwalifikowanym (decyzja Artura 22.11.2026).
    qualified_document_ids: Optional[list[int]] = Field(default=None, max_length=20)


class EsignDocumentOption(BaseModel):
    id: int
    name: str


class EsignDocumentOut(BaseModel):
    id: int
    title: str
    signed_at: Optional[datetime] = None
    # 0754: ``qualified`` albo ``any``; jak podpisano: ``qualified``/``email_code``.
    requirement: str = "qualified"
    signed_via: Optional[str] = None


class EsignRequestOut(BaseModel):
    id: int
    generated_contract_id: int
    status: str
    contractor_name: str
    contractor_email: Optional[str]
    company_signer_id: Optional[int]
    company_signer_name: Optional[str]
    sent_at: datetime
    expires_at: datetime
    contractor_signed_at: Optional[datetime]
    completed_at: Optional[datetime]
    closed_at: Optional[datetime]
    close_reason: Optional[str]
    cc: list[EsignPerson] = Field(default_factory=list)
    # Dokumenty paczki obok umowy (0687) — podpisuje je tylko kontraktor.
    documents: list[EsignDocumentOut] = Field(default_factory=list)
    # Kontraktor podpisał umowę, ale w paczce czekają jeszcze dokumenty.
    contract_signed_at: Optional[datetime] = None
    # Kto obsługuje wysyłkę (po „Przejmij obsługę” — zastępca, 27.10.2026).
    handled_by_id: Optional[int] = None
    handled_by_name: Optional[str] = None
    # Tylko w liście „Czeka na mój podpis” (pulpit i rejestr) — reszta zna wiersz.
    contract_number: Optional[str] = None
    client_name: Optional[str] = None


class EsignSendOut(BaseModel):
    request: EsignRequestOut
    # Link do podpisu dla kontraktora. Mail idzie ze skrzynki nadawcy (M365);
    # bez połączonej skrzynki ``mail_sent=False`` i nadawca przekazuje link sam.
    sign_url: str
    mail_sent: bool = False
    mail_problem: Optional[str] = None


class EsignDefaultsOut(BaseModel):
    contractor_name: Optional[str]
    contractor_email: Optional[str]
    company_signers: list[EsignPerson]
    mailbox_connected: bool
    # Kogo można dodać do DW: zespół rekrutacji i autor, którzy sami
    # mogliby wysłać tę umowę (widzą stawki).
    cc_candidates: list[EsignCcPerson] = Field(default_factory=list)
    # Wzory z listy klienta, których para jeszcze nie ma (0687) — okno
    # zaznacza wszystkie.
    documents: list[EsignDocumentOption] = Field(default_factory=list)


class EsignRenewIn(BaseModel):
    # Okno pokazuje 1, 3, 5 albo 7 dni, jak przy wysyłce.
    days: int = Field(default=3, ge=1, le=30)


class EsignWithdrawIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class PublicSignDocument(BaseModel):
    id: int
    title: str
    signed: bool
    # 0754: ``qualified`` (podpis kwalifikowany) albo ``any`` (także kod z maila).
    requirement: Literal["qualified", "any"] = "qualified"
    signed_via: Optional[Literal["qualified", "email_code"]] = None


class RemoteSigningOut(BaseModel):
    """Podpis u dostawcy przez API CSC (E1): czy ten wniosek może z niego
    skorzystać i pod jaką nazwą dostawca stoi na ekranie."""

    available: bool = False
    provider_label: Optional[str] = None


class PublicSignView(BaseModel):
    contract_number: str
    contractor_name: str
    status: Literal["waiting", "signed_by_you", "completed", "expired", "closed"]
    # Przy ``waiting`` — do kiedy działa link; przy ``expired`` — kiedy minął.
    expires_at: Optional[datetime]
    # Kontraktor już poprosił o nowy link (27.10.2026), czeka na odpowiedź.
    renewal_requested_at: Optional[datetime] = None
    # Do kiedy działa „Pobierz umowę podpisaną przez obie strony” (26.10.2026).
    signed_pdf_until: Optional[datetime] = None
    # Paczka (0687): umowa już podpisana, a dokumenty obok niej.
    contract_signed: bool = False
    documents: list[PublicSignDocument] = Field(default_factory=list)
    # 0754: dokąd idzie kod (adres zamaskowany) i kiedy wysłano ostatni.
    accept_code_email: Optional[str] = None
    accept_code_sent_at: Optional[datetime] = None
    # E1: podpis u dostawcy jednym zatwierdzeniem (umowa i wybrane dokumenty).
    remote_signing: RemoteSigningOut = Field(default_factory=RemoteSigningOut)


RemoteState = Literal["waiting_for_user", "signing", "done", "failed", "cancelled"]


class RemoteStartIn(BaseModel):
    # Umowa wchodzi zawsze; tu dokumenty paczki podpisywane obok niej.
    include_document_ids: list[int] = Field(default_factory=list, max_length=20)
    method: Literal["own_certificate", "one_time"]


class RemoteStartOut(BaseModel):
    redirect_url: str
    session_id: str


class PublicRemoteStatus(BaseModel):
    state: RemoteState
    message: Optional[str] = None
    view: Optional[PublicSignView] = None


class CompanyRemoteStartIn(BaseModel):
    request_ids: list[int] = Field(min_length=1, max_length=20)


class CompanyRemoteStatus(BaseModel):
    state: RemoteState
    message: Optional[str] = None
    done_request_ids: list[int] = Field(default_factory=list)


class PublicAcceptIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)
    document_ids: list[int] = Field(min_length=1, max_length=20)


# ── Pomocnicze ──────────────────────────────────────────────────────────────


async def _names(db: AsyncSession, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows.all()}


async def _out(
    db: AsyncSession, request: B2BSigningRequest, *, with_contact: bool = True
) -> EsignRequestOut:
    cc_ids = list(request.cc_user_ids or [])
    handler = service.handler_id(request)
    names = await _names(
        db,
        [
            *([request.company_signer_id] if request.company_signer_id else []),
            *([handler] if handler else []),
            *cc_ids,
        ],
    )
    return EsignRequestOut(
        id=request.id,
        generated_contract_id=request.generated_contract_id,
        status=request.status,
        contractor_name=request.contractor_name,
        # E-mail kontraktora widzi nadawca i reprezentant firmy, nie każdy
        # z odczytem rejestru (przegląd bezpieczeństwa 21.10.2026).
        contractor_email=request.contractor_email if with_contact else None,
        company_signer_id=request.company_signer_id,
        company_signer_name=names.get(request.company_signer_id or -1),
        sent_at=request.sent_at,
        expires_at=request.expires_at,
        contractor_signed_at=request.contractor_signed_at,
        completed_at=request.completed_at,
        closed_at=request.closed_at,
        close_reason=request.close_reason,
        cc=[EsignPerson(id=uid, name=names[uid]) for uid in cc_ids if uid in names],
        documents=[
            EsignDocumentOut(
                id=d.id,
                title=d.title,
                signed_at=d.signed_at,
                requirement=d.requirement,
                signed_via=d.signed_via,
            )
            for d in await esign_docs.for_request(db, request.id)
        ],
        contract_signed_at=(
            service.contract_signed_at(request) if request.contractor_pdf_path else None
        ),
        handled_by_id=handler,
        handled_by_name=names.get(handler or -1),
    )


async def _cc_candidates(
    db: AsyncSession, row: B2BGeneratedContract, sender: User
) -> list[EsignCcPerson]:
    """Kogo nadawca może dodać do DW: zespół rekrutacji z nadania (prowadzący,
    TAC, Delivery Lead, aktywne przypisanie) i autor umowy — każdy tylko wtedy,
    gdy sam mógłby ją wysłać. DW dostaje link do PDF-a ze stawkami, więc ta
    sama bramka co wysyłka (``_assert_row_sender``)."""
    ids: list[int] = []
    lead: Optional[int] = None
    if row.job_id:
        job = await db.get(Job, row.job_id)
        if job is not None:
            lead = job.recruiter_id
            ids += [job.recruiter_id, job.tac_id, job.delivery_lead_id]
        ids += list(
            await db.scalars(
                select(JobWorkAssignment.user_id).where(
                    JobWorkAssignment.job_id == row.job_id,
                    JobWorkAssignment.state == "active",
                    JobWorkAssignment.source != "owner",
                )
            )
        )
    ids.append(row.created_by)
    out: list[EsignCcPerson] = []
    for uid in dict.fromkeys(i for i in ids if i and i != sender.id):
        user = await db.get(User, uid)
        if user is None or not user.is_active or not user.email:
            continue
        if await _may_send(db, user, row):
            out.append(EsignCcPerson(id=uid, name=user.name, suggested=uid == lead))
    return out


async def _cc_for_mail(
    db: AsyncSession, row: B2BGeneratedContract, user_ids: list[int]
) -> list[str]:
    """Adresy DW sprawdzane PRZED każdym mailem, nie tylko przy wysyłce
    (przegląd kodu 27.10.2026): kto wypadł z zespołu rekrutacji, nie dostaje
    już linku do PDF-a ze stawkami ani kopii podpisanej umowy."""
    allowed: list[int] = []
    for uid in user_ids:
        user = await db.get(User, uid)
        if user is not None and user.is_active and await _may_send(db, user, row):
            allowed.append(uid)
    return await esign_mail.cc_emails(db, allowed)


async def _assert_row_sender(
    db: AsyncSession, user: User, row: B2BGeneratedContract
) -> None:
    """Ten, kto może wysłać albo wycofać podpis tej umowy (patrz docstring modułu)."""
    _require_contract_generation(user)
    await _assert_generator_client_access(db, user, row.client_id, write=True)
    await _require_generator_rate_content(
        db, user, row.client_id, created_by=row.created_by, job_id=row.job_id
    )
    team = await _jobs_led_by(db, user, {row.job_id} if row.job_id else set())
    if _may_correct_generated(user, row, team):
        return
    # 22.11.2026: kto potwierdza podpis tej umowy (np. Administracja przy
    # umowie rekrutera), ten może ją też wysłać do podpisu.
    if await may_confirm_row_signature(db, user, row):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "Do podpisu wysyła osoba, która wygenerowała umowę, zespół "
            "rekrutacji, TCM, admin albo osoba, która może oznaczyć jej podpis."
        ),
    )


async def _fresh(db: AsyncSession, request_id: int) -> B2BSigningRequest:
    """Wniosek wczytany na nowo (także gdy obiekt w sesji wygasł po rollbacku)."""
    request = await db.scalar(
        select(B2BSigningRequest)
        .where(B2BSigningRequest.id == request_id)
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise HTTPException(status_code=404, detail="Wniosek o podpis nie istnieje.")
    return request


async def _may_send(db: AsyncSession, user: User, row: B2BGeneratedContract) -> bool:
    try:
        await _assert_row_sender(db, user, row)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return False
    return True


async def _upload_bytes(file: UploadFile) -> bytes:
    data = await file.read(service.MAX_UPLOAD_BYTES + 1)
    service.check_pdf_upload(data)
    return data


# ── Ustawienia ──────────────────────────────────────────────────────────────


@router.get("/esign/settings", response_model=EsignSettingsOut)
async def get_esign_settings(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> EsignSettingsOut:
    current = await esign_settings.load(db)
    names = await _names(db, list(current.company_signer_ids))
    return EsignSettingsOut(
        mode=current.mode,
        can_send=current.can_send(current_user),
        company_signers=[
            EsignPerson(id=uid, name=names[uid])
            for uid in current.company_signer_ids
            if uid in names
        ],
        pilot_user_ids=(
            sorted(current.pilot_user_ids)
            if current_user.has_role(UserRole.admin)
            else None
        ),
    )


@router.put("/esign/settings", response_model=EsignSettingsOut)
async def put_esign_settings(
    body: EsignSettingsIn,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> EsignSettingsOut:
    known = await _names(db, list({*body.pilot_user_ids, *body.company_signer_ids}))
    unknown = [
        uid
        for uid in {*body.pilot_user_ids, *body.company_signer_ids}
        if uid not in known
    ]
    if unknown:
        raise HTTPException(status_code=422, detail="Nie ma takiego konta w NEXUSIE.")
    value = esign_settings.parse(body.model_dump())
    await esign_settings.save(db, value, actor_id=current_user.id)
    await db.commit()
    return await get_esign_settings(current_user, db)


# ── Wysyłka, stan, wycofanie ────────────────────────────────────────────────


@router.post("/generated/{generated_id}/esign/send", response_model=EsignSendOut)
async def send_for_esign(
    generated_id: int,
    body: EsignSendIn,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> EsignSendOut:
    current = await esign_settings.load(db)
    if not current.can_send(current_user):
        raise HTTPException(status_code=403, detail=MSG_OFF)
    if body.company_signer_id not in current.company_signer_ids:
        raise HTTPException(status_code=422, detail=MSG_SIGNER)
    row = await db.scalar(
        select(B2BGeneratedContract)
        .where(B2BGeneratedContract.id == generated_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    _reject_excel_row(row)
    if mandate.is_mandate(row):
        raise HTTPException(status_code=409, detail=MSG_MANDATE)
    await _assert_row_sender(db, current_user, row)
    service.assert_sendable(row)
    if body.cc_user_ids:
        allowed = {p.id for p in await _cc_candidates(db, row, current_user)}
        if not set(body.cc_user_ids) <= allowed:
            raise HTTPException(status_code=422, detail=MSG_CC)
    request, token = await open_signing_request(
        db,
        row,
        actor_id=current_user.id,
        contractor_email=str(body.contractor_email),
        company_signer_id=body.company_signer_id,
        days=body.days,
        cc_user_ids=body.cc_user_ids,
        start_document_ids=body.start_document_ids,
        qualified_document_ids=body.qualified_document_ids,
    )
    await db.commit()
    url = _sign_url(token)
    out = await _out(db, request)
    mail_sent, problem = await _mail_link(
        db, sender_id=current_user.id, request=out, row=row, url=url
    )
    return EsignSendOut(
        request=out, sign_url=url, mail_sent=mail_sent, mail_problem=problem
    )


async def open_signing_request(
    db: AsyncSession,
    row: B2BGeneratedContract,
    *,
    actor_id: int,
    contractor_email: str,
    company_signer_id: int,
    days: int,
    cc_user_ids: Optional[list[int]] = None,
    start_document_ids: Optional[list[int]] = None,
    qualified_document_ids: Optional[list[int]] = None,
) -> tuple[B2BSigningRequest, str]:
    """PDF umowy z Worda, PDF-y paczki i otwarty wniosek (bez commita).

    Wspólne dla „Wyślij do podpisu” i masowej wysyłki nowej umowy (E5b).
    Wołający trzyma blokadę wiersza i sprawdził nadawcę, przełącznik
    i reprezentanta. Awaria PDF-a = 503, wniosek nie powstaje."""
    chosen = esign_docs.choose(await esign_docs.candidates(db, row), start_document_ids)
    qualified_ids = esign_docs.choose_qualified(chosen, qualified_document_ids)
    docx = await _render_generated_row_docx(db, row)
    try:
        pdf = await pdf_from_docx(docx)
    except PdfPreviewUnavailable as exc:
        logger.warning("[b2b_esign] PDF z DOCX niedostępny row=%d: %s", row.id, exc)
        raise HTTPException(status_code=503, detail=MSG_PDF) from exc
    prepared: list[tuple[Any, bytes]] = []
    for document in chosen:
        try:
            prepared.append(
                (document, await esign_docs.render_pdf(document, row.render_payload))
            )
        except (PdfPreviewUnavailable, FileNotFoundError) as exc:
            logger.warning(
                "[b2b_esign] PDF dokumentu niedostępny row=%d document=%d: %s",
                row.id,
                document.id,
                exc,
            )
            raise HTTPException(
                status_code=503, detail=esign_docs.doc_pdf_problem(document.name)
            ) from exc
    request, token = await service.send(
        db,
        row=row,
        pdf=pdf,
        actor_id=actor_id,
        contractor_email=contractor_email,
        company_signer_id=company_signer_id,
        days=days,
        now=_now(),
        cc_user_ids=cc_user_ids,
    )
    await esign_docs.attach(db, request, prepared, qualified_ids)
    return request, token


async def _mail_link(
    db: AsyncSession,
    *,
    sender_id: int,
    request: EsignRequestOut,
    row: B2BGeneratedContract,
    url: str,
    request_key: Optional[str] = None,
    renewed: bool = False,
) -> tuple[bool, Optional[str]]:
    """Mail z linkiem ze skrzynki nadawcy — kontraktor zna ten adres.

    Awaria nie cofa wysyłki: okno pokazuje link do skopiowania."""
    subject, body = esign_mail.contractor_sign_message(
        number=row.contract_number,
        url=url,
        expires_at=request.expires_at,
        renewed=renewed,
        documents=[d.title for d in request.documents],
    )
    return await esign_mail.send_from(
        db,
        user_id=sender_id,
        to=request.contractor_email or "",
        subject=subject,
        body_html=body,
        candidate_id=row.candidate_id,
        request_key=request_key or f"b2b-esign-{request.id}",
        cc=await _cc_for_mail(db, row, [p.id for p in request.cc]),
    )


@router.get("/generated/{generated_id}/esign/defaults", response_model=EsignDefaultsOut)
async def esign_defaults(
    generated_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> EsignDefaultsOut:
    """Podpowiedzi okna „Wyślij do podpisu” — dla tego, kto może wysłać."""
    row = await db.get(B2BGeneratedContract, generated_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    await _assert_row_sender(db, current_user, row)
    email = (row.render_payload or {}).get("partner_email")
    if not email and row.candidate_id:
        candidate = await db.get(Candidate, row.candidate_id)
        email = candidate.email if candidate else None
    current = await esign_settings.load(db)
    names = await _names(db, list(current.company_signer_ids))
    connected = await esign_mail.mailbox_connected(db, current_user.id)
    return EsignDefaultsOut(
        contractor_name=row.partner_name,
        contractor_email=email if isinstance(email, str) else None,
        company_signers=[
            EsignPerson(id=uid, name=names[uid])
            for uid in current.company_signer_ids
            if uid in names
        ],
        mailbox_connected=connected,
        cc_candidates=await _cc_candidates(db, row, current_user),
        documents=[
            EsignDocumentOption(id=d.id, name=d.name)
            for d in await esign_docs.candidates(db, row)
        ],
    )


@router.get("/generated/{generated_id}/esign", response_model=Optional[EsignRequestOut])
async def get_row_esign(
    generated_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> Optional[EsignRequestOut]:
    """Ostatni wniosek o podpis tej umowy (albo ``null``)."""
    row = await db.get(B2BGeneratedContract, generated_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    await _assert_generator_client_access(db, current_user, row.client_id, write=False)
    request = await db.scalar(
        select(B2BSigningRequest)
        .where(B2BSigningRequest.generated_contract_id == generated_id)
        .order_by(B2BSigningRequest.id.desc())
        .limit(1)
    )
    if request is None:
        return None
    with_contact = request.company_signer_id == current_user.id or await _may_send(
        db, current_user, row
    )
    return await _out(db, request, with_contact=with_contact)


@router.post("/esign/{request_id}/withdraw", response_model=EsignRequestOut)
async def withdraw_esign(
    request_id: int,
    body: EsignWithdrawIn,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> EsignRequestOut:
    request = await db.get(B2BSigningRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Wniosek o podpis nie istnieje.")
    row = await db.get(B2BGeneratedContract, request.generated_contract_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    await _assert_row_sender(db, current_user, row)
    updated = await service.withdraw(
        db,
        request_id=request_id,
        actor_id=current_user.id,
        reason=body.reason,
        now=_now(),
    )
    await db.commit()
    return await _out(db, updated)


async def _row_of(db: AsyncSession, request_id: int) -> B2BGeneratedContract:
    request = await db.get(B2BSigningRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Wniosek o podpis nie istnieje.")
    row = await db.get(B2BGeneratedContract, request.generated_contract_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    return row


@router.post("/esign/{request_id}/extend", response_model=EsignRequestOut)
async def extend_esign(
    request_id: int,
    body: EsignRenewIn,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> EsignRequestOut:
    """„Przedłuż termin” — link z pierwszego maila działa dłużej, PDF ten sam.

    Jak wycofanie: działa także po wyłączeniu przełącznika."""
    row = await _row_of(db, request_id)
    await _assert_row_sender(db, current_user, row)
    updated = await service.extend(
        db,
        request_id=request_id,
        actor_id=current_user.id,
        days=body.days,
        now=_now(),
    )
    await db.commit()
    out = await _out(db, updated)
    subject, mail_body = esign_mail.contractor_extended_message(
        number=row.contract_number, expires_at=updated.expires_at
    )
    await esign_mail.send_from(
        db,
        user_id=current_user.id,
        to=updated.contractor_email or "",
        subject=subject,
        body_html=mail_body,
        candidate_id=row.candidate_id,
        request_key=f"b2b-esign-{request_id}-extended-{len(updated.events or [])}",
        cc=await _cc_for_mail(db, row, list(updated.cc_user_ids or [])),
    )
    return out


@router.post("/esign/{request_id}/relink", response_model=EsignSendOut)
async def relink_esign(
    request_id: int,
    body: EsignRenewIn,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> EsignSendOut:
    """„Wyślij nowy link” po terminie — ten sam zamrożony PDF (27.10.2026).

    Nowa wysyłka robi PDF o innych bajtach, więc plik podpisany przed terminem
    byłby odrzucony. Tu kontraktor wgrywa go bez ponownego podpisu."""
    current = await esign_settings.load(db)
    if not current.can_send(current_user):
        raise HTTPException(status_code=403, detail=MSG_OFF)
    row = await _row_of(db, request_id)
    await _assert_row_sender(db, current_user, row)
    updated, token = await service.relink(
        db,
        row_id=row.id,
        request_id=request_id,
        actor_id=current_user.id,
        days=body.days,
        signer_ids=current.company_signer_ids,
        now=_now(),
    )
    await db.commit()
    url = _sign_url(token)
    out = await _out(db, updated)
    mail_sent, problem = await _mail_link(
        db,
        sender_id=current_user.id,
        request=out,
        row=row,
        url=url,
        request_key=f"b2b-esign-{request_id}-relink-{len(updated.events or [])}",
        renewed=True,
    )
    return EsignSendOut(
        request=out, sign_url=url, mail_sent=mail_sent, mail_problem=problem
    )


@router.post("/esign/{request_id}/take-over", response_model=EsignRequestOut)
async def take_over_esign(
    request_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> EsignRequestOut:
    """„Przejmij obsługę” (zastępstwo, 27.10.2026). Bez nowego uprawnienia:
    przejmuje ten, kto mógłby wysłać tę umowę (``_assert_row_sender``)."""
    row = await _row_of(db, request_id)
    await _assert_row_sender(db, current_user, row)
    # Bez skrzynki dalsze maile obiegu przepadłyby bez śladu (przegląd kodu
    # 27.10.2026): przypomnienia, mail do reprezentanta i kopia kontraktora.
    if not await esign_mail.mailbox_connected(db, current_user.id):
        raise HTTPException(status_code=409, detail=MSG_TAKE_OVER_MAILBOX)
    updated, previous = await service.take_over(
        db, request_id=request_id, actor_id=current_user.id, now=_now()
    )
    await db.commit()
    out = await _out(db, updated)
    if previous and previous != current_user.id:
        await _notify(
            db,
            user_id=previous,
            title=f"{current_user.name} obsługuje teraz umowę {row.contract_number}",
            message=(
                "Przypomnienia, mail do podpisu za B2Bnetwork i kopia umowy pójdą "
                "z tamtej skrzynki, a dzwonki o tej wysyłce do tej osoby."
            ),
            ntype=NotificationType.signature_sent,
            request_id=request_id,
        )
    return out


# ── Podpis za B2B Network ───────────────────────────────────────────────────


@router.get("/esign/mine", response_model=list[EsignRequestOut])
async def my_company_signatures(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> list[EsignRequestOut]:
    """Umowy podpisane przez kontraktora, które czekają na mój podpis za firmę."""
    rows = (
        await db.scalars(
            select(B2BSigningRequest)
            .where(
                B2BSigningRequest.company_signer_id == current_user.id,
                B2BSigningRequest.status == "contractor_signed",
            )
            .order_by(B2BSigningRequest.contractor_signed_at)
        )
    ).all()
    contracts: dict[int, Any] = {}
    if rows:
        result = await db.execute(
            select(
                B2BGeneratedContract.id,
                B2BGeneratedContract.contract_number,
                B2BGeneratedContract.client_name,
            ).where(
                B2BGeneratedContract.id.in_([r.generated_contract_id for r in rows])
            )
        )
        contracts = {row.id: row for row in result.all()}
    out = []
    for r in rows:
        item = await _out(db, r)
        contract = contracts.get(r.generated_contract_id)
        if contract is not None:
            item.contract_number = contract.contract_number
            item.client_name = contract.client_name
        out.append(item)
    return out


@router.get("/esign/{request_id}/pdf")
async def company_signer_pdf(
    request_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Plik do podpisu za firmę — wersja podpisana przez kontraktora."""
    current = await esign_settings.load(db)
    request = await service.company_precheck(
        db,
        request_id=request_id,
        actor_id=current_user.id,
        signer_ids=current.company_signer_ids,
    )
    data = storage_service.read_b2b_signing_pdf(request.contractor_pdf_path or "")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": await _pdf_disposition(
                db, request, "podpisana przez kontraktora"
            ),
            "Cache-Control": "no-store",
        },
    )


@router.post("/esign/{request_id}/company-sign", response_model=EsignRequestOut)
async def company_sign(
    request_id: int,
    current_user: B2BGeneratorAccess,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> EsignRequestOut:
    current = await esign_settings.load(db)
    request = await service.company_precheck(
        db,
        request_id=request_id,
        actor_id=current_user.id,
        signer_ids=current.company_signer_ids,
    )
    # Wgrywa osoba wskazana przy wysyłce, a podpisać za firmę może każdy
    # reprezentant z listy (Artur 26.10.2026: Olaf wgrywa podpis Artura).
    names = await _names(db, list(current.company_signer_ids))
    representative_names = [
        names[uid] for uid in current.company_signer_ids if names.get(uid)
    ] or [current_user.name]
    data = await _upload_bytes(file)
    updated = await service.company_submit(
        db,
        request=request,
        representative_names=representative_names,
        data=data,
        validator=_validator(),
        now=_now(),
    )
    await db.commit()
    # Same identyfikatory: automatyka po podpisie przy odmowie robi rollback,
    # który wygasza obiekty sesji (odczyt pola w async = MissingGreenlet).
    updated_id = updated.id
    await _after_both_signed(db, updated_id, current_user)
    return await _out(db, await _fresh(db, updated_id))


@router.get("/esign/{request_id}/signed-pdf")
async def signed_pdf(
    request_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Umowa podpisana przez obie strony — dla nadawcy i reprezentanta (np. gdy
    automatyka nie założyła kontraktu i trzeba oznaczyć podpis ręcznie)."""
    request = await db.get(B2BSigningRequest, request_id)
    if request is None or request.status != "completed" or not request.final_pdf_path:
        raise HTTPException(status_code=404, detail="Wniosek o podpis nie istnieje.")
    if request.company_signer_id != current_user.id:
        row = await db.get(B2BGeneratedContract, request.generated_contract_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
        await _assert_row_sender(db, current_user, row)
    data = storage_service.read_b2b_signing_pdf(request.final_pdf_path)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": await _pdf_disposition(db, request, "podpisana"),
            "Cache-Control": "no-store",
        },
    )


# ── Po podpisie (PR 5) ──────────────────────────────────────────────────────

_REGISTER_LINK = "/contracts/b2b-generator?tab=generated"


async def _notify(
    db: AsyncSession,
    *,
    user_id: int | None,
    title: str,
    message: str,
    ntype: NotificationType,
    request_id: int,
) -> None:
    """Dzwonek bez kwot; jego awaria nie cofa podpisu."""
    if not user_id:
        return
    try:
        await emit_notification(
            db,
            user_id=user_id,
            title=title,
            message=message,
            ntype=ntype,
            related_entity_type="b2b_signing_request",
            related_entity_id=request_id,
            link=_REGISTER_LINK,
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("[b2b_esign] dzwonek nie wyszedł request=%d", request_id)
        await db.rollback()


async def _notify_many(
    db: AsyncSession,
    *,
    user_ids: list[int],
    title: str,
    message: str,
    ntype: NotificationType,
    request_id: int,
) -> None:
    """Ten sam dzwonek dla nadawcy i osób w DW."""
    for user_id in user_ids:
        await _notify(
            db,
            user_id=user_id,
            title=title,
            message=message,
            ntype=ntype,
            request_id=request_id,
        )


async def _after_contractor_signed(db: AsyncSession, request_id: int) -> None:
    request = await db.get(B2BSigningRequest, request_id)
    if request is None:
        return
    row = await db.get(B2BGeneratedContract, request.generated_contract_id)
    number = row.contract_number if row else ""
    company_signer = await service.active_company_signer(db, request)
    if company_signer is None:
        # Konto reprezentanta wyłączone: bez maila na jego adres, dzwonek do
        # osób wysyłki — inaczej umowa czekałaby na podpis, o którym nikt nie wie.
        await _notify_many(
            db,
            user_ids=await service.bell_recipients(db, request, business_today()),
            title=f"Umowa {number} czeka na podpis B2Bnetwork",
            message=service.company_signer_missing_message(
                request.contractor_name, number
            ),
            # Własny typ: dzienny dedup (osoba + typ + wniosek) zjadałby ten
            # dzwonek razem z „czeka na podpis kontraktora” z tego samego dnia.
            ntype=service.COMPANY_SIGNER_MISSING_TYPE,
            request_id=request_id,
        )
        return
    await _notify(
        db,
        user_id=company_signer.id,
        title=f"Umowa {number} czeka na Twój podpis",
        message=(
            f"{request.contractor_name} podpisał(a) umowę {number} podpisem "
            "kwalifikowanym. Podpisz ją za B2Bnetwork."
        ),
        ntype=NotificationType.signature_sent,
        request_id=request_id,
    )
    # Sam dzwonek nie wystarczał (Olaf 26.10.2026) — mail ze skrzynki nadawcy.
    if company_signer.email:
        subject, body = esign_mail.company_signer_message(
            number=number,
            contractor_name=request.contractor_name,
            since=request.contractor_signed_at or _now(),
            reminder=False,
        )
        await esign_mail.send_from(
            db,
            # Ze skrzynki obsługującego (po „Przejmij obsługę” — zastępcy).
            user_id=service.handler_id(request),
            to=company_signer.email,
            subject=subject,
            body_html=body,
            candidate_id=row.candidate_id if row else None,
            request_key=f"b2b-esign-{request_id}-company",
        )


async def _send_contractor_copy(db: AsyncSession, request_id: int) -> None:
    """Mail do kontraktora z umową podpisaną przez obie strony (26.10.2026).

    Wcześniej kopia nie wychodziła wcale, a link po podpisie firmy gasł.
    Awaria wysyłki nie cofa podpisu: kopia zostaje do pobrania z linku."""
    # ``populate_existing``: automatyka po podpisie bywa zakończona rollbackiem,
    # który wygasza obiekty sesji (odczyt pola w async = MissingGreenlet).
    request = await db.get(B2BSigningRequest, request_id, populate_existing=True)
    if request is None or not request.final_pdf_path or not request.contractor_email:
        return
    row = await db.get(
        B2BGeneratedContract, request.generated_contract_id, populate_existing=True
    )
    number = row.contract_number if row else ""
    try:
        data = storage_service.read_b2b_signing_pdf(request.final_pdf_path)
    except Exception:  # noqa: BLE001
        logger.exception("[b2b_esign] brak pliku kopii request=%d", request_id)
        return
    subject, body = esign_mail.contractor_copy_message(number=number)
    await esign_mail.send_from(
        db,
        user_id=service.handler_id(request),
        to=request.contractor_email,
        subject=subject,
        body_html=body,
        candidate_id=row.candidate_id if row else None,
        request_key=f"b2b-esign-{request_id}-copy",
        cc=(
            await _cc_for_mail(db, row, list(request.cc_user_ids or [])) if row else []
        ),
        attachments=[
            m365_sender.FileAttachment(
                name=contract_file_name(
                    number,
                    row.partner_name
                    if row and row.partner_name
                    else request.contractor_name,
                    ext="pdf",
                    suffix="podpisana",
                ),
                content_type="application/pdf",
                data=data,
            )
        ],
    )


async def _after_both_signed(db: AsyncSession, request_id: int, signer: User) -> None:
    """Ta sama automatyka co „Oznacz jako podpisaną” + plik w Dokumentach.

    Woła trasę potwierdzenia w imieniu reprezentanta — z tymi samymi bramkami
    (uprawnienie „Oznaczanie podpisu”, zakres klienta, różnice warunków).
    Odmowa nie cofa podpisu: nadawca dostaje dzwonek, żeby oznaczyć umowę
    ręcznie i dołączyć plik (``signed-pdf``)."""
    # Same identyfikatory: trasa potwierdzenia przy odmowie robi ``rollback``,
    # który wygasza obiekty sesji, także ``signer``.
    signer_id = signer.id
    request = await db.get(B2BSigningRequest, request_id)
    if request is None or request.status != "completed":
        return
    row_id = request.generated_contract_id
    # Dzwonek o podpisie obu stron: nadawca i osoby w DW (27.10.2026).
    watcher_ids = await service.bell_recipients(db, request, business_today())
    final_path = request.final_pdf_path
    row = await db.get(B2BGeneratedContract, row_id)
    number = row.contract_number if row else ""
    reason: str | None = None
    try:
        # Paczka (0687): dzień podpisu umowy, nie ostatniego dokumentu.
        contractor_signed_at = service.contract_signed_at(request)
        await confirm_generated_contract_fully_signed(
            generated_id=row_id,
            payload=B2BConfirmFullySignedRequest(),
            current_user=signer,
            db=db,
            # Dzień podpisu = dzień podpisu kontraktora (Warszawa), nie dzień,
            # w którym umowę podpisał reprezentant firmy; źródło `esign` (0654).
            evidence_for=lambda _row: SignedOnEvidence(
                source="esign",
                signed_on=(
                    business_date(contractor_signed_at)
                    if contractor_signed_at
                    else None
                ),
                consultant_signed_at=contractor_signed_at,
            ),
        )
    except HTTPException as exc:
        detail = exc.detail
        reason = (
            detail
            if isinstance(detail, str)
            else "brak uprawnienia albo różnice warunków"
        )
        await db.rollback()
    except Exception:  # noqa: BLE001 — podpis jest zapisany; człowiek dokończy
        logger.exception("[b2b_esign] automatyka po podpisie padła row=%d", row_id)
        reason = "błąd automatyki (szczegóły w logu serwera)."
        await db.rollback()
    if reason is None and final_path:
        try:
            # Kontrakty osoby PRZED wierszem rejestru (audyt 22.10.2026, F47).
            await _lock_person_contracts_before_row(db, row_id)
            locked = await db.scalar(
                select(B2BGeneratedContract)
                .where(B2BGeneratedContract.id == row_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            replaced = await signed_file.attach(
                db,
                row=locked,
                filename=contract_file_name(
                    number,
                    locked.partner_name if locked else None,
                    ext="pdf",
                    suffix="podpisana",
                ),
                content_type="application/pdf",
                data=storage_service.read_b2b_signing_pdf(final_path),
                actor_id=signer_id,
            )
            locked.signature_source = "validated_upload"
            await db.commit()
            signed_file.discard(replaced)
        except Exception:  # noqa: BLE001 — kontrakt jest; plik da się dołączyć ręcznie
            logger.exception("[b2b_esign] plik nie trafił do Dokumentów row=%d", row_id)
            await db.rollback()
    if reason is None:
        await _notify_many(
            db,
            user_ids=watcher_ids,
            title=f"Umowa {number} podpisana przez obie strony",
            message=(
                "Kontrakt i szkic zamówienia założone, kandydat na „Zatrudniony”, "
                "podpisany plik w Dokumentach kontraktu."
            ),
            ntype=NotificationType.signature_signed,
            request_id=request_id,
        )
    else:
        await _notify_many(
            db,
            user_ids=watcher_ids,
            title=f"Umowa {number} podpisana — oznacz ją w rejestrze",
            message=(
                "Obie strony podpisały umowę w NEXUSIE, ale kontrakt nie powstał "
                f"automatycznie: {reason} Oznacz umowę jako podpisaną i dołącz "
                "podpisany plik."
            )[:1000],
            ntype=NotificationType.signature_signed,
            request_id=request_id,
        )
    # Kopia dla kontraktora niezależnie od tego, czy kontrakt powstał sam.
    await _send_contractor_copy(db, request_id)


# ── Kontraktor (publicznie, link z maila) ───────────────────────────────────


def _public_status(request: B2BSigningRequest, now: datetime) -> str:
    if request.status == "contractor_signed":
        return "signed_by_you"
    if request.status == "completed":
        return "completed"
    if service.is_expired(request, now):
        return "expired"
    return "waiting" if service.is_link_live(request, now) else "closed"


async def _public_view(db: AsyncSession, request: B2BSigningRequest) -> PublicSignView:
    row = await db.get(B2BGeneratedContract, request.generated_contract_id)
    now = _now()
    status = _public_status(request, now)
    if status == "expired" and not await service.renewable(db, request, now):
        # Umowę anulowano, poprawiono albo wysłano od nowa — stary link nie
        # obiecuje, że podpisany plik przejdzie.
        status = "closed"
    copy_until = service.signed_copy_until(request)
    documents = await esign_docs.for_request(db, request.id)
    can_accept = status == "waiting" and any(
        d.requirement == "any" and not d.signed_pdf_path for d in documents
    )
    # E1: umowa wchodzi do podpisu u dostawcy zawsze, więc po wgraniu umowy
    # z dysku reszta paczki idzie dotychczasową drogą.
    provider = remote.availability()
    return PublicSignView(
        contract_number=row.contract_number if row else "",
        contractor_name=request.contractor_name,
        status=status,
        expires_at=(request.expires_at if status in ("waiting", "expired") else None),
        renewal_requested_at=(
            service.renewal_requested_at(request) if status == "expired" else None
        ),
        signed_pdf_until=copy_until if copy_until and copy_until > now else None,
        contract_signed=bool(request.contractor_pdf_path),
        documents=[
            PublicSignDocument(
                id=d.id,
                title=d.title,
                signed=bool(d.signed_pdf_path),
                requirement="any" if d.requirement == "any" else "qualified",
                signed_via=(
                    d.signed_via
                    if d.signed_via in ("qualified", "email_code")
                    else None
                ),
            )
            for d in documents
        ],
        accept_code_email=(
            accept_code.mask_email(request.contractor_email) if can_accept else None
        ),
        accept_code_sent_at=request.accept_code_sent_at if can_accept else None,
        remote_signing=RemoteSigningOut(
            available=(
                provider.available
                and status == "waiting"
                and not request.contractor_pdf_path
            ),
            provider_label=provider.provider_label,
        ),
    )


@public_router.get("/b2b-sign/{token}", response_model=PublicSignView)
@limiter.limit("30/minute")
async def public_sign_view(
    token: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
) -> PublicSignView:
    """Strona kontraktora: numer umowy, imię i nazwisko, stan — bez kwot."""
    signing = await service.load_by_token(db, token)
    return await _public_view(db, signing)


@public_router.get("/b2b-sign/{token}/pdf")
@limiter.limit("30/minute")
async def public_sign_pdf(
    token: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
) -> Response:
    """PDF do podpisu — tylko dopóki link czeka na podpis kontraktora."""
    signing = await service.load_by_token(db, token)
    if not service.is_link_live(signing, _now()):
        raise HTTPException(status_code=410, detail=service.MSG_CLOSED)
    data = storage_service.read_b2b_signing_pdf(signing.source_pdf_path)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": await _pdf_disposition(db, signing),
            "Cache-Control": "no-store",
        },
    )


@public_router.get("/b2b-sign/{token}/signed-pdf")
@limiter.limit("30/minute")
async def public_signed_copy(
    token: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Kopia kontraktora: umowa podpisana przez obie strony, przez 30 dni."""
    signing = await service.load_by_token(db, token)
    until = service.signed_copy_until(signing)
    if until is None or until <= _now():
        raise HTTPException(status_code=410, detail=service.MSG_CLOSED)
    data = storage_service.read_b2b_signing_pdf(signing.final_pdf_path or "")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": await _pdf_disposition(db, signing, "podpisana"),
            "Cache-Control": "no-store",
        },
    )


@public_router.post("/b2b-sign/{token}", response_model=PublicSignView)
@limiter.limit("5/minute;30/hour")
async def public_sign_submit(
    token: str,
    request: Request,  # wymagane przez slowapi
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> PublicSignView:
    # Najpierw link i stan, dopiero potem plik (fałszywy link nie zmusza
    # serwera do przyjęcia 20 MB).
    now = _now()
    signing = await service.contractor_precheck(db, token, now)
    data = await _upload_bytes(file)
    signing = await service.contractor_submit(
        db, request=signing, data=data, validator=_validator(), now=now
    )
    finished = signing.status == "contractor_signed"
    await db.commit()
    signing_id = signing.id
    await _after_contractor_files(db, signing_id, [], finished=finished, now=now)
    return await _public_view(db, await _fresh(db, signing_id))


@public_router.get("/b2b-sign/{token}/documents/{document_id}/pdf")
@limiter.limit("30/minute")
async def public_document_pdf(
    token: str,
    document_id: int,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
) -> Response:
    """PDF dokumentu z paczki (0687) — dopóki link czeka na podpis kontraktora."""
    signing = await service.load_by_token(db, token)
    if not service.is_link_live(signing, _now()):
        raise HTTPException(status_code=410, detail=service.MSG_CLOSED)
    item = await esign_docs.get_in_request(db, signing.id, document_id)
    data = storage_service.read_b2b_signing_pdf(item.source_pdf_path)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(
                f"{item.title}.pdf", "attachment"
            ),
            "Cache-Control": "no-store",
        },
    )


@public_router.post(
    "/b2b-sign/{token}/documents/{document_id}", response_model=PublicSignView
)
@limiter.limit("10/minute;60/hour")
async def public_document_submit(
    token: str,
    document_id: int,
    request: Request,  # wymagane przez slowapi
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> PublicSignView:
    """Podpisany dokument z paczki. Ostatni podpisany plik (umowa albo
    dokument) przekazuje umowę reprezentantowi B2B Network."""
    now = _now()
    signing = await service.contractor_precheck(db, token, now, for_contract=False)
    data = await _upload_bytes(file)
    signing, item = await esign_docs.contractor_submit(
        db,
        request=signing,
        document_id=document_id,
        data=data,
        validator=_validator(),
        now=now,
    )
    finished = signing.status == "contractor_signed"
    await db.commit()
    signing_id = signing.id
    await _after_contractor_files(
        db, signing_id, [(item.id, data)], finished=finished, now=now
    )
    return await _public_view(db, await _fresh(db, signing_id))


async def _after_contractor_files(
    db: AsyncSession,
    request_id: int,
    delivered: list[tuple[int, bytes]],
    *,
    finished: bool,
    now: datetime,
) -> None:
    """Po zapisie plików kontraktora (wgranie, kod z maila, podpis u dostawcy):
    dokumenty do „Dokumentów do startu” pary, a po ostatnim pliku dzwonek
    i mail do reprezentanta B2Bnetwork. Wołać po commicie."""
    for item_id, data in delivered:
        await _deliver_to_start_documents(db, request_id, item_id, data, now)
    if finished:
        await _after_contractor_signed(db, request_id)


async def _deliver_to_start_documents(
    db: AsyncSession, request_id: int, item_id: int, data: bytes, now: datetime
) -> None:
    """Podpisany dokument w „Dokumentach do startu” pary. Awaria nie cofa
    podpisu: plik zostaje przy wniosku, a DL dostanie go od rekrutera jak dotąd."""
    new_path: Optional[str] = None
    try:
        request = await db.get(B2BSigningRequest, request_id)
        item = await db.get(B2BSigningDocument, item_id)
        row = (
            await db.get(B2BGeneratedContract, request.generated_contract_id)
            if request
            else None
        )
        if row is None or item is None:
            return
        new_path, previous = await esign_docs.deliver_to_pair(
            db, row=row, item=item, data=data, now=now
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — podpis jest zapisany
        logger.exception(
            "[b2b_esign] dokument nie trafił do Dokumentów do startu item=%d", item_id
        )
        await db.rollback()
        if new_path:
            storage_service.delete_start_document_file(new_path)
        return
    if previous:
        storage_service.delete_start_document_file(previous)


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


@public_router.post("/b2b-sign/{token}/accept-code", response_model=PublicSignView)
@limiter.limit("3/minute;10/hour")
async def public_accept_code(
    token: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
) -> PublicSignView:
    """Kod do akceptacji dokumentów bez wymogu kwalifikowanego (0754).

    Mail idzie ze skrzynki osoby, która obsługuje wysyłkę, na adres z wysyłki
    (jak link). Bez skrzynki kod nie wychodzi: 503 z podpowiedzią."""
    now = _now()
    signing = await service.contractor_precheck(db, token, now, for_contract=False)
    locked, code = await accept_code.issue(db, request=signing, now=now)
    await db.commit()
    signing_id = locked.id
    row = await db.get(B2BGeneratedContract, locked.generated_contract_id)
    subject, body = esign_mail.contractor_accept_code_message(
        number=row.contract_number if row else "",
        code=code,
        valid_minutes=accept_code.CODE_VALID_MINUTES,
    )
    sent, _problem = await esign_mail.send_from(
        db,
        user_id=service.handler_id(locked),
        to=locked.contractor_email or "",
        subject=subject,
        body_html=body,
        candidate_id=row.candidate_id if row else None,
        request_key=f"b2b-esign-{signing_id}-code-{int(now.timestamp())}",
    )
    if not sent:
        fresh = await service.lock_request(db, signing_id)
        accept_code.withdraw_code(fresh)
        await db.commit()
        raise HTTPException(status_code=503, detail=accept_code.MSG_MAIL_FAILED)
    return await _public_view(db, await _fresh(db, signing_id))


@public_router.post("/b2b-sign/{token}/accept", response_model=PublicSignView)
@limiter.limit("10/minute;30/hour")
async def public_accept(
    token: str,
    body: PublicAcceptIn,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
) -> PublicSignView:
    """Akceptacja dokumentów kodem z maila (0754). Zaakceptowany dokument trafia
    do „Dokumentów do startu” jak podpisany; ostatni brakujący plik przekazuje
    umowę reprezentantowi B2Bnetwork."""
    now = _now()
    signing = await service.contractor_precheck(db, token, now, for_contract=False)
    signing, items = await accept_code.accept(
        db,
        request=signing,
        code=body.code,
        document_ids=body.document_ids,
        evidence=accept_code.Evidence(
            ip=_client_ip(request), user_agent=request.headers.get("user-agent")
        ),
        now=now,
    )
    finished = signing.status == "contractor_signed"
    await db.commit()
    signing_id = signing.id
    delivered = [
        (i.id, storage_service.read_b2b_signing_pdf(i.signed_pdf_path or ""))
        for i in items
    ]
    await _after_contractor_files(db, signing_id, delivered, finished=finished, now=now)
    return await _public_view(db, await _fresh(db, signing_id))


@public_router.post("/b2b-sign/{token}/renewal", response_model=PublicSignView)
@limiter.limit("5/minute;20/hour")
async def public_request_renewal(
    token: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
) -> PublicSignView:
    """„Poproś o nowy link” z wygasłego linku (27.10.2026) — dzwonek do osoby,
    która wysłała umowę; kolejne kliknięcia w ciągu doby nic nie dodają."""
    signing, fresh = await service.request_renewal(db, token=token, now=_now())
    await db.commit()
    signing_id = signing.id
    if fresh:
        row = await db.get(B2BGeneratedContract, signing.generated_contract_id)
        number = row.contract_number if row else ""
        await _notify_many(
            db,
            user_ids=await service.bell_recipients(db, signing, business_today()),
            title=f"Kontraktor prosi o nowy link do umowy {number}",
            message=(
                f"{signing.contractor_name}: link wygasł. „Wyślij nowy link” "
                "w rejestrze wyśle ten sam PDF."
            ),
            ntype=NotificationType.signature_renewal_requested,
            request_id=signing_id,
        )
    return await _public_view(db, await _fresh(db, signing_id))


# ── Podpis u dostawcy przez API CSC (E1, kierunek K1 z 22.11.2026) ──────────
#
# Kontraktor (link z maila) albo reprezentant B2Bnetwork zatwierdza u dostawcy
# usług zaufania RAZ, a NEXUS podpisuje skróty wszystkich plików i przepuszcza
# każdy podpisany plik przez te same bramki co wgranie z dysku
# (``service.validate_upload`` + ``store_*``, potem te same dzwonki, maile
# i „Dokumenty do startu”). Za konfiguracją ``B2B_ESIGN_CSC_*`` — pusta = 404.


def _contractor_callback_url() -> str:
    base = app_config.PUBLIC_API_BASE_URL.rstrip("/")
    return f"{base}/api/public/b2b-sign/remote/callback"


def _company_callback_url() -> str:
    base = app_config.PUBLIC_API_BASE_URL.rstrip("/")
    return f"{base}/api/b2b-generator/esign/company-remote/callback"


def _front_url(path: str) -> str:
    return f"{app_config.PUBLIC_BASE_URL.rstrip('/')}{path}"


def _remote_message(exc: HTTPException) -> str:
    detail = exc.detail
    return detail if isinstance(detail, str) else remote.MSG_FAILED


def _remote_field(party: str, public_id: str) -> str:
    """Nazwa pola podpisu: własna dla sesji, więc nie trafi na pole, które
    plik już ma (np. podpis kontraktora z innego narzędzia)."""
    return f"NEXUS_{party}_{public_id[:8]}"


async def _remote_failed(db: AsyncSession, session_id: int, message: str) -> None:
    await db.rollback()
    await remote.mark(db, session_id, status="failed", message=message, now=_now())
    await db.commit()


async def _sign_contractor_remote(
    db: AsyncSession, session_id: int, code: str
) -> Optional[tuple[int, list[tuple[int, bytes]], bool, datetime]]:
    """Podpis u dostawcy i przyjęcie plików kontraktora, wszystko albo nic.

    Zwraca (wniosek, dokumenty do „Dokumentów do startu”, czy umowa idzie do
    firmy, chwila) albo ``None``, gdy sesja skończyła się bez podpisu."""
    now = _now()
    session = await db.get(B2BEsignRemoteSession, session_id)
    if session is None or session.status != "signing":
        return None
    [request_id] = session.request_ids
    document_ids = list(session.document_ids or [])
    verifier, method, public_id = (
        session.code_verifier,
        session.method,
        session.public_id,
    )
    try:
        request = await _fresh(db, request_id)
        service.check_contractor_open(request, now)
        row_id = request.generated_contract_id
        name = request.contractor_name
        contract = Fingerprint(request.source_sha256, request.source_size)
        contract_bytes = storage_service.read_b2b_signing_pdf(request.source_pdf_path)
        docs = []
        for document_id in document_ids:
            item = await esign_docs.signable_document(db, request_id, document_id)
            docs.append(
                (
                    item.id,
                    item.requirement,
                    Fingerprint(item.source_sha256, item.source_size),
                    storage_service.read_b2b_signing_pdf(item.source_pdf_path),
                )
            )
        row = await db.get(B2BGeneratedContract, row_id)
        number = row.contract_number if row else ""
        field = _remote_field("kontraktor", public_id)
        signed = await remote.sign(
            code=code,
            code_verifier=verifier,
            redirect_uri=_contractor_callback_url(),
            files=[(field, contract_bytes), *[(field, d[3]) for d in docs]],
            names=[name],
            method=method,
            description=(
                f"NEXUS: umowa B2B nr {number}"
                + (f" i dokumenty do startu ({len(docs)})" if docs else "")
            ),
        )
        # Ta sama droga co wgranie z dysku. Nieudana walidacja nie zużywa
        # prób linku: pliku nie przygotował kontraktor, tylko dostawca.
        validator = _validator()
        contract_report = await service.validate_upload(
            db,
            request_id=request_id,
            data=signed.files[0],
            previous=contract,
            validator=validator,
            required_signers=[name],
            count_failures=False,
        )
        doc_reports = []
        for (_doc_id, requirement, source, _data), data in zip(docs, signed.files[1:]):
            doc_reports.append(
                await service.validate_upload(
                    db,
                    request_id=request_id,
                    data=data,
                    previous=source,
                    validator=validator,
                    required_signers=[name],
                    count_failures=False,
                    not_qualified_message=(
                        esign_docs.MSG_ANY_NOT_QUALIFIED
                        if requirement == "any"
                        else None
                    ),
                )
            )
        locked = await service.store_contract(
            db,
            request_id=request_id,
            row_id=row_id,
            source_sha256=contract.sha256,
            data=signed.files[0],
            report=contract_report,
            now=now,
        )
        delivered: list[tuple[int, bytes]] = []
        for (doc_id, _requirement, source, _data), data, report in zip(
            docs, signed.files[1:], doc_reports
        ):
            locked, _item = await esign_docs.store_document(
                db,
                request_id=request_id,
                row_id=row_id,
                document_id=doc_id,
                source_sha256=source.sha256,
                data=data,
                report=report,
                now=now,
            )
            delivered.append((doc_id, data))
        finished = locked.status == "contractor_signed"
        await remote.mark(
            db,
            session_id,
            status="done",
            message=None,
            now=now,
            done_request_ids=[request_id],
            evidence=signed.evidence,
        )
        await db.commit()
    except HTTPException as exc:
        await _remote_failed(db, session_id, _remote_message(exc))
        return None
    except csc.CscError as exc:
        await _remote_failed(db, session_id, exc.message)
        return None
    return request_id, delivered, finished, now


async def _run_contractor_remote(session_id: int, code: str) -> None:
    """Zadanie po powrocie od dostawcy (``BackgroundTasks``): przeglądarka
    dostaje przekierowanie od razu i pyta o stan sesji."""
    async with AsyncSessionLocal() as db:
        try:
            outcome = await _sign_contractor_remote(db, session_id, code)
        except Exception:  # noqa: BLE001 — sesja nie może zostać „w podpisie”
            logger.exception(
                "[b2b_esign] podpis u dostawcy padł session=%d", session_id
            )
            await _remote_failed(db, session_id, remote.MSG_FAILED)
            return
        if outcome is not None:
            request_id, delivered, finished, now = outcome
            await _after_contractor_files(
                db, request_id, delivered, finished=finished, now=now
            )


async def _sign_company_remote(
    db: AsyncSession, session_id: int, code: str
) -> Optional[tuple[int, list[int]]]:
    """Podpis za B2Bnetwork kilku umów jednym zatwierdzeniem. Każda umowa
    przechodzi bramki ``company_submit`` osobno: zła jedna nie cofa reszty.
    Zwraca (reprezentant, przyjęte wnioski) albo ``None``."""
    now = _now()
    session = await db.get(B2BEsignRemoteSession, session_id)
    if session is None or session.status != "signing" or session.user_id is None:
        return None
    request_ids = list(session.request_ids or [])
    user_id = session.user_id
    verifier, public_id = session.code_verifier, session.public_id
    current = await esign_settings.load(db)
    names = await _names(db, [*current.company_signer_ids, user_id])
    representative_names = [
        names[uid] for uid in current.company_signer_ids if names.get(uid)
    ] or [names.get(user_id) or ""]
    pending = []
    problems: list[str] = []
    for request_id in request_ids:
        try:
            request = await service.company_precheck(
                db,
                request_id=request_id,
                actor_id=user_id,
                signer_ids=current.company_signer_ids,
            )
        except HTTPException as exc:
            problems.append(_remote_message(exc))
            continue
        row = await db.get(B2BGeneratedContract, request.generated_contract_id)
        pending.append(
            (
                request.id,
                request.generated_contract_id,
                request.contractor_name,
                Fingerprint(
                    request.contractor_sha256 or "", request.contractor_size or 0
                ),
                storage_service.read_b2b_signing_pdf(request.contractor_pdf_path or ""),
                row.contract_number if row else "",
            )
        )
    if not pending:
        await _remote_failed(
            db, session_id, problems[0] if problems else remote.MSG_FAILED
        )
        return None
    field = _remote_field("B2Bnetwork", public_id)
    try:
        signed = await remote.sign(
            code=code,
            code_verifier=verifier,
            redirect_uri=_company_callback_url(),
            files=[(field, p[4]) for p in pending],
            names=representative_names,
            method=None,
            description=(
                "NEXUS: podpis za B2Bnetwork, umowy " + ", ".join(p[5] for p in pending)
            ),
        )
    except csc.CscError as exc:
        await _remote_failed(db, session_id, exc.message)
        return None
    validator = _validator()
    done: list[int] = []
    for (request_id, row_id, name, previous, _data, number), data in zip(
        pending, signed.files
    ):
        try:
            report = await service.validate_upload(
                db,
                request_id=request_id,
                data=data,
                previous=previous,
                validator=validator,
                required_signers=[name],
                any_of_signers=representative_names,
                count_failures=False,
            )
            final = await service.company_long_term(
                data,
                previous=previous,
                validator=validator,
                required_signers=[name],
                any_of_signers=representative_names,
            )
            await service.store_company(
                db,
                request_id=request_id,
                row_id=row_id,
                contractor_sha256=previous.sha256,
                data=data,
                report=report,
                now=now,
                final=final,
            )
            await db.commit()
            done.append(request_id)
        except HTTPException as exc:
            await db.rollback()
            problems.append(f"Umowa {number}: {_remote_message(exc)}")
    await remote.mark(
        db,
        session_id,
        status="done" if done else "failed",
        message="\n".join(problems) or None,
        now=now,
        done_request_ids=done,
        evidence=signed.evidence,
    )
    await db.commit()
    return user_id, done


async def _run_company_remote(session_id: int, code: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            outcome = await _sign_company_remote(db, session_id, code)
        except Exception:  # noqa: BLE001 — sesja nie może zostać „w podpisie”
            logger.exception(
                "[b2b_esign] podpis firmy u dostawcy padł session=%d", session_id
            )
            await _remote_failed(db, session_id, remote.MSG_FAILED)
            return
        if outcome is None:
            return
        user_id, done = outcome
        for request_id in done:
            # Świeży obiekt: automatyka po podpisie przy odmowie robi rollback.
            signer = await db.get(User, user_id, populate_existing=True)
            if signer is None:
                return
            await _after_both_signed(db, request_id, signer)


@public_router.post("/b2b-sign/{token}/remote/start", response_model=RemoteStartOut)
@limiter.limit("5/minute;20/hour")
async def public_remote_start(
    token: str,
    body: RemoteStartIn,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
) -> RemoteStartOut:
    """Podpis u dostawcy: umowa (zawsze) i wybrane dokumenty paczki jednym
    zatwierdzeniem. Wniosek zmienia się dopiero po powrocie od dostawcy."""
    remote.require_config()
    now = _now()
    signing = await service.contractor_precheck(db, token, now)
    document_ids = list(dict.fromkeys(body.include_document_ids))
    for document_id in document_ids:
        await esign_docs.signable_document(db, signing.id, document_id)
    session, url = await remote.start(
        db,
        party="contractor",
        request_ids=[signing.id],
        document_ids=document_ids,
        method=body.method,
        token=token,
        redirect_uri=_contractor_callback_url(),
        now=now,
    )
    public_id = session.public_id
    await db.commit()
    return RemoteStartOut(redirect_url=url, session_id=public_id)


@public_router.get("/b2b-sign/remote/callback")
@limiter.limit("20/minute")
async def public_remote_callback(
    request: Request,  # wymagane przez slowapi
    background: BackgroundTasks,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Powrót od dostawcy. Podpis biegnie w tle, przeglądarka wraca na stronę
    kontraktora i pyta o stan sesji (``?remote=…``)."""
    remote.require_config()
    back = await remote.accept_callback(
        db, party="contractor", state=state, code=code, error=error, now=_now()
    )
    await db.commit()
    if back.proceed and code:
        background.add_task(_run_contractor_remote, back.session_id, code)
    return RedirectResponse(
        _front_url(f"/sign/b2b/{back.token}?remote={back.public_id}"),
        status_code=302,
    )


@public_router.get(
    "/b2b-sign/{token}/remote/{session_id}", response_model=PublicRemoteStatus
)
@limiter.limit("60/minute")
async def public_remote_status(
    token: str,
    session_id: str,
    request: Request,  # wymagane przez slowapi
    db: AsyncSession = Depends(get_db),
) -> PublicRemoteStatus:
    """Stan sesji podpisu u dostawcy; po końcu także świeży widok strony."""
    signing = await service.load_by_token(db, token)
    signing_id = signing.id
    session = await remote.load(
        db, session_id, party="contractor", request_id=signing_id, now=_now()
    )
    done = session.status not in remote.OPEN_STATES
    return PublicRemoteStatus(
        state=session.status,
        message=session.message,
        view=await _public_view(db, await _fresh(db, signing_id)) if done else None,
    )


@router.get("/esign/company-remote/available", response_model=RemoteSigningOut)
async def company_remote_available(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> RemoteSigningOut:
    """Czy ta osoba może podpisać za B2Bnetwork u dostawcy (E1)."""
    provider = remote.availability()
    current = await esign_settings.load(db)
    return RemoteSigningOut(
        available=provider.available and current_user.id in current.company_signer_ids,
        provider_label=provider.provider_label,
    )


@router.post("/esign/company-remote/start", response_model=RemoteStartOut)
async def company_remote_start(
    body: CompanyRemoteStartIn,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> RemoteStartOut:
    """Podpis za B2Bnetwork kilku umów jednym zatwierdzeniem u dostawcy. Każda
    musi czekać na podpis tej osoby (te same bramki co ``company-sign``)."""
    remote.require_config()
    current = await esign_settings.load(db)
    request_ids = list(dict.fromkeys(body.request_ids))
    for request_id in request_ids:
        await service.company_precheck(
            db,
            request_id=request_id,
            actor_id=current_user.id,
            signer_ids=current.company_signer_ids,
        )
    session, url = await remote.start(
        db,
        party="company",
        request_ids=request_ids,
        user_id=current_user.id,
        redirect_uri=_company_callback_url(),
        now=_now(),
    )
    public_id = session.public_id
    await db.commit()
    return RemoteStartOut(redirect_url=url, session_id=public_id)


@router.get("/esign/company-remote/callback")
async def company_remote_callback(
    current_user: B2BGeneratorAccess,
    background: BackgroundTasks,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Powrót od dostawcy do rejestru Generatora; sesja tylko tego konta."""
    remote.require_config()
    back = await remote.accept_callback(
        db,
        party="company",
        state=state,
        code=code,
        error=error,
        user_id=current_user.id,
        now=_now(),
    )
    await db.commit()
    if back.proceed and code:
        background.add_task(_run_company_remote, back.session_id, code)
    return RedirectResponse(
        _front_url(f"{_REGISTER_LINK}&remote={back.public_id}"), status_code=302
    )


@router.get("/esign/company-remote/{session_id}", response_model=CompanyRemoteStatus)
async def company_remote_status(
    session_id: str,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> CompanyRemoteStatus:
    session = await remote.load(
        db, session_id, party="company", user_id=current_user.id, now=_now()
    )
    return CompanyRemoteStatus(
        state=session.status,
        message=session.message,
        done_request_ids=list(session.done_request_ids or []),
    )
