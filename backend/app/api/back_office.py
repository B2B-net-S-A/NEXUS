"""Kolejka back office'u: tablica, przejęcia, przydział, stan, kroki, zespoły.

Prefiks ``/api/back-office`` (wpięty w ``app/main.py`` za ``_HR_PROGRAM``). Moduł
``back_office`` wyłączony = 404 dla każdego, także admina. Dostęp ma kierownik
(head back office, zastępca, admin) i członek zespołu; akcept na karcie front
woła istniejącą trasę (raporty, premie, zmiany w zamówieniach), a tu prosi tylko
o odświeżenie karty. Reguły: ``app/services/back_office/``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.back_office import BoCard, BoTeamMember
from app.models.user import User
from app.services.back_office import access, board, service, steps, sync
from app.services.back_office.sources import ADAPTERS
from app.services.back_office_schema import BACK_OFFICE_SETTING, NOTE_MAX
from app.services.hr.modules import HrModule

router = APIRouter()

NO_ACCESS_DETAIL = "Kolejkę back office widzą zespoły back office i kierownik."
LEAD_ONLY_DETAIL = "To może zrobić kierownik back office."
CARD_NOT_FOUND_DETAIL = "Nie ma takiej karty."

Team = Literal["care", "finance", "contracts", "orders"]


def require_hr_back_office_member():
    """Członek zespołu albo kierownik, przy włączonym module."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.back_office)
        if not (await access.load_viewer(db, current_user)).has_access:
            raise HTTPException(status.HTTP_403_FORBIDDEN, NO_ACCESS_DETAIL)
        return current_user

    return _check


def require_hr_back_office_lead():
    """Kierownik: head back office, zastępca, admin."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.back_office)
        if not (await access.load_viewer(db, current_user)).is_lead:
            raise HTTPException(status.HTTP_403_FORBIDDEN, LEAD_ONLY_DETAIL)
        return current_user

    return _check


BackOfficeMember = Annotated[User, Depends(require_hr_back_office_member())]
BackOfficeLead = Annotated[User, Depends(require_hr_back_office_lead())]


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, service.CardConflict):
        return HTTPException(
            status.HTTP_409_CONFLICT, {"message": str(exc), "code": exc.code}
        )
    if isinstance(exc, service.CardForbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


_CARD_ERRORS = (service.CardConflict, service.CardForbidden, service.CardError)


async def _card(db: AsyncSession, card_id: int) -> BoCard:
    card = await service.locked_card(db, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARD_NOT_FOUND_DETAIL)
    return card


async def _detail(db: AsyncSession, card: BoCard, user: User) -> dict[str, Any]:
    await db.commit()
    await db.refresh(card)
    viewer = await access.load_viewer(db, user)
    return await board.card_detail(db, card, user=user, viewer=viewer)


@router.get("/board")
async def get_board(
    current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    viewer = await access.load_viewer(db, current_user)
    return await board.board(
        db, user=current_user, viewer=viewer, today=business_today()
    )


@router.get("/cards/{card_id}")
async def get_card(
    card_id: int, current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    card = await db.get(BoCard, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARD_NOT_FOUND_DETAIL)
    viewer = await access.load_viewer(db, current_user)
    return await board.card_detail(db, card, user=current_user, viewer=viewer)


class TakeBody(BaseModel):
    substitute: bool = False
    override_priority: bool = False
    expected_updated_at: Optional[datetime] = None


@router.post("/cards/{card_id}/take")
async def take_card(
    card_id: int,
    body: TakeBody,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    card = await _card(db, card_id)
    viewer = await access.load_viewer(db, current_user)
    try:
        await service.take(
            db,
            card,
            actor=current_user,
            viewer=viewer,
            substitute=body.substitute,
            override_priority=body.override_priority,
            expected_updated_at=body.expected_updated_at,
            today=business_today(),
        )
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


@router.post("/cards/{card_id}/release")
async def release_card(
    card_id: int, current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    card = await _card(db, card_id)
    viewer = await access.load_viewer(db, current_user)
    try:
        await service.release(db, card, actor=current_user, viewer=viewer)
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


class AssignBody(BaseModel):
    user_id: int


@router.post("/cards/{card_id}/assign")
async def assign_card(
    card_id: int,
    body: AssignBody,
    current_user: BackOfficeLead,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    card = await _card(db, card_id)
    try:
        await service.assign(db, card, actor=current_user, user_id=body.user_id)
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


class StateBody(BaseModel):
    state: Literal["new", "in_progress", "waiting", "done"]
    waiting_on: Optional[str] = Field(default=None, max_length=200)
    expected_updated_at: Optional[datetime] = None


@router.post("/cards/{card_id}/state")
async def set_card_state(
    card_id: int,
    body: StateBody,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    card = await _card(db, card_id)
    viewer = await access.load_viewer(db, current_user)
    try:
        await service.set_state(
            db,
            card,
            actor=current_user,
            viewer=viewer,
            state=body.state,
            waiting_on=body.waiting_on,
            expected_updated_at=body.expected_updated_at,
        )
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


class NoteBody(BaseModel):
    body: str = Field(min_length=1, max_length=NOTE_MAX)


@router.post("/cards/{card_id}/note")
async def note_card(
    card_id: int,
    body: NoteBody,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    card = await _card(db, card_id)
    try:
        await service.add_note(db, card, actor=current_user, body=body.body)
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


@router.post("/cards/{card_id}/dismiss")
async def dismiss_card(
    card_id: int,
    body: NoteBody,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    card = await _card(db, card_id)
    viewer = await access.load_viewer(db, current_user)
    try:
        await service.dismiss(
            db, card, actor=current_user, viewer=viewer, note=body.body
        )
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


@router.post("/cards/{card_id}/step-done")
async def step_done(
    card_id: int, current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    card = await _card(db, card_id)
    viewer = await access.load_viewer(db, current_user)
    try:
        await service.complete_step(db, card, actor=current_user, viewer=viewer)
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


class MoveBody(BaseModel):
    team: Team
    lane: str = Field(max_length=12)


@router.post("/cards/{card_id}/move")
async def move_card(
    card_id: int,
    body: MoveBody,
    current_user: BackOfficeLead,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    card = await _card(db, card_id)
    try:
        await service.move(db, card, actor=current_user, team=body.team, lane=body.lane)
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


@router.post("/cards/{card_id}/refresh")
async def refresh_card(
    card_id: int, current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Po akcepcie w istniejącej trasie: przelicza karty tego rodzaju od razu."""

    card = await db.get(BoCard, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARD_NOT_FOUND_DETAIL)
    today = business_today()
    if card.source_kind in ADAPTERS:
        await sync.sync_kinds(db, [card.source_kind], today=today)
    if card.source_kind == "case":
        await steps.sync_steps(db, today=today)
    return await _detail(db, card, current_user)


