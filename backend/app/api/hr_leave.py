"""Urlopy i zastępstwa — wnioski, akceptacje, kalendarz zespołu, „Nieobecni dziś”.

Prefiks ``/api/hr/leave`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` (``app/api/hr_gates.py`` albo własną w tym module) i sprawdza
przełącznik modułu w ``app_settings['hr_modules']``.

* samoobsługa (kartoteka wymagana): saldo, moje wnioski, podgląd, złożenie,
  anulowanie, propozycje zastępcy, zgoda na przekierowanie poczty,
* akceptacje (przełożony swojego zespołu, Kadry i admin wszystkich — nikt
  siebie): kolejka, historia, akceptuj/odrzuć, wpis za pracownika, anulowanie;
  zastępca przełożonego, który jest dziś na urlopie, dostaje kolejkę i
  akceptuj/odrzuć dla jego podwładnych (``leave_substitute``),
* zmiana cudzego wniosku (``PATCH /approvals/{id}``: rodzaj, daty, pół dnia,
  zastępca — ``leave_edit``) i wyłączenie przekierowania poczty przez Kadry
  z powodem (``POST /approvals/{id}/forward-off``),
* zgłoszenia z B2B i zlecenia (D5, 17.10.2026): wchodzą od razu, koordynator
  widzi je „do wiadomości” obok kolejki (``reported`` w ``/approvals/pending``)
  i może zgłosić kolizję (``POST /{id}/conflict``) — bez akceptacji i odrzucenia,
* załącznik do wniosku (potwierdzenie nieobecności w e-teczce, ``leave_proofs``):
  osoba dołącza, pobiera i usuwa własny plik (``/requests/{id}/proofs``),
  Kadry pobierają (``/approvals/{id}/proofs/{doc}/file``, bramka
  ``require_hr_leave_proof_reader``); przełożony widzi tylko ``proof_count``,
* kalendarz zespołu (osoby z kartoteką i uprawnienia „Ludzi”),
* „Nieobecni dziś” i odczyt zbiorczy dla plakietki — każdy aktywny pracownik
  wewnętrzny, także rekruter bez kartoteki. Bez rodzaju nieobecności (D6).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import (
    ensure_module,
    require_hr_people_reader,
    require_hr_self_service,
)
from app.core.database import get_db
from app.core.http_headers import content_disposition, safe_document_disposition
from app.core.scheduling import business_today
from app.models.hr_document import HrDocument
from app.models.hr_leave import LeaveRequest
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.hr import absence as absence_service
from app.services.hr import audit
from app.services.hr import documents, leave_proofs
from app.services.hr import leave_edit
from app.services.hr import leave_service as service
from app.services.hr import leave_substitute
from app.services.hr import people
from app.services.hr.leave_balance import balance_payload
from app.services.hr.leave_calendar import team_calendar
from app.services.hr.leave_context import candidate_payload, substitute_candidates
from app.services.hr.leave_policy import LeavePolicyError
from app.services.hr.leave_queries import history_counts, mask_for_viewer
from app.services.hr.modules import HrModule, load_modules, module_open_for
from app.services.hr_leave_schema import LEAVE_STATUSES
from app.services.permission_denial import ensure_any_permission

router = APIRouter()

MODULE = HrModule.leave
APPROVER_DETAIL = "Akceptacje widzą przełożeni i Kadry."
INTERNAL_DETAIL = "Nieobecności widzą pracownicy firmy."
#: Konta, które nie są ludźmi zatrudnionymi w firmie (jak w „Dodaj osobę”).
_NOT_STAFF = {UserRole.automation, UserRole.user, UserRole.board}
_MAX_BADGE_USERS = 300


def require_hr_leave_approver():
    """Przełożony (ma podwładnych z kartoteką), Kadry albo admin — i zastępca
    przełożonego, który jest dziś na urlopie (podwładni tego przełożonego)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if await service.is_leave_approver(db, current_user):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, APPROVER_DETAIL)

    return _check


