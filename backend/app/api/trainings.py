"""Szkolenia i trenerzy od strony NEXUSA (decyzja Artura 13.11.2026).

Prefiks ``/api/trainings`` (wpięty w ``app/main.py`` za ``_HR_PROGRAM``: to moduł grupy
„Ludzie w NEXUSIE”, jak panel konsultanta). Bramki:

* **prowadzenie szkoleń** (zamówienie, wycena, umowa, przyjęcie plików, nagranie,
  publikacja, obecność): Talent Community Manager i admin,
* **odczyt z kwotami**: to samo plus „Moduł Finanse”; trener widzi swoje kwoty w panelu,
* **zapłata**: „Moduł Finanse” (i admin),
* **podpis za B2B Network**: osoba z listy reprezentantów podpisu B2B
  (``company_signer_ids``); reguła siedzi w handlerze, bo lista jest w ustawieniach,
* **biblioteka i zapisy**: każda zalogowana osoba po wejściu do NEXUSA,
* **folder SharePointa na pliki**: admin.

Reguły, których macierz uprawnień nie widzi: publikacja dopiero po zapłacie trenera
B2B (§ 8 ust. 3 umowy), nagranie zatwierdza druga osoba, plik z biblioteki tylko
z opublikowanego szkolenia i tylko „dla uczestników”. Pilnują ich testy
``test_trainings_flow.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today
from app.models.consultant_panel import CpTrainerApplication
from app.models.contract import Contract
from app.models.training import Training, TrainingAttendance, TrainingFile
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import audit
from app.services.trainings import (
    agreement,
    agreement_files,
    attendance,
    core,
    media,
    raw_upload,
    samples,
    signing,
    storage,
)
from app.services.trainings.errors import TrainingError
from app.services.trainings_schema import (
    DESCRIPTION_MAX,
    NOTE_MAX,
    TEXT_MAX,
    TITLE_MAX,
)

router = APIRouter()

MANAGER_ONLY = "Szkolenia prowadzi Talent Community Manager albo administrator."
READER_ONLY = "Szkolenia widzi Talent Community, Finanse i administrator."
FINANCE_ONLY = "Zapłatę oznacza zespół Finansów."
ADMIN_ONLY = "Folder na pliki szkoleń ustawia administrator."
MAX_ATTENDANCE_BYTES = 5 * 1024 * 1024
MAX_INVOICE_BYTES = 20 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _translate(exc: TrainingError) -> HTTPException:
    return HTTPException(exc.status, {"message": exc.message, "code": exc.code})


def is_manager(user: User) -> bool:
    return user.has_role(UserRole.admin) or user.has_role(
        UserRole.talent_community_manager
    )


def is_finance(user: User) -> bool:
    return user.has_role(UserRole.admin) or has_permission(
        user, ProductAction.finance_module
    )


def require_hr_trainings_manager():
    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        if not is_manager(current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, MANAGER_ONLY)
        return current_user

    return _check


def require_hr_trainings_reader():
    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        if not (is_manager(current_user) or is_finance(current_user)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, READER_ONLY)
        return current_user

    return _check


def require_hr_trainings_finance():
    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        if not is_finance(current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, FINANCE_ONLY)
        return current_user

    return _check


def require_hr_trainings_admin():
    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        if not current_user.has_role(UserRole.admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_ONLY)
        return current_user

    return _check


BOARD_ONLY_INSIGHTS = "Rola „Rada nadzorcza” widzi tylko Insights."


def require_hr_trainings_viewer():
    """Biblioteka i zapisy: każda osoba po wejściu do NEXUSA, poza Radą nadzorczą,
    która z decyzji z 21.10.2026 widzi wyłącznie Insights."""

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        if current_user.has_role(UserRole.board):
            raise HTTPException(status.HTTP_403_FORBIDDEN, BOARD_ONLY_INSIGHTS)
        return current_user

    return _check


Manager = Annotated[User, Depends(require_hr_trainings_manager())]
Reader = Annotated[User, Depends(require_hr_trainings_reader())]
Finance = Annotated[User, Depends(require_hr_trainings_finance())]
Admin = Annotated[User, Depends(require_hr_trainings_admin())]
Viewer = Annotated[User, Depends(require_hr_trainings_viewer())]


# ── Modele wejścia ───────────────────────────────────────────────────────────


class Deliverable(BaseModel):
    key: Literal["materials", "presentation", "audio", "other"]
    label: str = Field(default="", max_length=TITLE_MAX)
    required: bool = True
    format: str = Field(default="", max_length=TITLE_MAX)
    due_days: Optional[int] = Field(default=None, ge=0, le=60)


class OrderBody(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    topic: str = Field(default="", max_length=TITLE_MAX)
    description: str = Field(default="", max_length=DESCRIPTION_MAX)
    session_date: Optional[date] = None
    time_from: str = Field(default="", max_length=5)
    time_to: str = Field(default="", max_length=5)
    duration_minutes: Optional[int] = Field(default=None, ge=15, le=2_400)
    platform: str = Field(default="Microsoft Teams", max_length=TITLE_MAX)
    join_url: str = Field(default="", max_length=1_000)
    expected_participants: Optional[int] = Field(default=None, ge=1, le=10_000)
    quote_due_on: Optional[date] = None
    participant_materials: str = Field(default="", max_length=TEXT_MAX)
    deliverables: list[Deliverable] = Field(default_factory=list, max_length=4)
    knowledge_test: bool = False
    extra_terms: str = Field(default="", max_length=TEXT_MAX)

    def to_input(self) -> core.OrderInput:
        return core.OrderInput(
            title=self.title,
            topic=self.topic,
            description=self.description,
            session_date=self.session_date,
            time_from=self.time_from,
            time_to=self.time_to,
            duration_minutes=self.duration_minutes,
            platform=self.platform,
            join_url=self.join_url,
            expected_participants=self.expected_participants,
            quote_due_on=self.quote_due_on,
            participant_materials=self.participant_materials,
            deliverables=tuple(item.model_dump() for item in self.deliverables),
            knowledge_test=self.knowledge_test,
            extra_terms=self.extra_terms,
        )


class CreateBody(OrderBody):
    trainer_contract_id: Optional[int] = None
    trainer_user_id: Optional[int] = None
    application_id: Optional[int] = None


class NoteBody(BaseModel):
    note: str = Field(default="", max_length=TEXT_MAX)


class CancelBody(BaseModel):
    reason: str = Field(default="", max_length=NOTE_MAX)


class PartnerBody(BaseModel):
    full_name: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=300)
    address: str = Field(default="", max_length=300)
    postal_city: str = Field(default="", max_length=200)
    nip: str = Field(default="", max_length=20)
    regon: str = Field(default="", max_length=20)
    phone: str = Field(default="", max_length=50)
    email: str = Field(default="", max_length=255)


class AgreementBody(BaseModel):
    partner: PartnerBody
    company_email: str = Field(min_length=3, max_length=255)


class ReviewBody(BaseModel):
    accept: bool
    note: str = Field(default="", max_length=NOTE_MAX)


class FlagBody(BaseModel):
    value: bool


class PaidBody(BaseModel):
    paid: bool


class PublishBody(BaseModel):
    publish: bool


class JoinBody(BaseModel):
    join: bool


class SharePointBody(BaseModel):
    share_url: str = Field(min_length=10, max_length=2_000)


# ── Pomocnicze ───────────────────────────────────────────────────────────────


async def _view(db: AsyncSession, training: Training) -> dict[str, Any]:
    return await core.staff_view(db, training, show_fees=True)


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Plik może mieć najwyżej {limit // 1024 // 1024} MB.",
        )
    return data


# ── Kim jestem dla szkoleń ───────────────────────────────────────────────────


@router.get("/me")
async def me(current_user: Viewer, db: AsyncSession = Depends(get_db)) -> dict:
    return {
        "can_manage": is_manager(current_user),
        "can_read": is_manager(current_user) or is_finance(current_user),
        "can_pay": is_finance(current_user),
        "is_company_signer": await signing.is_company_signer(db, current_user),
    }


# ── Biblioteka (każdy) ───────────────────────────────────────────────────────


@router.get("/library")
async def library(current_user: Viewer, db: AsyncSession = Depends(get_db)) -> dict:
    return await core.library(db, today=business_today(), user_id=current_user.id)


@router.get("/library/files/{file_id}")
async def library_file(
    file_id: int,
    request: Request,
    current_user: Viewer,
    download: bool = False,
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        item = await core.library_file(db, file_id)
        return await storage.stream(
            item, range_header=request.headers.get("range"), download=download
        )
    except TrainingError as exc:
        raise _translate(exc) from exc


@router.get("/library/files/{file_id}/ticket")
async def library_ticket(
    file_id: int, current_user: Viewer, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        await core.library_file(db, file_id)
    except TrainingError as exc:
        raise _translate(exc) from exc
    return {"url": media.url(file_id, scope="lib", now=_now())}


@router.post("/library/{training_id}/registration")
async def registration(
    training_id: int,
    body: JoinBody,
    current_user: Viewer,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await core.register(
            db,
            training_id,
            today=business_today(),
            user_id=current_user.id,
            join=body.join,
        )
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"registered": body.join}


# ── Zgłoszenia trenerów ──────────────────────────────────────────────────────


@router.get("/applications")
async def applications(
    current_user: Manager, db: AsyncSession = Depends(get_db)
) -> dict:
    rows = (
        await db.execute(
            select(CpTrainerApplication, Contract.candidate_email)
            .join(Contract, Contract.id == CpTrainerApplication.contract_id)
            .order_by(CpTrainerApplication.updated_at.desc())
            .limit(300)
        )
    ).all()
    out = []
    for application, email in rows:
        out.append(
            {
                "id": application.id,
                "contract_id": application.contract_id,
                "trainer_name": await core.contract_person_name(
                    db, application.contract_id
                ),
                "email": email,
                "topics": application.topics,
                "experience": application.experience,
                "proposal_title": application.proposal_title,
                "proposal_hours": application.proposal_hours,
                "audience": application.audience,
                "availability": application.availability,
                "materials": application.materials,
                "sample_name": application.sample_name,
                "case_id": application.case_id,
                "sent_at": application.updated_at.isoformat(),
            }
        )
    return {"applications": out}


@router.get("/applications/{application_id}/sample")
async def application_sample(
    application_id: int, current_user: Manager, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    application = await db.get(CpTrainerApplication, application_id)
    if application is None or not application.sample_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej próbki.")
    try:
        path = samples.path_for(application.sample_path)
    except FileNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Nie ma takiej próbki."
        ) from None
    return FileResponse(
        path,
        headers={
            "Content-Disposition": content_disposition(
                application.sample_name or path.name
            ),
            "Cache-Control": "private, no-store",
        },
    )


# ── Folder SharePointa (admin) ───────────────────────────────────────────────


@router.get("/settings")
async def get_settings(current_user: Admin, db: AsyncSession = Depends(get_db)) -> dict:
    target = await storage.load_settings(db)
    return {
        "sharepoint": target is not None and storage.sharepoint_ready(target),
        "share_url": getattr(target, "share_url", None) if target else None,
    }


@router.put("/settings")
async def save_settings(
    body: SharePointBody, current_user: Admin, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        target = await storage.save_settings(db, body.share_url)
    except TrainingError as exc:
        raise _translate(exc) from exc
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="trainings",
        entity_id=0,
        action="trainings_sharepoint_folder",
        details={},
    )
    await db.commit()
    return {"sharepoint": storage.sharepoint_ready(target), "share_url": body.share_url}


# ── Rejestr i zamówienie (TCM) ───────────────────────────────────────────────


@router.get("")
async def list_trainings(
    current_user: Reader, db: AsyncSession = Depends(get_db)
) -> dict:
    rows = (
        await db.scalars(
            select(Training).order_by(
                Training.session_date.desc().nulls_first(), Training.id.desc()
            )
        )
    ).all()
    return {
        "trainings": [
            core.list_row(t, name=await core.trainer_name(db, t), show_fees=True)
            for t in rows
        ]
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_training(
    body: CreateBody, current_user: Manager, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        training = await core.create(
            db,
            body.to_input(),
            actor=current_user,
            trainer_contract_id=body.trainer_contract_id,
            trainer_user_id=body.trainer_user_id,
            application_id=body.application_id,
        )
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"training": await _view(db, training)}


@router.get("/{training_id}")
async def get_training(
    training_id: int, current_user: Reader, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        training = await core.get(db, training_id)
    except TrainingError as exc:
        raise _translate(exc) from exc
    return {"training": await _view(db, training)}


@router.put("/{training_id}")
async def update_training(
    training_id: int,
    body: OrderBody,
    current_user: Manager,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await core.update_order(db, training_id, body.to_input())
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"training": await _view(db, training)}


@router.post("/{training_id}/send")
async def send_order(
    training_id: int, current_user: Manager, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        training = await core.send_order(db, training_id, now=_now())
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    from app.services.trainings import notify

    await notify.order_sent(db, training)
    return {"training": await _view(db, training)}


@router.post("/{training_id}/cancel")
async def cancel_training(
    training_id: int,
    body: CancelBody,
    current_user: Manager,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await core.cancel(db, training_id, reason=body.reason, now=_now())
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"training": await _view(db, training)}


@router.post("/{training_id}/return")
async def return_quote(
    training_id: int,
    body: NoteBody,
    current_user: Manager,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await core.return_quote(db, training_id, note=body.note)
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    from app.services.trainings import notify

    await notify.quote_returned(db, training)
    return {"training": await _view(db, training)}


@router.post("/{training_id}/accept")
async def accept_quote(
    training_id: int, current_user: Manager, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        training = await core.accept_quote(
            db, training_id, actor=current_user, now=_now()
        )
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"training": await _view(db, training)}


# ── Umowa ────────────────────────────────────────────────────────────────────


@router.get("/{training_id}/partner")
async def partner(
    training_id: int, current_user: Manager, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        training = await core.get(db, training_id)
    except TrainingError as exc:
        raise _translate(exc) from exc
    if training.trainer_contract_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Szkolenie pracownika nie ma umowy B2B."
        )
    data = training.partner or await agreement.partner_from_contract(
        db, training.trainer_contract_id
    )
    return {
        "partner": data,
        "missing": agreement.missing_partner_fields(data),
        "company_email": current_user.email,
    }


@router.post("/{training_id}/agreement")
async def generate_agreement(
    training_id: int,
    body: AgreementBody,
    current_user: Manager,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await core.get(db, training_id, lock=True)
        await agreement.generate(
            db,
            training,
            partner=body.partner.model_dump(),
            company_email=body.company_email,
            now=_now(),
        )
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    from app.services.trainings import notify

    await notify.agreement_ready(db, training)
    return {"training": await _view(db, training)}


@router.get("/{training_id}/agreement.pdf")
async def agreement_pdf(
    training_id: int,
    current_user: Viewer,
    version: Literal["draft", "trainer", "signed"] = "draft",
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    allowed = (
        is_manager(current_user)
        or is_finance(current_user)
        or await signing.is_company_signer(db, current_user)
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, READER_ONLY)
    try:
        training = await core.get(db, training_id)
        return agreement_files.response(training, version)
    except TrainingError as exc:
        raise _translate(exc) from exc


@router.post("/{training_id}/agreement/company-signature")
async def company_signature(
    training_id: int,
    current_user: Viewer,
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    data = await _read_limited(file, MAX_INVOICE_BYTES)
    try:
        training = await signing.company_upload(
            db, training_id, data, user=current_user, now=_now()
        )
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    from app.services.trainings import notify

    await notify.agreement_signed(db, training)
    return {"training": await core.staff_view(db, training, show_fees=False)}


@router.get("/signatures/pending")
async def pending_signatures(
    current_user: Viewer, db: AsyncSession = Depends(get_db)
) -> dict:
    if not await signing.is_company_signer(db, current_user):
        return {"trainings": []}
    rows = (
        await db.scalars(select(Training).where(Training.status == "trainer_signed"))
    ).all()
    return {
        "trainings": [
            {
                "id": t.id,
                "title": t.title,
                "number": t.agreement_number,
                "trainer_name": await core.trainer_name(db, t),
                "trainer_signed_at": t.trainer_signed_at.isoformat()
                if t.trainer_signed_at
                else None,
            }
            for t in rows
        ]
    }


# ── Pliki ────────────────────────────────────────────────────────────────────


@router.post("/{training_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    training_id: int,
    current_user: Manager,
    request: Request,
    kind: Literal["recording", "internal"],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Nagranie (do 2 GB) jako surowe ciało: bramka TCM przed odczytem bajtów
    (``services/trainings/raw_upload.py``)."""

    try:
        training = await core.get(db, training_id)
        upload = raw_upload.read(request)
        stored = await storage.save(
            db,
            training_id=training.id,
            training_title=training.title,
            session_year=(training.session_date or business_today()).year,
            file_name=upload.file_name,
            content_type=upload.content_type,
            source=upload.body,
        )
        await core.add_file(
            db,
            training,
            kind=kind,
            stored=stored,
            file_name=upload.file_name,
            now=_now(),
            user_id=current_user.id,
        )
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"training": await _view(db, training)}