@router.post("/sync")
async def run_sync(
    current_user: BackOfficeLead, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """„Odśwież teraz” kierownika: ten sam przebieg co pętla."""

    today = business_today()
    result = await sync.run_once(db, today=today)
    return result


@router.get("/team")
async def get_team(
    current_user: BackOfficeLead, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    members = await access.team_members(db)
    names = await board.user_names(db, [uid for ids in members.values() for uid in ids])
    settings_value = await access.load_settings(db)
    return {
        "teams": [
            {
                "id": team,
                "label": board.TEAM_LABELS[team],
                "members": [{"id": uid, "name": names.get(uid)} for uid in ids],
            }
            for team, ids in members.items()
        ],
        "deputy_user_id": settings_value.get("deputy_user_id"),
    }


class TeamBody(BaseModel):
    user_ids: list[int] = Field(max_length=100)


@router.put("/team/{team}")
async def put_team(
    team: Team,
    body: TeamBody,
    current_user: BackOfficeLead,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    wanted = set(body.user_ids)
    found = set(
        (
            await db.scalars(
                select(User.id).where(User.id.in_(wanted), User.is_active.is_(True))
            )
        ).all()
    )
    if wanted - found:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Nie ma takiego aktywnego konta."
        )
    current = set(
        (
            await db.scalars(
                select(BoTeamMember.user_id).where(BoTeamMember.team == team)
            )
        ).all()
    )
    for user_id in current - wanted:
        member = await db.get(BoTeamMember, (team, user_id))
        if member is not None:
            await db.delete(member)
    for user_id in wanted - current:
        db.add(BoTeamMember(team=team, user_id=user_id, added_by=current_user.id))
    await db.commit()
    return await get_team(current_user, db)


class DeputyBody(BaseModel):
    user_id: Optional[int] = None


@router.put("/deputy")
async def put_deputy(
    body: DeputyBody,
    current_user: BackOfficeLead,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if body.user_id is not None:
        person = await db.get(User, body.user_id)
        if person is None or not person.is_active:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Nie ma takiego aktywnego konta.",
            )
    value = {**(await access.load_settings(db)), "deputy_user_id": body.user_id}
    statement = insert(AppSetting).values(
        key=BACK_OFFICE_SETTING, value=value, updated_by=current_user.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": current_user.id},
        )
    )
    await db.commit()
    return {"deputy_user_id": body.user_id}
