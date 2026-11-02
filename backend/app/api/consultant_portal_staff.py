"""Portal konsultanta od strony back office'u: FAQ, Rozmowy, Jakość, dokumenty, wyłącznik.

Prefiks ``/api/back-office/portal`` (wpięty w ``app/main.py`` za ``_HR_PROGRAM``). Bramki
``require_hr_*`` jak w ``api/back_office.py``: moduł ``back_office`` wyłączony = 404.

Reguły, których macierz uprawnień nie widzi, bo siedzą w treści odpowiedzi, a nie w bramce:

* transkrypt widzi prowadzący, kierownik i osoba prowadząca sprawę,
* ocenę rozmowy widzi kierownik, a nigdy osoba oceniana, także gdy sama jest kierownikiem,
* osoba oceniana dostaje przegląd miesięczny w zbiorczych liczbach.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.back_office import BackOfficeLead, BackOfficeMember
from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase
from app.models.back_office import BoCard
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.consultant_portal import CpDocument, CpFaqItem, CpMeeting, CpRating
from app.models.contract import Contract
from app.models.user import User, UserRole
from app.services.back_office import access, sync
from app.services.care.access import full_name
from app.services.consultant_portal import (
    content,
    documents,
    mailbox,
    meetings,
    portal_settings,
    ratings,
)
from app.services.consultant_portal.auth import PortalError
from app.services.consultant_portal.sms import current_sender
from app.services.consultant_portal_schema import (
    COMMENT_MAX,
    QUESTION_MAX,
    STATES,
    TOPICS,
)
from app.services.hr import audit
from app.services.hr.modules import HrModule

router = APIRouter()

FINANCE_ONLY = "To może zrobić zespół Finansów albo kierownik back office."
ADMIN_ONLY = "Wyłącznik portalu zmienia administrator."
FAQ_NOT_FOUND = "Nie ma takiego pytania."
MEETING_NOT_FOUND = "Nie ma takiej rozmowy."
CARD_NOT_FOUND = "Nie ma takiej karty."

Topic = Literal["invoice", "contract", "leave", "access", "next", "data"]
assert set(Topic.__args__) == set(TOPICS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _translate(exc: PortalError) -> HTTPException:
    return HTTPException(exc.status, {"message": exc.message, "code": exc.code})


def require_hr_portal_finance():
    """Zespół Finansów albo kierownik, przy włączonym module."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.back_office)
        if not (await access.load_viewer(db, current_user)).owns("finance"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, FINANCE_ONLY)
        return current_user

    return _check