def require_hr_absence_reader():
    """Każdy aktywny pracownik wewnętrzny (bez kont technicznych i podglądu)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if current_user.has_role(UserRole.admin):
            return current_user
        if not set(current_user.get_all_roles()) - _NOT_STAFF:
            raise HTTPException(status.HTTP_403_FORBIDDEN, INTERNAL_DETAIL)
        return current_user

    return _check


def require_hr_leave_proof_reader():
    """Moduł urlopów włączony i uprawnienie „Kadry” (admin ma je zawsze) —
    treść załącznika do cudzego wniosku. Przełożony widzi tylko, że jest (D6)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        ensure_any_permission(current_user, ProductAction.people_admin)
        return current_user

    _check.required_permissions = (ProductAction.people_admin,)
    return _check


LeaveSelf = Annotated[User, Depends(require_hr_self_service(MODULE))]
LeaveApprover = Annotated[User, Depends(require_hr_leave_approver())]
LeaveCalendarReader = Annotated[User, Depends(require_hr_people_reader(module=MODULE))]
AbsenceReader = Annotated[User, Depends(require_hr_absence_reader())]
LeaveProofReader = Annotated[User, Depends(require_hr_leave_proof_reader())]

HalfDay = Literal["morning", "afternoon"]


class LeaveFields(BaseModel):
    leave_type: str = Field(min_length=1, max_length=24)
    start_date: date
    end_date: date
    half_day: Optional[HalfDay] = None
    note: Optional[str] = Field(default=None, max_length=2000)
    substitute_user_id: Optional[int] = None
    # Kto wrzuca do Cpro w tym czasie — tylko wniosek osoby od Cpro (29.10.2026).
    cpro_substitute_user_id: Optional[int] = None


class LeaveIn(LeaveFields):
    forward_mail_consent: bool = False
    oof_internal_message: Optional[str] = Field(default=None, max_length=4000)
    oof_external_message: Optional[str] = Field(default=None, max_length=4000)


class OnBehalfIn(LeaveFields):
    """Wpis za pracownika — bez zgody na przekierowanie i bez tekstów OOF.

    ``extra='forbid'``: zgoda na przekierowanie poczty należy do osoby;
    przesłana przez przełożonego kończy się 422, a nie cichym pominięciem.
    """

    model_config = ConfigDict(extra="forbid")
    user_id: int


class PreviewOnBehalfIn(LeaveFields):
    user_id: int


class DecisionIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class RejectIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class LeaveCancelIn(BaseModel):
    """Powód cofnięcia — wymagany od pierwszego dnia (3–500 znaków, polskie
    komunikaty z ``leave_policy.approver_cancel_refusal``)."""

    reason: Optional[str] = Field(default=None, max_length=2000)


class ConsentIn(BaseModel):
    consent: bool


class ConflictIn(BaseModel):
    note: str = Field(min_length=1, max_length=service.CONFLICT_NOTE_MAX)


class EditIn(BaseModel):
    """Zmiana wniosku — pole pominięte zostaje; ``null`` czyści pół dnia
    i zastępcę. Zgody na przekierowanie ani tekstów OOF tu nie ma (należą do
    osoby)."""

    model_config = ConfigDict(extra="forbid")
    leave_type: Optional[str] = Field(default=None, min_length=1, max_length=24)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    half_day: Optional[HalfDay] = None
    substitute_user_id: Optional[int] = None


class ForwardOffIn(BaseModel):
    reason: str = Field(min_length=1, max_length=leave_edit.FORWARD_REASON_MAX)