@router.get("/{training_id}/files/{file_id}")
async def download_file(
    training_id: int,
    file_id: int,
    request: Request,
    current_user: Reader,
    download: bool = True,
    db: AsyncSession = Depends(get_db),
) -> Response:
    item = await db.scalar(
        select(TrainingFile).where(
            TrainingFile.id == file_id, TrainingFile.training_id == training_id
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego pliku.")
    try:
        return await storage.stream(
            item, range_header=request.headers.get("range"), download=download
        )
    except TrainingError as exc:
        raise _translate(exc) from exc


@router.get("/{training_id}/files/{file_id}/ticket")
async def file_ticket(
    training_id: int,
    file_id: int,
    current_user: Reader,
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await db.scalar(
        select(TrainingFile).where(
            TrainingFile.id == file_id, TrainingFile.training_id == training_id
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego pliku.")
    return {"url": media.url(file_id, scope="own", now=_now())}


@router.post("/{training_id}/files/{file_id}/review")
async def review_file(
    training_id: int,
    file_id: int,
    body: ReviewBody,
    current_user: Manager,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await core.review_file(
            db,
            training_id,
            file_id,
            accept=body.accept,
            note=body.note,
            actor=current_user,
            now=_now(),
        )
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    from app.services.trainings import notify

    await notify.file_reviewed(db, training, accepted=body.accept)
    return {"training": await _view(db, training)}


@router.put("/{training_id}/files/{file_id}/participants")
async def file_for_participants(
    training_id: int,
    file_id: int,
    body: FlagBody,
    current_user: Manager,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await core.set_for_participants(db, training_id, file_id, value=body.value)
        training = await core.get(db, training_id)
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"training": await _view(db, training)}


# ── Zapłata i biblioteka ─────────────────────────────────────────────────────


@router.post("/{training_id}/paid")
async def mark_paid(
    training_id: int,
    body: PaidBody,
    current_user: Finance,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await core.mark_paid(
            db, training_id, actor=current_user, now=_now(), paid=body.paid
        )
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"training": await _view(db, training)}


@router.post("/{training_id}/publish")
async def publish(
    training_id: int,
    body: PublishBody,
    current_user: Manager,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        training = await core.publish(
            db, training_id, actor=current_user, now=_now(), publish_it=body.publish
        )
    except TrainingError as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"training": await _view(db, training)}


# ── Zapisy i obecność ────────────────────────────────────────────────────────


@router.get("/{training_id}/people")
async def people(
    training_id: int, current_user: Manager, db: AsyncSession = Depends(get_db)
) -> dict:
    from app.services.trainings import people as people_service

    try:
        await core.get(db, training_id)
    except TrainingError as exc:
        raise _translate(exc) from exc
    return await people_service.overview(db, training_id)


@router.post("/{training_id}/attendance")
async def import_attendance(
    training_id: int,
    current_user: Manager,
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    data = await _read_limited(file, MAX_ATTENDANCE_BYTES)
    try:
        await core.get(db, training_id, lock=True)
        rows = await attendance.match(db, attendance.parse_teams_report(data))
    except TrainingError as exc:
        raise _translate(exc) from exc
    existing = (
        await db.scalars(
            select(TrainingAttendance).where(
                TrainingAttendance.training_id == training_id
            )
        )
    ).all()
    for row in existing:
        await db.delete(row)
    for row in rows:
        db.add(
            TrainingAttendance(
                training_id=training_id,
                display_name=row.name[:255],
                email=(row.email or "")[:255],
                minutes=row.minutes,
                user_id=row.user_id,
                contract_id=row.contract_id,
            )
        )
    await db.commit()
    return {
        "imported": len(rows),
        "matched": sum(1 for r in rows if r.user_id or r.contract_id),
    }