def require_hr_portal_switch():
    """Wyłącznik portalu to decyzja o wysyłce do ludzi spoza firmy: tylko admin."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.back_office)
        if not current_user.has_role(UserRole.admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_ONLY)
        return current_user

    return _check


PortalFinance = Annotated[User, Depends(require_hr_portal_finance())]
PortalSwitch = Annotated[User, Depends(require_hr_portal_switch())]


# ── Stan i wyłącznik ─────────────────────────────────────────────────────────


@router.get("/status")
async def portal_status(
    current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    state = await portal_settings.load(db)
    viewer = await access.load_viewer(db, current_user)
    return {
        "state": state.state,
        "pilot_contract_ids": sorted(state.pilot_contract_ids)
        if viewer.is_lead
        else [],
        "booking_ready": meetings.booking_ready(),
        "sms_available": current_sender().available,
        "mailbox": await mailbox.status(db) if viewer.owns("finance") else None,
        "viewer": {"is_lead": viewer.is_lead, "user_id": viewer.user_id},
    }


class SwitchBody(BaseModel):
    state: Literal["off", "pilot", "all"]
    pilot_contract_ids: list[int] = Field(default_factory=list, max_length=500)


assert set(SwitchBody.model_fields["state"].annotation.__args__) == set(STATES)


@router.put("/settings")
async def save_settings(
    body: SwitchBody, current_user: PortalSwitch, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    saved = await portal_settings.save(
        db, state=body.state, pilot_contract_ids=body.pilot_contract_ids
    )
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="consultant_portal",
        entity_id=0,
        action="portal_switch_changed",
        details={"state": saved.state, "pilot": len(saved.pilot_contract_ids)},
    )
    return saved.as_dict()


# ── FAQ ──────────────────────────────────────────────────────────────────────


def _faq_row(item: CpFaqItem) -> dict[str, Any]:
    return {**content.faq_row(item), "published": item.published}


@router.get("/faq")
async def list_faq(
    current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    items = (
        await db.scalars(
            select(CpFaqItem).order_by(
                CpFaqItem.topic, CpFaqItem.position, CpFaqItem.id
            )
        )
    ).all()
    return {
        "items": [_faq_row(item) for item in items],
        "topics": [{"key": key, "label": content.TOPIC_LABELS[key]} for key in TOPICS],
    }


class FaqBody(BaseModel):
    topic: Topic
    question: str = Field(min_length=3, max_length=QUESTION_MAX)
    answer: str = Field(min_length=3, max_length=content.ANSWER_MAX)
    position: int = Field(default=0, ge=0, le=999)
    published: bool = True


@router.post("/faq", status_code=status.HTTP_201_CREATED)
async def create_faq(
    body: FaqBody, current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        question, answer = content.clean_faq(body.question, body.answer)
    except PortalError as exc:
        raise _translate(exc) from exc
    item = CpFaqItem(
        topic=body.topic,
        question=question,
        answer=answer,
        position=body.position,
        published=body.published,
        updated_by=current_user.id,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return _faq_row(item)


@router.put("/faq/{item_id}")
async def update_faq(
    item_id: int,
    body: FaqBody,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    item = await db.get(CpFaqItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, FAQ_NOT_FOUND)
    try:
        item.question, item.answer = content.clean_faq(body.question, body.answer)
    except PortalError as exc:
        raise _translate(exc) from exc
    item.topic = body.topic
    item.position = body.position
    item.published = body.published
    item.updated_by = current_user.id
    item.updated_at = _now()
    return _faq_row(item)


@router.delete("/faq/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    item_id: int, current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> None:
    item = await db.get(CpFaqItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, FAQ_NOT_FOUND)
    await db.delete(item)


# ── Rozmowy ──────────────────────────────────────────────────────────────────


def _meeting_filter(viewer: access.Viewer):
    """Kierownik widzi wszystko; reszta swoje rozmowy i rozmowy ze swoich spraw."""

    if viewer.is_lead:
        return None
    return or_(
        CpMeeting.host_user_id == viewer.user_id,
        AdminCase.assignee_user_id == viewer.user_id,
    )


def _rating_payload(
    rating: Optional[CpRating], meeting: CpMeeting, viewer: access.Viewer
) -> Optional[dict[str, Any]]:
    if rating is None or not viewer.is_lead or meeting.host_user_id == viewer.user_id:
        return None
    return {
        "score": rating.score,
        "resolved": rating.resolved,
        "comment": rating.comment,
        "followup_status": rating.followup_status,
    }


def _meeting_base():
    return (
        select(
            CpMeeting,
            CpRating,
            User.name,
            Candidate.name,
            Candidate.lastname,
            Client.display_name,
            Client.name,
        )
        .outerjoin(AdminCase, AdminCase.id == CpMeeting.case_id)
        .outerjoin(CpRating, CpRating.meeting_id == CpMeeting.id)
        .outerjoin(User, User.id == CpMeeting.host_user_id)
        .join(Contract, Contract.id == CpMeeting.contract_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Client, Client.id == Contract.client_id)
        .where(CpMeeting.status.in_(("booked", "cancelled")))
    )


def _meeting_row(row: Any, viewer: access.Viewer) -> dict[str, Any]:
    meeting, rating, host, first, last, client_display, client_name = row
    return {
        "id": meeting.id,
        "consultant": full_name(first, last),
        "client": client_display or client_name,
        "host": host,
        "host_user_id": meeting.host_user_id,
        "topic": meeting.topic,
        "topic_label": content.TOPIC_LABELS[meeting.topic],
        "reason": meeting.reason or None,
        "start_at": meeting.start_at.isoformat(),
        "end_at": meeting.end_at.isoformat(),
        "status": meeting.status,
        "case_id": meeting.case_id,
        "transcript_status": meeting.transcript_status,
        "summary_status": meeting.summary_status,
        "rating": _rating_payload(rating, meeting, viewer),
    }


@router.get("/meetings")
async def list_meetings(
    current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    viewer = await access.load_viewer(db, current_user)
    statement = _meeting_base().order_by(CpMeeting.start_at.desc()).limit(200)
    scope = _meeting_filter(viewer)
    if scope is not None:
        statement = statement.where(scope)
    rows = (await db.execute(statement)).all()
    return {"items": [_meeting_row(row, viewer) for row in rows]}


@router.get("/meetings/{meeting_id}")
async def meeting_detail(
    meeting_id: int,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    viewer = await access.load_viewer(db, current_user)
    statement = _meeting_base().where(CpMeeting.id == meeting_id)
    scope = _meeting_filter(viewer)
    if scope is not None:
        statement = statement.where(scope)
    row = (await db.execute(statement)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MEETING_NOT_FOUND)
    meeting: CpMeeting = row[0]
    return {
        **_meeting_row(row, viewer),
        "summary": meeting.summary,
        "action_items": meeting.action_items or [],
        "transcript": meeting.transcript_text,
        "transcript_purged": meeting.transcript_purged_at is not None,
    }


# ── Jakość ───────────────────────────────────────────────────────────────────


@router.get("/quality")
async def quality(
    current_user: BackOfficeLead, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await ratings.quality(db, viewer_id=current_user.id, now=_now())


@router.get("/quality/my-review")
async def my_review(
    current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await ratings.my_review(db, user_id=current_user.id, today=business_today())


class TaskBody(BaseModel):
    note: str = Field(default="", max_length=COMMENT_MAX)


@router.post("/quality/tasks/{rating_id}/close")
async def close_task(
    rating_id: int,
    body: TaskBody,
    current_user: BackOfficeLead,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        rating = await ratings.close_task(
            db, rating_id, viewer_id=current_user.id, note=body.note, now=_now()
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return {"id": rating.id, "followup_status": rating.followup_status}


# ── Dokumenty ────────────────────────────────────────────────────────────────


async def _after_decision(db: AsyncSession, document: CpDocument) -> dict[str, Any]:
    """Karta zamyka się od razu; pętla i tak by to domknęła po kilku minutach."""

    await sync.sync_kinds(db, ["document"], today=business_today())
    return documents.staff_row(document)


@router.get("/documents/by-card/{card_id}")
async def documents_of_card(
    card_id: int, current_user: PortalFinance, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    card = await db.get(BoCard, card_id)
    if card is None or card.source_kind != "document":
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARD_NOT_FOUND)
    ids = [
        value
        for value in (card.meta or {}).get("document_ids", [])
        if isinstance(value, int)
    ]
    rows = (
        await db.scalars(
            select(CpDocument).where(CpDocument.id.in_(ids)).order_by(CpDocument.id)
        )
    ).all()
    return {"items": [documents.staff_row(row) for row in rows]}


@router.get("/documents/{document_id}/file")
async def document_file(
    document_id: int, current_user: PortalFinance, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    document = await db.get(CpDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, documents.NOT_FOUND)
    try:
        path = documents.path_for(document.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, documents.NOT_FOUND) from exc
    name = document.file_name or f"dokument-{document.id}"
    return FileResponse(
        path,
        media_type=document.mime,
        headers={"Content-Disposition": content_disposition(name, "attachment")},
    )


@router.post("/documents/{document_id}/accept")
async def accept_document(
    document_id: int, current_user: PortalFinance, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        document = await documents.accept(
            db, document_id, actor_id=current_user.id, now=_now()
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return await _after_decision(db, document)


class RejectBody(BaseModel):
    reason: str = Field(min_length=3, max_length=COMMENT_MAX)


@router.post("/documents/{document_id}/reject")
async def reject_document(
    document_id: int,
    body: RejectBody,
    current_user: PortalFinance,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        document = await documents.reject(
            db, document_id, actor_id=current_user.id, reason=body.reason, now=_now()
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return await _after_decision(db, document)


@router.post("/documents/{document_id}/paid")
async def paid_document(
    document_id: int, current_user: PortalFinance, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        document = await documents.mark_paid(
            db, document_id, actor_id=current_user.id, now=_now()
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return documents.staff_row(document)


class AssignBody(BaseModel):
    contract_id: int = Field(gt=0)


@router.post("/documents/{document_id}/assign")
async def assign_document(
    document_id: int,
    body: AssignBody,
    current_user: PortalFinance,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        document = await documents.assign_contract(
            db, document_id, contract_id=body.contract_id, now=_now()
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    return await _after_decision(db, document)