def _input(payload: LeaveFields) -> service.LeaveInput:
    return service.LeaveInput(
        leave_type=payload.leave_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        half_day=payload.half_day,
        note=payload.note,
        substitute_user_id=payload.substitute_user_id,
        cpro_substitute_user_id=payload.cpro_substitute_user_id,
        forward_mail_consent=getattr(payload, "forward_mail_consent", False),
        oof_internal_message=getattr(payload, "oof_internal_message", None),
        oof_external_message=getattr(payload, "oof_external_message", None),
    )


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, LeavePolicyError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if isinstance(exc, service.LeaveConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, service.LeaveForbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    return HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego wniosku.")


_HANDLED = (
    LeavePolicyError,
    service.LeaveConflict,
    service.LeaveForbidden,
    service.LeaveNotFound,
)


async def _one(
    db: AsyncSession, request, viewer: User, locked_months: tuple[str, ...] = ()
) -> dict:
    """Wiersz wniosku + ostrzeżenie o zamkniętym miesiącu płac (godziny
    w nim zostały bez zmian; Płace dostały dzwonek)."""

    await db.refresh(request)
    today = business_today()
    item = (await service.serialize(db, [request], viewer=viewer, today=today))[0]
    await mask_for_viewer(db, item, request, viewer, today)
    item["payroll_locked_months"] = list(locked_months)
    item["payroll_warning"] = service.payroll_locked_warning(locked_months)
    return item


async def _outcome(
    db: AsyncSession, outcome: service.LeaveOutcome, viewer: User
) -> dict:
    return await _one(db, outcome.request, viewer, outcome.payroll_locked_months)


async def _own_profile(db: AsyncSession, user: User):
    profile = await people.profile_of(db, user.id)
    if profile is None:  # bramka samoobsługi już to sprawdziła
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak kartoteki w NEXUSIE.")
    return profile


# ── Samoobsługa ───────────────────────────────────────────────────────────────


@router.get("/balance")
async def my_balance(
    current_user: LeaveSelf,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
) -> dict:
    profile = await _own_profile(db, current_user)
    today = business_today()
    return await balance_payload(
        db,
        user_id=current_user.id,
        year=year or today.year,
        employment_type=profile.employment_type,
        today=today,
    )


@router.get("/my-requests")
async def my_requests(
    current_user: LeaveSelf, db: AsyncSession = Depends(get_db)
) -> dict:
    items = await service.my_requests(db, user=current_user, today=business_today())
    return {"items": items, "total": len(items)}


@router.post("/preview")
async def preview_request(
    payload: LeaveIn, current_user: LeaveSelf, db: AsyncSession = Depends(get_db)
) -> dict:
    profile = await _own_profile(db, current_user)
    return await service.preview(
        db, subject=current_user, profile=profile, data=_input(payload), for_self=True
    )


@router.post("/requests", status_code=status.HTTP_201_CREATED)
async def submit_request(
    payload: LeaveIn, current_user: LeaveSelf, db: AsyncSession = Depends(get_db)
) -> dict:
    profile = await _own_profile(db, current_user)
    try:
        outcome = await service.submit(
            db,
            actor=current_user,
            subject=current_user,
            profile=profile,
            data=_input(payload),
            on_behalf=False,
            today=business_today(),
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _outcome(db, outcome, current_user)


@router.post("/requests/{request_id}/cancel")
async def cancel_my_request(
    request_id: uuid.UUID, current_user: LeaveSelf, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        outcome = await service.cancel_own(
            db, actor=current_user, request_id=request_id, today=business_today()
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _outcome(db, outcome, current_user)


@router.put("/requests/{request_id}/forward-consent")
async def set_forward_consent(
    request_id: uuid.UUID,
    payload: ConsentIn,
    current_user: LeaveSelf,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        request = await service.set_forward_consent(
            db,
            actor=current_user,
            request_id=request_id,
            consent=payload.consent,
            today=business_today(),
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _one(db, request, current_user)


# ── Załącznik do wniosku (potwierdzenie nieobecności) ────────────────────────


async def _own_request(
    db: AsyncSession, request_id: uuid.UUID, user: User
) -> LeaveRequest:
    request = await db.get(LeaveRequest, request_id)
    if request is None or request.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego wniosku.")
    return request


def _proof_error(exc: documents.HrDocumentError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


def _proof_file(db: AsyncSession, document: HrDocument, actor: User) -> FileResponse:
    try:
        path = documents.file_of(document)
    except documents.HrDocumentError as exc:
        raise _proof_error(exc) from None
    # Ten sam ślad co pobranie z e-teczki (`hr_documents.document_file`, audyt
    # 21.10.2026); zapisuje go commit sesji żądania przed wysłaniem pliku.
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=document.user_id,
        entity_type="hr_document",
        entity_id=document.id,
        action="document_downloaded",
        details={"kind": document.kind},
        sensitivity="health" if document.kind == documents.ABSENCE_PROOF else "general",
    )
    return FileResponse(
        path,
        media_type=document.mime,
        headers={
            "Content-Disposition": content_disposition(
                documents.download_name(document),
                safe_document_disposition(document.mime, "attachment"),
            )
        },
    )


@router.post("/requests/{request_id}/proofs", status_code=status.HTTP_201_CREATED)
async def attach_proof(
    request_id: uuid.UUID,
    current_user: LeaveSelf,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    request = await _own_request(db, request_id, current_user)
    content = await file.read(leave_proofs.MAX_PROOF_BYTES + 1)
    try:
        await leave_proofs.attach(
            db,
            request=request,
            content=content,
            file_name=file.filename,
            actor=current_user,
        )
    except documents.HrDocumentError as exc:
        await db.rollback()
        raise _proof_error(exc) from None
    await db.commit()
    return await _one(db, request, current_user)


@router.get("/requests/{request_id}/proofs/{document_id}/file")
async def own_proof_file(
    request_id: uuid.UUID,
    document_id: int,
    current_user: LeaveSelf,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    request = await _own_request(db, request_id, current_user)
    try:
        document = await leave_proofs.proof_of(db, request, document_id)
    except documents.HrDocumentError as exc:
        raise _proof_error(exc) from None
    return _proof_file(db, document, current_user)


@router.post("/requests/{request_id}/proofs/{document_id}/remove")
async def remove_own_proof(
    request_id: uuid.UUID,
    document_id: int,
    current_user: LeaveSelf,
    db: AsyncSession = Depends(get_db),
) -> dict:
    request = await _own_request(db, request_id, current_user)
    try:
        document = await leave_proofs.proof_of(db, request, document_id)
        orphan = await leave_proofs.remove_own(
            db, request, document, actor=current_user
        )
    except documents.HrDocumentError as exc:
        await db.rollback()
        raise _proof_error(exc) from None
    await db.commit()
    documents.delete_files([orphan])
    return await _one(db, request, current_user)


def _period(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Data końca nie może być przed datą początku.",
        )
    if (end - start).days > 366:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Okres może obejmować najwyżej rok."
        )


@router.get("/substitutes")
async def my_substitutes(
    current_user: LeaveSelf,
    start_date: date,
    end_date: date,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _period(start_date, end_date)
    profile = await _own_profile(db, current_user)
    found = await substitute_candidates(
        db,
        subject=current_user,
        department=profile.department,
        start=start_date,
        end=end_date,
    )
    return {"items": [candidate_payload(c) for c in found]}


# ── Akceptacje ────────────────────────────────────────────────────────────────


@router.get("/approvals/pending")
async def approvals_pending(
    current_user: LeaveApprover, db: AsyncSession = Depends(get_db)
) -> dict:
    today = business_today()
    items = await service.pending_queue(db, actor=current_user, today=today)
    return {
        "items": items,
        "total": len(items),
        # Kogo patrzący zastępuje dziś („W zastępstwie za …” nad kolejką).
        "covering": await leave_substitute.covering_payload(db, current_user.id, today),
        # Zgłoszenia z B2B i zlecenia do wiadomości (D5) — poza licznikiem decyzji.
        "reported": await service.reported_queue(db, actor=current_user, today=today),
    }


@router.get("/approvals/history")
async def approvals_history(
    current_user: LeaveApprover,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    user_id: Optional[int] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    if status_filter is not None and status_filter not in LEAVE_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nieznany status.")
    items = await service.history(
        db,
        actor=current_user,
        today=business_today(),
        status=status_filter,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    # Liczniki przy filtrach statusu: ten sam zakres i filtry bez statusu.
    counts = await history_counts(
        db,
        actor=current_user,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )
    return {"items": items, "total": len(items), "counts": counts}


@router.get("/approvals/people")
async def approvals_people(
    current_user: LeaveApprover, db: AsyncSession = Depends(get_db)
) -> dict:
    return {"items": await service.on_behalf_people(db, actor=current_user)}


@router.get("/approvals/substitutes")
async def approvals_substitutes(
    current_user: LeaveApprover,
    user_id: int,
    start_date: date,
    end_date: date,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _period(start_date, end_date)
    try:
        subject, profile = await service.subject_for_on_behalf(
            db, actor=current_user, user_id=user_id
        )
    except _HANDLED as exc:
        raise _translate(exc) from exc
    found = await substitute_candidates(
        db,
        subject=subject,
        department=profile.department,
        start=start_date,
        end=end_date,
    )
    return {"items": [candidate_payload(c) for c in found]}


@router.post("/approvals/preview")
async def approvals_preview(
    payload: PreviewOnBehalfIn,
    current_user: LeaveApprover,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        subject, profile = await service.subject_for_on_behalf(
            db, actor=current_user, user_id=payload.user_id
        )
    except _HANDLED as exc:
        raise _translate(exc) from exc
    return await service.preview(
        db, subject=subject, profile=profile, data=_input(payload), for_self=False
    )


@router.post("/approvals/on-behalf", status_code=status.HTTP_201_CREATED)
async def enter_on_behalf(
    payload: OnBehalfIn, current_user: LeaveApprover, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        subject, profile = await service.subject_for_on_behalf(
            db, actor=current_user, user_id=payload.user_id
        )
        outcome = await service.submit(
            db,
            actor=current_user,
            subject=subject,
            profile=profile,
            data=_input(payload),
            on_behalf=True,
            today=business_today(),
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _outcome(db, outcome, current_user)


@router.post("/approvals/{request_id}/approve")
async def approve_request(
    request_id: uuid.UUID,
    current_user: LeaveApprover,
    payload: Optional[DecisionIn] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        outcome = await service.approve(
            db,
            actor=current_user,
            request_id=request_id,
            note=payload.note if payload else None,
            today=business_today(),
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _outcome(db, outcome, current_user)


@router.post("/approvals/{request_id}/reject")
async def reject_request(
    request_id: uuid.UUID,
    payload: RejectIn,
    current_user: LeaveApprover,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        request = await service.reject(
            db,
            actor=current_user,
            request_id=request_id,
            note=payload.note,
            today=business_today(),
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _one(db, request, current_user)


@router.post("/approvals/{request_id}/cancel")
async def cancel_team_request(
    request_id: uuid.UUID,
    current_user: LeaveApprover,
    payload: Optional[LeaveCancelIn] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        outcome = await service.cancel_as_approver(
            db,
            actor=current_user,
            request_id=request_id,
            today=business_today(),
            reason=payload.reason if payload else None,
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _outcome(db, outcome, current_user)


def _changes(payload: EditIn) -> leave_edit.LeaveChanges:
    sent = payload.model_fields_set
    values: dict = {}
    for name in ("leave_type", "start_date", "end_date"):
        if name in sent and getattr(payload, name) is not None:
            values[name] = getattr(payload, name)
    for name in ("half_day", "substitute_user_id"):
        if name in sent:
            values[name] = getattr(payload, name)
    return leave_edit.LeaveChanges(**values)


@router.patch("/approvals/{request_id}")
async def edit_team_request(
    request_id: uuid.UUID,
    payload: EditIn,
    current_user: LeaveApprover,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Przełożony albo Kadry zmieniają rodzaj, daty, pół dnia albo zastępcę."""

    try:
        outcome = await leave_edit.edit_request(
            db,
            actor=current_user,
            request_id=request_id,
            changes=_changes(payload),
            today=business_today(),
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _outcome(db, outcome, current_user)


@router.post("/approvals/{request_id}/forward-off")
async def forward_off(
    request_id: uuid.UUID,
    payload: ForwardOffIn,
    current_user: LeaveApprover,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Kadry wyłączają przekierowanie poczty cudzego wniosku (powód w śladzie)."""

    try:
        request = await leave_edit.forward_off_by_hr(
            db,
            actor=current_user,
            request_id=request_id,
            reason=payload.reason,
            today=business_today(),
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _one(db, request, current_user)


@router.get("/approvals/{request_id}/proofs/{document_id}/file")
async def team_proof_file(
    request_id: uuid.UUID,
    document_id: int,
    current_user: LeaveProofReader,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Kadry pobierają załącznik cudzego wniosku (przy akceptacji i w historii)."""

    request = await db.get(LeaveRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego wniosku.")
    try:
        document = await leave_proofs.proof_of(db, request, document_id)
    except documents.HrDocumentError as exc:
        raise _proof_error(exc) from None
    return _proof_file(db, document, current_user)


@router.post("/{request_id}/conflict")
async def report_conflict(
    request_id: uuid.UUID,
    payload: ConflictIn,
    current_user: LeaveApprover,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Koordynator zgłasza kolizję zgłoszonej przerwy z pracą (D5)."""

    try:
        request = await service.report_conflict(
            db,
            actor=current_user,
            request_id=request_id,
            note=payload.note,
            today=business_today(),
        )
    except _HANDLED as exc:
        await db.rollback()
        raise _translate(exc) from exc
    await db.commit()
    return await _one(db, request, current_user)


# ── Kalendarz zespołu i nieobecni ─────────────────────────────────────────────


@router.get("/calendar")
async def calendar_month(
    current_user: LeaveCalendarReader,
    db: AsyncSession = Depends(get_db),
    month: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    department: Optional[str] = Query(default=None, max_length=200),
    team: bool = Query(default=False),
) -> dict:
    today = business_today()
    year, month_no = today.year, today.month
    if month:
        year, month_no = int(month[:4]), int(month[5:])
        if not (2020 <= year <= 2100 and 1 <= month_no <= 12):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Nieznany miesiąc."
            )
    return await team_calendar(
        db,
        viewer=service.actor_of(current_user),
        year=year,
        month=month_no,
        department=department or None,
        team_only=team,
        today=today,
        # Praca zdalna i delegacja to dane modułu czasu — tylko gdy jest otwarty.
        with_presence=module_open_for(
            current_user, await load_modules(db), HrModule.time
        ),
    )


@router.get("/absent-today")
async def absent_today(
    current_user: AbsenceReader, db: AsyncSession = Depends(get_db)
) -> dict:
    today = business_today()
    found = await absence_service.absent_on(db, today)
    names = await service.names_of(db, {a.user_id for a in found})
    busy = {a.user_id for a in found}
    items = [
        {
            "user_id": a.user_id,
            "name": names.get(a.user_id),
            "until": a.until.isoformat(),
            "half_day": a.half_day,
            "substitute_user_id": a.substitute_user_id,
            "substitute_name": a.substitute_name,
            "substitute_absent": a.substitute_user_id in busy,
            "i_substitute": a.substitute_user_id == current_user.id,
            "is_me": a.user_id == current_user.id,
        }
        for a in found
    ]
    items.sort(key=lambda item: (not item["i_substitute"], item["name"] or ""))
    return {"date": today.isoformat(), "items": items, "total": len(items)}


def _parse_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or len(part) > 9:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "user_ids to lista numerów oddzielonych przecinkami.",
            )
        ids.append(int(part))
    if len(ids) > _MAX_BADGE_USERS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Najwyżej {_MAX_BADGE_USERS} osób w jednym zapytaniu.",
        )
    return ids


@router.get("/absence")
async def absence_for_people(
    current_user: AbsenceReader,
    db: AsyncSession = Depends(get_db),
    user_ids: str = Query(default="", max_length=4000),
    on: Optional[date] = Query(default=None),
) -> dict:
    day = on or business_today()
    found = await absence_service.absences_on(db, _parse_ids(user_ids), day)
    return {
        "on": day.isoformat(),
        "items": [
            {
                "user_id": a.user_id,
                "until": a.until.isoformat(),
                "half_day": a.half_day,
                "substitute_user_id": a.substitute_user_id,
                "substitute_name": a.substitute_name,
            }
            for a in sorted(found.values(), key=lambda a: a.user_id)
        ],
    }
