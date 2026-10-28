"""„Ogłoszenia” na pulpicie każdej osoby (decyzja Artura 28.10.2026, 0613).

* ``GET /api/announcements`` — aktywne ogłoszenia patrzącego (pulpit);
* ``POST /api/announcements/{id}/read`` — „Przeczytane”;
* ``POST /api/announcements`` — publikuje Head of Recruitment albo admin;
* ``PATCH /api/announcements/{id}`` — poprawka przed terminem;
* ``DELETE /api/announcements/{id}`` — „Zdejmij” przed terminem.

Odczyt i „Przeczytane” są bez bramki sekcji (opisany wyjątek
w ``tests/test_route_authz_contract.py``): pulpit ma każde konto, także
„Pracownik” i Rada, a odbiorców filtruje serwer (``announcements.list_for``).
Zapisy stoją za sekcją Rekrutacje i rolą Head of Recruitment albo admin.
Skutki liczy ``services/announcements``.

Uwaga: moduł bez ``from __future__ import annotations`` — FastAPI czyta
adnotacje ciała w czasie rejestracji trasy.
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, HeadOfRecruitmentPlus, get_db
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.announcement import Announcement
from app.services import announcements
from app.services.announcements_schema import BODY_MAX, TITLE_MAX

router = APIRouter()


class AnnouncementOut(BaseModel):
    id: int
    title: str
    body: str
    visible_until: date
    audience_roles: list[str]
    pinned: bool
    important: bool
    author_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Czy ogłoszenie jest skierowane do patrzącego (publikujący widzą wszystkie).
    for_me: bool
    read: bool
    # Tylko dla publikujących: „przeczytało N z M”.
    read_count: Optional[int] = None
    recipient_count: Optional[int] = None


class AnnouncementListOut(BaseModel):
    items: list[AnnouncementOut]
    can_publish: bool
    audience_roles: list[str]


class AnnouncementBody(BaseModel):
    title: str = Field(max_length=TITLE_MAX * 2)
    body: str = Field(max_length=BODY_MAX * 2)
    visible_until: date
    # Pusta lista = wszyscy.
    audience_roles: list[str] = Field(default_factory=list, max_length=20)
    pinned: bool = False
    important: bool = False

    def to_input(self) -> announcements.AnnouncementInput:
        return announcements.AnnouncementInput(
            title=self.title,
            body=self.body,
            visible_until=self.visible_until,
            audience_roles=tuple(self.audience_roles),
            pinned=self.pinned,
            important=self.important,
        )


class AnnouncementSavedOut(BaseModel):
    id: int
    notified: int = 0


@router.get("", response_model=AnnouncementListOut)
async def list_announcements(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return {
        "items": await announcements.list_for(db, user),
        "can_publish": announcements.can_publish(user),
        "audience_roles": list(announcements.AUDIENCE_ROLES),
    }


async def _get(db: AsyncSession, announcement_id: int, *, lock: bool = False):
    row = await db.get(
        Announcement, announcement_id, with_for_update=lock, populate_existing=lock
    )
    if row is None:
        raise HTTPException(404, "Nie ma takiego ogłoszenia.")
    return row


@router.post("/{announcement_id}/read", status_code=204)
async def read_announcement(
    announcement_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    row = await _get(db, announcement_id)
    try:
        await announcements.mark_read(db, row, user)
    except announcements.AnnouncementError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    await db.commit()


@router.post(
    "",
    response_model=AnnouncementSavedOut,
    status_code=201,
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)
async def publish_announcement(
    body: AnnouncementBody,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    try:
        row = await announcements.create(db, body.to_input(), actor_id=user.id)
    except announcements.AnnouncementError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    sent = await announcements.notify_important(db, row, actor_id=user.id)
    await db.commit()
    return {"id": row.id, "notified": len(sent)}


@router.patch(
    "/{announcement_id}",
    response_model=AnnouncementSavedOut,
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)
async def edit_announcement(
    announcement_id: int,
    body: AnnouncementBody,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    row = await _get(db, announcement_id, lock=True)
    try:
        await announcements.update(db, row, body.to_input(), actor_id=user.id)
    except announcements.AnnouncementError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    # „Ważne” dodane w poprawce dzwoni raz; drugi raz poprawka nie dzwoni.
    sent = await announcements.notify_important(db, row, actor_id=user.id)
    await db.commit()
    return {"id": row.id, "notified": len(sent)}


@router.delete(
    "/{announcement_id}",
    response_model=AnnouncementSavedOut,
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)
async def withdraw_announcement(
    announcement_id: int,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    row = await _get(db, announcement_id, lock=True)
    try:
        await announcements.withdraw(db, row, actor_id=user.id)
    except announcements.AnnouncementError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    await db.commit()
    return {"id": row.id}
