"""Opieka → Komunikaty: komunikaty do konsultantów (O12, makiety M7–M8).

Prefiks ``/api/care/announcements`` (wpina koordynator w ``app/main.py``).
Bramka ``require_hr_announcements_user``: włączony moduł opieki i autor
komunikatów — opiekun (TCM) albo Delivery Lead z dostępem do Delivery, head
back office albo admin. Zakres klientów Delivery Leada pilnuje serwis
(cudzy klient → 403). Zatwierdza head back office albo admin, nigdy autor;
przełącznik wysyłki zmienia tylko admin. Reguły: ``services/care/announcements.py``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.models.user import User
from app.services.care import announcement_audience as audience_svc
from app.services.care import announcements as service
from app.services.hr.modules import HrModule

router = APIRouter()

Kind = Literal["mandatory", "informational"]


def require_hr_announcements_user():
    """Autor komunikatów (opiekun, DL, head back office, admin) i włączony moduł."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.care)
        is_head = (await service.back_office_head_id(db)) == current_user.id
        if not service.may_author(current_user, is_head=is_head):
            raise HTTPException(status.HTTP_403_FORBIDDEN, service.AUTHOR_DENIED)
        return current_user

    return _check


AnnouncementsUser = Annotated[User, Depends(require_hr_announcements_user())]


class AnnouncementIn(BaseModel):
    kind: Kind
    subject: str = Field(max_length=1000)
    body: str = Field(max_length=50_000)
    audience: dict[str, Any]


class AnnouncementPatch(BaseModel):
    kind: Optional[Kind] = None
    subject: Optional[str] = Field(default=None, max_length=1000)
    body: Optional[str] = Field(default=None, max_length=50_000)
    audience: Optional[dict[str, Any]] = None


class PreviewIn(BaseModel):
    kind: Kind
    audience: dict[str, Any]
    # Podgląd istniejącego komunikatu liczy w zakresie jego autora — tak jak
    # wysyłka (admin przy szkicu Delivery Leada).
    announcement_id: Optional[int] = Field(default=None, ge=1)


class ReturnIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class SettingsIn(BaseModel):
    sending_enabled: bool


def _refuse(exc: service.AnnouncementError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


async def _actor(db: AsyncSession, user: User) -> service.Actor:
    return await service.actor_for(db, user)


@router.get("")
async def list_announcements(
    current_user: AnnouncementsUser, db: AsyncSession = Depends(get_db)
) -> dict:
    actor = await _actor(db, current_user)
    return {
        "items": await service.list_for(db, actor),
        "me": {
            "user_id": current_user.id,
            "can_author": True,
            "can_approve": actor.can_approve,
            "is_admin": actor.is_admin,
        },
        "settings": service.settings_payload(await service.sending_enabled(db)),
    }


@router.get("/options")
async def audience_options(
    current_user: AnnouncementsUser, db: AsyncSession = Depends(get_db)
) -> dict:
    actor = await _actor(db, current_user)
    return await audience_svc.options(db, actor.allowed)


@router.post("/preview")
async def preview_audience(
    payload: PreviewIn,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(db, current_user)
    try:
        return await service.preview(
            db,
            actor,
            kind=payload.kind,
            audience=payload.audience,
            announcement_id=payload.announcement_id,
        )
    except service.AnnouncementError as exc:
        raise _refuse(exc) from exc


@router.put("/settings")
async def update_settings(
    payload: SettingsIn,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(db, current_user)
    try:
        return await service.set_sending(db, actor, payload.sending_enabled)
    except service.AnnouncementError as exc:
        raise _refuse(exc) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_announcement(
    payload: AnnouncementIn,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(db, current_user)
    try:
        announcement = await service.create(
            db,
            actor,
            kind=payload.kind,
            subject=payload.subject,
            body=payload.body,
            audience=payload.audience,
        )
        return await service.detail(db, actor, announcement)
    except service.AnnouncementError as exc:
        raise _refuse(exc) from exc


@router.get("/{announcement_id}")
async def get_announcement(
    announcement_id: int,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(db, current_user)
    try:
        announcement = await service.load(db, actor, announcement_id)
        return await service.detail(db, actor, announcement)
    except service.AnnouncementError as exc:
        raise _refuse(exc) from exc


@router.patch("/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    payload: AnnouncementPatch,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = await _actor(db, current_user)
    try:
        announcement = await service.load(db, actor, announcement_id, for_update=True)
        await service.update_draft(
            db, actor, announcement, payload.model_dump(exclude_unset=True)
        )
        return await service.detail(db, actor, announcement)
    except service.AnnouncementError as exc:
        raise _refuse(exc) from exc


async def _transition(
    db: AsyncSession, current_user: User, announcement_id: int, step, *args
) -> dict:
    actor = await _actor(db, current_user)
    try:
        announcement = await service.load(db, actor, announcement_id, for_update=True)
        await step(db, actor, announcement, *args)
        return await service.detail(db, actor, announcement)
    except service.AnnouncementError as exc:
        raise _refuse(exc) from exc


@router.post("/{announcement_id}/test-send")
async def test_send(
    announcement_id: int,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _transition(db, current_user, announcement_id, service.test_send)


@router.post("/{announcement_id}/submit")
async def submit(
    announcement_id: int,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _transition(db, current_user, announcement_id, service.submit)


@router.post("/{announcement_id}/approve")
async def approve(
    announcement_id: int,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _transition(db, current_user, announcement_id, service.approve)


@router.post("/{announcement_id}/return")
async def return_to_draft(
    announcement_id: int,
    payload: ReturnIn,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _transition(
        db, current_user, announcement_id, service.return_to_draft, payload.note
    )


@router.post("/{announcement_id}/cancel")
async def cancel(
    announcement_id: int,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _transition(db, current_user, announcement_id, service.cancel)


@router.post("/{announcement_id}/retry-failed")
async def retry_failed(
    announcement_id: int,
    current_user: AnnouncementsUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Wyślij ponownie do nieudanych” — autor, head back office, admin."""

    return await _transition(db, current_user, announcement_id, service.retry_failed)
