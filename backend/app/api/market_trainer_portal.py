"""Panel trenera z rynku: ``/api/public/trainer-portal`` (0807, decyzje Artura 28.11.2026).

Trener z rynku loguje się tym samym ekranem ``/konsultant`` co konsultant, ale jego
link i sesja żyją w osobnych tabelach (``services/market_trainer_portal/auth``),
a ten router ma wyłącznie trasy szkoleń: logowanie, „Trener” (dane firmy do umowy,
tylko odczyt) i własne szkolenia (wycena, umowa, podpis, pliki, faktura).
Rozliczeń, spraw, rozmów, sprzętu ani biblioteki tu nie ma: sesja trenera nie
otwiera żadnej trasy konsultanta, a token konsultanta nie pasuje do tych tras.

Bramka: własny włącznik ``app_settings['market_trainer_portal']`` — wyłączony =
każda trasa 404, także przy poprawnej sesji. Limity jak w panelu konsultanta.
Moduł bez ``from __future__ import annotations`` — slowapi (patrz CLAUDE.md).
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
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
from app.core.rate_limit import limiter
from app.core.scheduling import business_today
from app.models.training import Training, TrainingFile
from app.services.consultant_portal import documents
from app.services.market_trainer_portal import auth, mail, switch
from app.services.market_trainer_portal.auth import TrainerContext
from app.services.trainings import agreement_files
from app.services.trainings import core as training_core
from app.services.trainings import media as training_media
from app.services.trainings import raw_upload as training_raw_upload
from app.services.trainings import signals as training_signals
from app.services.trainings import signing as training_signing
from app.services.trainings import storage as training_storage
from app.services.trainings.errors import TrainingError
from app.services.trainings_schema import TEXT_MAX as TRAINING_TEXT_MAX
from app.services.trainings_schema import TITLE_MAX as TRAINING_TITLE_MAX

logger = logging.getLogger(__name__)

router = APIRouter()

LINK_SENT = (
    "Jeśli ten adres ma otwarty panel, wysłaliśmy na niego link. "
    "Link działa 30 minut i tylko raz."
)
LINK_INVALID = "Link nieprawidłowy lub wygasły. Poproś o nowy."
SESSION_EXPIRED = "Sesja wygasła. Poproś o nowy link."
FILE_TOO_LARGE = "Dokument może mieć najwyżej 20 MB."

SHARED_READ = "120/minute"
SHARED_AUTH = "20/minute"
SHARED_WRITE = "30/minute"

# Ten sam ekran wejścia co konsultant: trener widzi tylko te pozycje menu.
MENU = ("szkolenia", "trener")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _training_error(exc: TrainingError) -> HTTPException:
    return HTTPException(exc.status, {"message": exc.message, "code": exc.code})


async def open_portal(db: AsyncSession = Depends(get_db)) -> None:
    if not await switch.is_enabled(db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


OpenPortal = Annotated[None, Depends(open_portal)]


async def trainer_context(
    _open: OpenPortal,
    db: AsyncSession = Depends(get_db),
    x_portal_session: Annotated[Optional[str], Header()] = None,
) -> TrainerContext:
    context = await auth.load_context(db, x_portal_session, now=_now())
    if context is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, SESSION_EXPIRED)
    return context


Session = Annotated[TrainerContext, Depends(trainer_context)]


# ── Wejście ──────────────────────────────────────────────────────────────────


class LinkRequest(BaseModel):
    email: EmailStr


class SessionRequest(BaseModel):
    token: str = Field(max_length=2048)


@router.get("/status")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="trainer-portal-read")
async def portal_status(
    _open: OpenPortal,
    request: Request,  # wymagane przez limiter slowapi
) -> dict:
    return {"open": True}


async def _send_link(email: str, raw_token: str) -> None:
    """Mail po odpowiedzi: czas odpowiedzi nie zdradza, czy adres istnieje."""
    async with AsyncSessionLocal() as db:
        await mail.send(
            db,
            to=email,
            subject="Twój link do panelu trenera B2B.net",
            text=(
                "Dzień dobry,\n\nto Twój link do panelu trenera. Działa 30 minut "
                f"i tylko raz:\n{mail.login_url(raw_token)}\n\n"
                "Jeśli to nie Ty prosisz o link, zignoruj tę wiadomość."
            ),
        )


@router.post("/link", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute;20/hour")
@limiter.shared_limit(SHARED_AUTH, scope="trainer-portal-auth")
async def request_link(
    payload: LinkRequest,
    _open: OpenPortal,
    request: Request,  # wymagane przez limiter slowapi
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    link = await auth.request_link(db, payload.email, now=_now())
    if link is not None:
        background.add_task(_send_link, link.email, link.raw_token)
    return {"message": LINK_SENT}


@router.post("/session")
@limiter.limit("10/minute;60/hour")
@limiter.shared_limit(SHARED_AUTH, scope="trainer-portal-auth")
async def open_session(
    payload: SessionRequest,
    _open: OpenPortal,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    opened = await auth.open_session(db, payload.token, now=_now())
    if opened is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, LINK_INVALID)
    raw, session = opened
    return {"session_token": raw, "expires_at": session.expires_at.isoformat()}


@router.post("/logout")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_WRITE, scope="trainer-portal-write")
async def logout(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
) -> dict:
    context.session.revoked_at = _now()
    return {"ok": True}


@router.get("/me")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="trainer-portal-read")
async def me(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
) -> dict:
    """Kształt jak ``/me`` konsultanta, żeby ekran panelu był jeden; ``kind`` tnie menu."""
    first_name = (context.trainer.full_name or "").split(" ")[0] or None
    return {
        "kind": "trainer",
        "first_name": first_name,
        "client": None,
        "since": None,
        "until": None,
        "support_email": None,
        "support_phone": None,
        "topics": [],
        "rate": None,
        "menu": {"start": False, "equipment": False},
    }


@router.get("/trainer")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="trainer-portal-read")
async def trainer(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
) -> dict:
    """Dane firmy do umowy (tylko odczyt: zmienia je TCM) i zgłoszenie ze strony."""
    row = context.trainer
    return {
        "company": {
            "company_name": row.company_name,
            "nip": row.nip,
            "regon": row.regon or None,
            "company_address": row.company_address,
            "email": row.panel_email,
        },
        "application": {
            "topics": list(row.topics or [])
            + ([row.other_topic] if row.other_topic else []),
            "first_training": row.first_training,
        },
    }


# ── Szkolenia trenera ────────────────────────────────────────────────────────


class AgendaItem(BaseModel):
    title: str = Field(default="", max_length=TRAINING_TITLE_MAX)
    minutes: Optional[int] = Field(default=None, ge=0, le=600)


def _fee() -> Optional[Decimal]:
    return Field(default=None, ge=0, max_digits=12, decimal_places=2)


class QuoteRequest(BaseModel):
    agenda: list[AgendaItem] = Field(min_length=1, max_length=20)
    fee_prep: Optional[Decimal] = _fee()
    fee_delivery: Optional[Decimal] = _fee()
    fee_presentation: Optional[Decimal] = _fee()
    fee_audio: Optional[Decimal] = _fee()
    fee_rights: Optional[Decimal] = _fee()
    own_materials: str = Field(default="", max_length=TRAINING_TEXT_MAX)
    third_party_materials: str = Field(default="", max_length=TRAINING_TEXT_MAX)
    quote_note: str = Field(default="", max_length=TRAINING_TEXT_MAX)


async def _mine(
    db: AsyncSession, context: TrainerContext, training_id: int, *, lock: bool = False
) -> Training:
    return await training_core.for_trainer(
        db, training_id, (), market_id=context.market_id, lock=lock
    )


@router.get("/trainings")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="trainer-portal-read")
async def trainings(
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Biblioteka nagrań jest dla zespołu i konsultantów; trener z rynku widzi swoje.
    return {
        "mine": await training_core.trainer_trainings(
            db, (), market_id=context.market_id
        ),
        "library": {"recordings": [], "live": []},
        "applied": True,
    }


@router.get("/trainings/{training_id}")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="trainer-portal-read")
async def training_detail(
    training_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await _mine(db, context, training_id)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    return {"training": await training_core.trainer_view(db, training)}


@router.put("/trainings/{training_id}/quote")
@limiter.limit("10/minute;60/hour")
@limiter.shared_limit(SHARED_WRITE, scope="trainer-portal-write")
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
            (),
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
            market_id=context.market_id,
        )
        await training_signals.quote_submitted(db, training)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    await db.commit()
    return {"training": await training_core.trainer_view(db, training)}


@router.get("/trainings/{training_id}/agreement.pdf")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_READ, scope="trainer-portal-read")
async def training_agreement_pdf(
    training_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    version: Literal["draft", "trainer", "signed"] = "draft",
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    try:
        training = await _mine(db, context, training_id)
        return agreement_files.response(training, version)
    except TrainingError as exc:
        raise _training_error(exc) from exc


@router.post("/trainings/{training_id}/agreement/signature")
@limiter.limit("10/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="trainer-portal-write")
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
        await _mine(db, context, training_id)
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
@limiter.shared_limit(SHARED_WRITE, scope="trainer-portal-write")
async def training_deliverable(
    training_id: int,
    key: Literal["materials", "presentation", "audio", "other"],
    context: Session,
    request: Request,  # wymagane przez limiter slowapi; ciało = sam plik
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Surowe ciało jak w panelu konsultanta: sesja i dostęp przed odczytem bajtów."""
    try:
        training = await training_core.check_deliverable(
            db, training_id, (), key, market_id=context.market_id
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
            contract_id=None,
            market_id=context.market_id,
            now=_now(),
        )
        await training_signals.file_submitted(db, training, upload.file_name)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    await db.commit()
    return {"training": await training_core.trainer_view(db, training)}


