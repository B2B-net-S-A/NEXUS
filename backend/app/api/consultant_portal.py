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
    topics: list[str] = Field(min_length=1, max_length=20)
    experience: str = Field(min_length=3, max_length=TRAINER_TEXT_MAX)
    form: Literal["online_or_onsite", "online", "onsite"] = "online_or_onsite"
    day_rate: str = Field(default="", max_length=TRAINER_SHORT_MAX)
    availability: str = Field(default="", max_length=TRAINER_SHORT_MAX)
    materials: str = Field(default="", max_length=MATERIAL_URL_MAX)


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
            form=payload.form,
            day_rate=payload.day_rate,
            availability=payload.availability,
            materials=payload.materials,
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return {"application": application}
