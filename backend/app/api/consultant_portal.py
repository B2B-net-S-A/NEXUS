"""Publiczne trasy portalu konsultanta: link z maila, bez konta i hasła.

Prefiks ``/api/public/consultant-portal`` (wpięty w ``app/main.py`` za ``_HR_PROGRAM``).
Trasy mają ``@limiter.limit`` — dlatego moduł NIE ma ``from __future__ import annotations``
(ciało żądania lądowałoby jako parametr query → 422).

Opisany wyjątek od bramek tras: te trasy są publiczne z definicji, bo konsultant nie ma
konta. Zamiast JWT pracownika stoją tu dwa własne warunki:

* ``open_portal`` — wyłącznik ``app_settings['consultant_portal']``: ``off`` = 404, ta sama
  odpowiedź co nieistniejąca trasa, także przy poprawnej sesji,
* ``portal_context`` — sesja z nagłówka ``X-Portal-Session`` (losowy token, hash w bazie).
  Pracowniczy JWT tu nie działa, a token portalu nie działa w ``/api/**`` pracownika.

Limity liczą się per IP (``client_ip_key``): limit trasy i wspólny kubełek, żeby seria
różnych tokenów z jednego adresu nie posłużyła do zgadywania. Prośba o link odpowiada
zawsze tym samym zdaniem, a mail idzie w tle, więc treść i czas wysyłki nie mówią, czy
konsultant istnieje (zostaje zapis linku w bazie: milisekundy, niemierzone). Błędy bez
szczegółów wewnętrznych.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.core.http_headers import content_disposition
from app.core.rate_limit import limiter
from app.core.scheduling import business_today
from app.services.consultant_portal import (
    auth,
    content,
    documents,
    meetings,
    panel,
    portal_mail,
    portal_settings,
    ratings,
)
from app.services.consultant_portal.auth import PortalContext, PortalError
from app.services.consultant_portal.portal_settings import PortalSettings
from app.services.consultant_panel_schema import (
    MATERIAL_URL_MAX,
    TRAINER_SHORT_MAX,
    TRAINER_TEXT_MAX,
)
from app.services.consultant_portal_schema import COMMENT_MAX, REASON_MAX, TOPICS
from app.services.equipment import protocols as equipment_protocols
from app.services.equipment.errors import EquipmentError
from app.models.training import Training, TrainingFile
from app.services.trainings import agreement_files
from app.services.trainings import core as training_core
from app.services.trainings import media as training_media
from app.services.trainings import raw_upload as training_raw_upload
from app.services.trainings import samples as trainer_samples
from app.services.trainings import signals as training_signals
from app.services.trainings import signing as training_signing
from app.services.trainings import teams as training_teams
from app.services.trainings import storage as training_storage
from app.services.trainings.errors import TrainingError
from app.services.trainings_schema import TEXT_MAX as TRAINING_TEXT_MAX
from app.services.trainings_schema import TITLE_MAX as TRAINER_TITLE_MAX

router = APIRouter()

Topic = Literal["invoice", "contract", "leave", "access", "next", "data"]
assert set(Topic.__args__) == set(TOPICS)

LINK_SENT = (
    "Jeśli ten adres jest w naszych umowach, za chwilę dostaniesz link do strefy "
    "konsultanta. Link działa 30 minut."
)
LINK_INVALID = "Link nieprawidłowy lub wygasły. Poproś o nowy."
SESSION_EXPIRED = "Sesja wygasła. Poproś o nowy link."
FILE_TOO_LARGE = "Dokument może mieć najwyżej 20 MB."

SHARED_READ = "120/minute"
SHARED_AUTH = "20/minute"
SHARED_WRITE = "30/minute"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _translate(exc: PortalError) -> HTTPException:
    return HTTPException(exc.status, {"message": exc.message, "code": exc.code})


async def open_portal(db: AsyncSession = Depends(get_db)) -> PortalSettings:
    state = await portal_settings.load(db)
    if not state.is_on:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return state


OpenPortal = Annotated[PortalSettings, Depends(open_portal)]


async def portal_context(
    state: OpenPortal,
    db: AsyncSession = Depends(get_db),
    x_portal_session: Annotated[Optional[str], Header()] = None,
) -> PortalContext:
    context = await auth.load_context(
        db, x_portal_session, state=state, today=business_today(), now=_now()
    )
    if context is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, SESSION_EXPIRED)
    return context


Session = Annotated[PortalContext, Depends(portal_context)]


# ── Wejście ──────────────────────────────────────────────────────────────────


class LinkRequest(BaseModel):
    email: EmailStr


class SessionRequest(BaseModel):
    # Bez dolnej granicy: krótki token dostaje to samo 404 co każdy inny zły.
    token: str = Field(max_length=2048)


@router.get("/status")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def portal_status(
    state: OpenPortal,
    request: Request,  # wymagane przez limiter slowapi
) -> dict:
    return {"open": True}


async def _send_link(contract_id: int, email: str, raw_token: str) -> None:
    """Mail po odpowiedzi: czas odpowiedzi nie zdradza, czy adres istnieje."""

    async with AsyncSessionLocal() as db:
        await portal_mail.send(
            db,
            contract_id=contract_id,
            to=email,
            subject="Twój link do strefy konsultanta B2B.net",
            text=(
                "Cześć,\n\nto Twój link do strefy konsultanta. Działa 30 minut i tylko raz:\n"
                f"{portal_mail.portal_url(f'/wejscie#{raw_token}')}\n\n"
                "Jeśli to nie Ty prosisz o link, zignoruj tę wiadomość."
            ),
        )


@router.post("/link", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute;20/hour")
@limiter.shared_limit(SHARED_AUTH, scope="consultant-portal-auth")
async def request_link(
    payload: LinkRequest,
    state: OpenPortal,
    request: Request,  # wymagane przez limiter slowapi
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    link = await auth.request_link(
        db, payload.email, state=state, today=business_today(), now=_now()
    )
    if link is not None:
        background.add_task(_send_link, link.contract_id, link.email, link.raw_token)
    return {"message": LINK_SENT}


@router.post("/session")
@limiter.limit("10/minute;60/hour")
@limiter.shared_limit(SHARED_AUTH, scope="consultant-portal-auth")
async def open_session(
    payload: SessionRequest,
    state: OpenPortal,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    opened = await auth.open_session(
        db, payload.token, state=state, today=business_today(), now=_now()
    )
    if opened is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, LINK_INVALID)
    raw, session = opened
    return {"session_token": raw, "expires_at": session.expires_at.isoformat()}


@router.post("/logout")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def logout(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    await auth.revoke(db, context.session, now=_now())
    return {"ok": True}


# ── Treści i sprawy ──────────────────────────────────────────────────────────


@router.get("/me")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def me(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {
        **await content.overview(db, context),
        **await panel.overview_extra(db, context, today=business_today()),
    }


@router.get("/todo")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def todo(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"items": await panel.todo(db, context, today=business_today(), now=_now())}


@router.get("/faq")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def faq(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"items": await content.published_faq(db)}


@router.get("/cases")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def cases(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"items": await content.own_cases(db, context)}


class NewRequest(BaseModel):
    topic: Topic
    title: str = Field(min_length=3, max_length=content.CASE_TITLE_MAX)
    body: str = Field(min_length=3, max_length=content.CASE_BODY_MAX)


@router.post("/cases", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def new_case(
    payload: NewRequest,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await content.new_request(
            db, context, topic=payload.topic, title=payload.title, body=payload.body
        )
    except PortalError as exc:
        raise _translate(exc) from exc


# ── Rozmowy ──────────────────────────────────────────────────────────────────


@router.get("/booking/hosts")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def booking_hosts(
    topic: Topic,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await meetings.hosts_with_slots(db, topic=topic, now=_now())


@router.get("/meetings")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def list_meetings(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {
        "items": await meetings.own_meetings(db, context, now=_now()),
        "note": meetings.INVITE_NOTE,
    }


class BookRequest(BaseModel):
    host_user_id: int = Field(gt=0)
    start: datetime
    topic: Topic
    reason: str = Field(default="", max_length=REASON_MAX)


@router.post("/meetings", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute;20/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def book_meeting(
    payload: BookRequest,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        meeting = await meetings.book(
            db,
            context,
            host_user_id=payload.host_user_id,
            start=payload.start,
            topic=payload.topic,
            reason=payload.reason,
            now=_now(),
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return {
        "id": meeting.id,
        "start_at": meeting.start_at.isoformat(),
        "end_at": meeting.end_at.isoformat(),
        "join_url": meeting.join_url,
        "status": meeting.status,
    }


@router.post("/meetings/{meeting_id}/cancel")
@limiter.limit("10/minute")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def cancel_meeting(
    meeting_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        meeting = await meetings.cancel(db, context, meeting_id, now=_now())
    except PortalError as exc:
        raise _translate(exc) from exc
    return {"id": meeting.id, "status": meeting.status}


class RatingRequest(BaseModel):
    score: int = Field(ge=1, le=5)
    resolved: Optional[bool] = None
    comment: Optional[str] = Field(default=None, max_length=COMMENT_MAX)


@router.post("/meetings/{meeting_id}/rating", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def rate_meeting(
    meeting_id: int,
    payload: RatingRequest,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await ratings.rate_as_consultant(
            db,
            context,
            meeting_id,
            score=payload.score,
            resolved=payload.resolved,
            comment=payload.comment,
            now=_now(),
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return {"ok": True}


class RatingLinkRequest(BaseModel):
    token: str = Field(max_length=2048)


class RatingByLinkRequest(RatingRequest):
    token: str = Field(max_length=2048)


# Token idzie w ciele, nie w adresie: adres trafia do logów serwera i pośredników.
@router.post("/rating-form")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_AUTH, scope="consultant-portal-auth")
async def rating_form(
    payload: RatingLinkRequest,
    state: OpenPortal,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    summary = await ratings.link_summary(db, payload.token, state=state, now=_now())
    if summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, LINK_INVALID)
    return summary


@router.post("/rating", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute;30/hour")
@limiter.shared_limit(SHARED_AUTH, scope="consultant-portal-auth")
async def rate_by_link(
    payload: RatingByLinkRequest,
    state: OpenPortal,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        rating = await ratings.rate_by_link(
            db,
            payload.token,
            state=state,
            score=payload.score,
            resolved=payload.resolved,
            comment=payload.comment,
            now=_now(),
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    if rating is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, LINK_INVALID)
    return {"ok": True}


# ── Finanse ──────────────────────────────────────────────────────────────────


@router.get("/finance/overview")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def finance_overview(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {
        "months": await documents.overview(db, context, today=business_today()),
    }


@router.post("/finance/documents", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute;60/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def finance_upload(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    kind: Annotated[Literal["report", "invoice"], Form()],
    year: Annotated[int, Form()],
    month: Annotated[int, Form()],
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    data = await file.read(documents.MAX_FILE_BYTES + 1)
    if len(data) > documents.MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, FILE_TOO_LARGE)
    try:
        stored = await documents.upload_from_portal(
            db,
            context,
            kind=kind,
            year=year,
            month=month,
            content=data,
            file_name=file.filename,
            today=business_today(),
            now=_now(),
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return {
        "id": stored.document.id,
        "status": stored.document.status,
        "duplicate": stored.duplicate,
    }


@router.get("/finance/documents/{document_id}/file")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def finance_download(
    document_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    try:
        document = await documents.own_document(db, context, document_id)
        path = documents.path_for(document.file_path)
    except PortalError as exc:
        raise _translate(exc) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, documents.NOT_FOUND) from exc
    name = document.file_name or f"dokument-{document.id}"
    return FileResponse(
        path,
        media_type=document.mime,
        headers={"Content-Disposition": content_disposition(name, "attachment")},
    )


@router.get("/settlement")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def settlement(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await panel.settlement_screen(db, context)


# ── Na start ─────────────────────────────────────────────────────────────────


@router.get("/start")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def start_screen(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await panel.start_screen(db, context, today=business_today())


@router.get("/start/materials/{material_id}/file")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def start_material_file(
    material_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    try:
        material, path = await panel.own_material_file(db, context, material_id)
    except PortalError as exc:
        raise _translate(exc) from exc
    name = material.file_name or f"material-{material.id}"
    return FileResponse(
        path,
        media_type=material.mime,
        headers={"Content-Disposition": content_disposition(name, "attachment")},
    )


# ── Sprzęt ───────────────────────────────────────────────────────────────────


@router.get("/equipment")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def equipment(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await panel.equipment_screen(db, context)


@router.get("/equipment/protocols/{protocol_id}/document.pdf")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def equipment_protocol_pdf(
    protocol_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        protocol = await panel.own_protocol(db, context, protocol_id)
    except PortalError as exc:
        raise _translate(exc) from exc
    try:
        data = await equipment_protocols.render_pdf(db, protocol)
    except EquipmentError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    name = equipment_protocols.protocol_filename(protocol, "pdf")
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(name, "attachment")},
    )


class ProtocolConfirmRequest(BaseModel):
    signer_name: str = Field(min_length=3, max_length=200)


@router.post("/equipment/protocols/{protocol_id}/confirm")
@limiter.limit("10/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def equipment_protocol_confirm(
    protocol_id: int,
    payload: ProtocolConfirmRequest,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        protocol = await panel.own_protocol(db, context, protocol_id)
        signed = await equipment_protocols.sign_in_panel(
            db, protocol, signer_name=payload.signer_name
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    except EquipmentError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return {"status": signed.status}


# ── Zostań trenerem ──────────────────────────────────────────────────────────


@router.get("/trainer")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def trainer(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"application": await panel.trainer_application(db, context)}


class TrainerRequest(BaseModel):
    """Bez formy i stawki za dzień (13.11.2026): szkolenia są wyłącznie zdalne (§ 3 umowy
    szkoleniowej), a cenę trener podaje w wycenie zamówienia. Stare pola ``form`` i
    ``day_rate`` z otwartej karty przeglądarki są ignorowane."""

    topics: list[str] = Field(min_length=1, max_length=20)
    experience: str = Field(min_length=3, max_length=TRAINER_TEXT_MAX)
    proposal_title: str = Field(default="", max_length=TRAINER_TITLE_MAX)
    proposal_hours: str = Field(default="", max_length=TRAINER_SHORT_MAX)
    audience: str = Field(default="", max_length=TRAINER_SHORT_MAX)
    availability: str = Field(default="", max_length=TRAINER_SHORT_MAX)
    materials: str = Field(default="", max_length=MATERIAL_URL_MAX)
    # 0698: formularz otwarty z „Zgłoś się na temat” w „Szukamy trenerów”.
    topic_request_id: Optional[int] = None


@router.put("/trainer")
@limiter.limit("10/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def save_trainer(
    payload: TrainerRequest,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        application = await panel.save_trainer_application(
            db,
            context,
            topics=payload.topics,
            experience=payload.experience,
            proposal_title=payload.proposal_title,
            proposal_hours=payload.proposal_hours,
            audience=payload.audience,
            availability=payload.availability,
            materials=payload.materials,
            topic_request_id=payload.topic_request_id,
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return {"application": application}


class TopicJoinRequest(BaseModel):
    join: bool


@router.post("/trainer/topics/{topic_id}")
@limiter.limit("10/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def trainer_topic(
    topic_id: int,
    payload: TopicJoinRequest,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Zgłoś się na temat” (0698): temat z „Szukamy trenerów” do zgłoszenia trenera."""

    try:
        application = await panel.save_trainer_topic(
            db, context, topic_id, join=payload.join
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return {"application": application}


@router.post("/trainer/sample")
@limiter.limit("10/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def save_trainer_sample(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    data = await file.read(trainer_samples.MAX_BYTES + 1)
    if len(data) > trainer_samples.MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, trainer_samples.REJECTED)
    try:
        application = await panel.save_trainer_sample(
            db, context, file_name=file.filename or "", content=data
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return {"application": application}


# ── Szkolenia: moje szkolenia, wycena, umowa, pliki, biblioteka ─────────────


def _training_error(exc: TrainingError) -> HTTPException:
    return HTTPException(exc.status, {"message": exc.message, "code": exc.code})


class AgendaItem(BaseModel):
    title: str = Field(default="", max_length=TRAINER_TITLE_MAX)
    minutes: Optional[int] = Field(default=None, ge=0, le=600)


class QuoteRequest(BaseModel):
    agenda: list[AgendaItem] = Field(min_length=1, max_length=20)
    fee_prep: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    fee_delivery: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    fee_presentation: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    fee_audio: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    fee_rights: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    own_materials: str = Field(default="", max_length=TRAINING_TEXT_MAX)
    third_party_materials: str = Field(default="", max_length=TRAINING_TEXT_MAX)
    quote_note: str = Field(default="", max_length=TRAINING_TEXT_MAX)


class JoinRequest(BaseModel):
    join: bool


@router.get("/trainings")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def trainings(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    consultant = context.consultant
    return {
        "mine": await training_core.trainer_trainings(db, consultant.contract_ids),
        "library": await training_core.library(
            db, today=business_today(), contract_ids=consultant.contract_ids
        ),
        "applied": await panel.trainer_application(db, context) is not None,
        "wanted_topics": await panel.wanted_topics(db, context),
    }


@router.get("/trainings/{training_id}")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def training_detail(
    training_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await training_core.for_trainer(
            db, training_id, context.consultant.contract_ids
        )
    except TrainingError as exc:
        raise _training_error(exc) from exc
    return {"training": await training_core.trainer_view(db, training)}


@router.put("/trainings/{training_id}/quote")
@limiter.limit("10/minute;60/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def training_quote(
    training_id: int,
    payload: QuoteRequest,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await training_core.submit_quote(
            db,
            training_id,
            context.consultant.contract_ids,
            training_core.QuoteInput(
                agenda=tuple(item.model_dump() for item in payload.agenda),
                fees={
                    "fee_prep": payload.fee_prep,
                    "fee_delivery": payload.fee_delivery,
                    "fee_presentation": payload.fee_presentation,
                    "fee_audio": payload.fee_audio,
                    "fee_rights": payload.fee_rights,
                },
                own_materials=payload.own_materials,
                third_party_materials=payload.third_party_materials,
                quote_note=payload.quote_note,
            ),
            now=_now(),
        )
        await training_signals.quote_submitted(db, training)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    await db.commit()
    return {"training": await training_core.trainer_view(db, training)}


@router.get("/trainings/{training_id}/agreement.pdf")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def training_agreement_pdf(
    training_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    version: Literal["draft", "trainer", "signed"] = "draft",
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    try:
        training = await training_core.for_trainer(
            db, training_id, context.consultant.contract_ids
        )
        return agreement_files.response(training, version)
    except TrainingError as exc:
        raise _training_error(exc) from exc


@router.post("/trainings/{training_id}/agreement/signature")
@limiter.limit("10/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def training_agreement_signature(
    training_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    data = await file.read(documents.MAX_FILE_BYTES + 1)
    if len(data) > documents.MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, FILE_TOO_LARGE)
    try:
        await training_core.for_trainer(
            db, training_id, context.consultant.contract_ids
        )
        training = await training_signing.trainer_upload(
            db, training_id, data, now=_now()
        )
        if training.status == "trainer_signed":
            await training_signals.awaiting_company_signature(db, training)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    await db.commit()
    return {"training": await training_core.trainer_view(db, training)}


@router.post("/trainings/{training_id}/deliverables/{key}", status_code=201)
@limiter.limit("20/minute;120/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def training_deliverable(
    training_id: int,
    key: Literal["materials", "presentation", "audio", "other"],
    context: Session,
    request: Request,  # wymagane przez limiter slowapi; ciało = sam plik
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Plik z Zał. 1 pkt 4 jako surowe ciało (``raw_upload``): sesja i dostęp do
    szkolenia są sprawdzone, zanim serwer weźmie choć jeden bajt (do 2 GB)."""

    try:
        training = await training_core.check_deliverable(
            db, training_id, context.consultant.contract_ids, key
        )
        upload = training_raw_upload.read(request)
        stored = await training_storage.save(
            db,
            training_id=training.id,
            training_title=training.title,
            session_year=(training.session_date or business_today()).year,
            file_name=upload.file_name,
            content_type=upload.content_type,
            source=upload.body,
        )
        await training_core.add_deliverable(
            db,
            training,
            key=key,
            stored=stored,
            file_name=upload.file_name,
            contract_id=training.trainer_contract_id or context.consultant.contract_id,
            now=_now(),
        )
        await training_signals.file_submitted(db, training, upload.file_name)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    await db.commit()
    return {"training": await training_core.trainer_view(db, training)}


@router.post("/trainings/{training_id}/invoice", status_code=201)
@limiter.limit("10/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def training_invoice(
    training_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await training_core.for_trainer(
            db, training_id, context.consultant.contract_ids
        )
        if training.invoice_ready_at is None or training.paid_at is not None:
            raise TrainingError(
                409,
                "Fakturę wgrasz po przyjęciu wszystkich plików z Załącznika nr 1.",
                "not_ready",
            )
        if not (file.filename or "").lower().endswith(".pdf"):
            raise TrainingError(422, "Fakturę wgraj jako PDF.", "invoice_pdf")
        stored = await training_storage.save(
            db,
            training_id=training.id,
            training_title=training.title,
            session_year=(training.session_date or business_today()).year,
            file_name=file.filename or "faktura.pdf",
            content_type="application/pdf",
            source=file,
        )
        await training_core.add_file(
            db,
            training,
            kind="invoice",
            stored=stored,
            file_name=file.filename or "faktura.pdf",
            now=_now(),
            contract_id=training.trainer_contract_id,
        )
        await training_signals.invoice_uploaded(db, training)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    await db.commit()
    return {"training": await training_core.trainer_view(db, training)}


async def _portal_training_file(
    db: AsyncSession, context: PortalContext, file_id: int
) -> tuple[TrainingFile, str]:
    """Plik własnego szkolenia (trener, zakres ``own``) albo plik z biblioteki
    (każdy z panelem, zakres ``lib``)."""

    own = await db.scalar(
        select(TrainingFile)
        .join(Training, Training.id == TrainingFile.training_id)
        .where(
            TrainingFile.id == file_id,
            Training.trainer_contract_id.in_(context.consultant.contract_ids),
            Training.status != "draft",
            TrainingFile.kind.in_(("deliverable", "invoice")),
        )
    )
    if own is not None:
        return own, "own"
    return await training_core.viewer_file(
        db, file_id, contract_ids=context.consultant.contract_ids
    )


@router.get("/trainings/files/{file_id}")
@limiter.limit("120/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def training_file(
    file_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    download: bool = False,
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        item, _scope = await _portal_training_file(db, context, file_id)
        return await training_storage.stream(
            item, range_header=request.headers.get("range"), download=download
        )
    except TrainingError as exc:
        raise _training_error(exc) from exc


@router.get("/trainings/files/{file_id}/ticket")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def training_file_ticket(
    file_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        _item, scope = await _portal_training_file(db, context, file_id)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    return {"url": training_media.url(file_id, scope=scope, now=_now())}


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1_000)


@router.post("/trainings/{training_id}/feedback")
@limiter.limit("20/minute")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def training_feedback(
    training_id: int,
    payload: FeedbackRequest,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await training_core.rate(
            db,
            training_id,
            today=business_today(),
            rating=payload.rating,
            comment=payload.comment,
            contract_id=context.consultant.contract_id,
        )
    except TrainingError as exc:
        raise _training_error(exc) from exc
    await db.commit()
    return {"rating": payload.rating}


@router.get("/trainings/{training_id}/transcript")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-portal-read")
async def training_transcript(
    training_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> dict:
    training = await db.get(Training, training_id)
    visible = (
        training is not None
        and training.status == "signed"
        and (
            training.published_at is not None
            or (
                training.shared_registered_at is not None
                and await training_core.is_registered(
                    db, training_id, contract_ids=context.consultant.contract_ids
                )
            )
        )
    )
    if not visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, training_core.NOT_FOUND)
    return await training_core.transcript_search(db, training_id, q[:100])


@router.post("/trainings/{training_id}/registration")
@limiter.limit("20/minute")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-portal-write")
async def training_registration(
    training_id: int,
    payload: JoinRequest,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        removed_invite = await training_core.register(
            db,
            training_id,
            today=business_today(),
            contract_id=context.consultant.contract_id,
            join=payload.join,
        )
    except TrainingError as exc:
        raise _training_error(exc) from exc
    await db.commit()
    # Zaproszenie Teams na adres z umowy po zatwierdzeniu zapisu (tylko przy otwartym panelu).
    await training_teams.registration_changed(
        db,
        training_id,
        join=payload.join,
        contract_id=context.consultant.contract_id,
        removed_invite=removed_invite,
    )
    await db.commit()
    return {"registered": payload.join}