@router.post("/trainings/{training_id}/invoice", status_code=201)
@limiter.limit("10/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="trainer-portal-write")
async def training_invoice(
    training_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await _mine(db, context, training_id)
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
            market_id=context.market_id,
        )
        await training_signals.invoice_uploaded(db, training)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    await db.commit()
    return {"training": await training_core.trainer_view(db, training)}


async def _own_file(
    db: AsyncSession, context: TrainerContext, file_id: int
) -> TrainingFile:
    """Wyłącznie plik ze szkolenia tego trenera (jego pliki i faktura)."""
    item = await db.scalar(
        select(TrainingFile)
        .join(Training, Training.id == TrainingFile.training_id)
        .where(
            TrainingFile.id == file_id,
            Training.trainer_market_id == context.market_id,
            Training.status != "draft",
            TrainingFile.kind.in_(("deliverable", "invoice")),
        )
    )
    if item is None:
        raise TrainingError(404, "Nie ma takiego pliku.", "file_not_found")
    return item


@router.get("/trainings/files/{file_id}")
@limiter.limit("120/minute")
@limiter.shared_limit(SHARED_READ, scope="trainer-portal-read")
async def training_file(
    file_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    download: bool = False,
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        item = await _own_file(db, context, file_id)
        return await training_storage.stream(
            item, range_header=request.headers.get("range"), download=download
        )
    except TrainingError as exc:
        raise _training_error(exc) from exc


@router.get("/trainings/files/{file_id}/ticket")
@limiter.limit("60/minute")
@limiter.shared_limit(SHARED_READ, scope="trainer-portal-read")
async def training_file_ticket(
    file_id: int,
    context: Session,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await _own_file(db, context, file_id)
    except TrainingError as exc:
        raise _training_error(exc) from exc
    return {"url": training_media.url(file_id, scope="own", now=_now())}
