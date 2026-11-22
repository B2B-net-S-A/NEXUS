"""Kolejka back office'u: tablica, przejęcia, przydział, stan, kroki, zespół.

Prefiks ``/api/back-office`` (wpięty w ``app/main.py`` za ``_HR_PROGRAM``). Moduł
``back_office`` wyłączony = 404 dla każdego, także admina. Dostęp ma kierownik
(head back office, zastępca, admin) i członek zespołu; akcept na karcie front
woła istniejącą trasę (raporty, premie, zmiany w zamówieniach), a tu prosi tylko
o odświeżenie karty. Reguły: ``app/services/back_office/``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.back_office import BoCard
from app.models.user import User
from app.services.back_office import (
    access,
    board,
    people_view,
    service,
    steps,
    sync,
    team,
)
from app.services.back_office import settlement_extras as card_extras
from app.services.client_settlements import extras as settlement_extras
from app.services.client_settlements import settings as settlements_module
from app.services.back_office.sources import ADAPTERS
from app.services.back_office_schema import BACK_OFFICE_SETTING, NOTE_MAX
from app.services.back_office_team_schema import CLIENT_NOTE_MAX
from app.services.hr.modules import HrModule

router = APIRouter()

NO_ACCESS_DETAIL = "Kolejkę back office widzą zespoły back office i kierownik."
LEAD_ONLY_DETAIL = "To może zrobić kierownik back office."
CARD_NOT_FOUND_DETAIL = "Nie ma takiej karty."

Team = Literal["care", "finance", "contracts", "orders"]
OutsideTeam = Literal["recruitment", "sales", "it", "hr", "accounting", "legal"]
NoteBlock = Literal["settlement", "onboarding", "orders", "contacts"]


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
    state: Literal["new", "in_progress", "waiting"]
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
        viewer = await access.load_viewer(db, current_user)
        await service.add_note(
            db, card, actor=current_user, viewer=viewer, body=body.body
        )
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


@router.post("/sync/cases")
async def sync_cases(
    current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Karta nowej sprawy od razu; pełny przebieg z modelem i eskalacją ma kierownik."""

    return await sync.sync_kinds(db, ["case"], today=business_today())


@router.post("/sync")
async def run_sync(
    current_user: BackOfficeLead, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """„Odśwież teraz” kierownika: ten sam przebieg co pętla."""

    today = business_today()
    result = await sync.run_once(db, today=today)
    return result


class ReviewBody(BaseModel):
    decision: Literal["current", "close", "move"]
    team: Optional[Team] = None
    lane: Optional[str] = Field(default=None, max_length=12)
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


@router.post("/cards/{card_id}/review")
async def review_card(
    card_id: int,
    body: ReviewBody,
    current_user: BackOfficeLead,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Przegląd przed startem: każda stara sprawa dostaje jedną decyzję kierownika."""

    card = await _card(db, card_id)
    viewer = await access.load_viewer(db, current_user)
    try:
        await service.review(
            db,
            card,
            actor=current_user,
            viewer=viewer,
            decision=body.decision,
            team=body.team,
            lane=body.lane,
            note=body.note,
        )
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


@router.post("/review/finish")
async def finish_review(
    current_user: BackOfficeLead, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Koniec przeglądu: nowe sprawy nie trafiają już na listę do przejrzenia."""

    await _save_setting(
        db,
        {"review_done_at": business_today().isoformat()},
        actor=current_user,
    )
    await db.commit()
    return {"review_done_at": business_today().isoformat()}


async def _save_setting(
    db: AsyncSession, changes: dict[str, Any], *, actor: User
) -> None:
    value = {**(await access.load_settings(db)), **changes}
    statement = insert(AppSetting).values(
        key=BACK_OFFICE_SETTING, value=value, updated_by=actor.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.id},
        )
    )


# ── Dodatek do rozliczenia z karty sprawy (13.11.2026) ──────────────────────


class SettlementExtraBody(BaseModel):
    contract_id: int = Field(ge=1)
    month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    kind: str = Field(max_length=20)
    amount: Decimal = Field(gt=0, le=100000)
    description: Optional[str] = Field(default=None, max_length=300)


async def _settlements_open(db: AsyncSession, user: User) -> None:
    """Dodatki żyją w rozliczeniach klientów: wyłączony moduł = 404."""

    if not settlements_module.open_for(user, await settlements_module.is_enabled(db)):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, settlements_module.MODULE_DISABLED_DETAIL
        )


@router.get("/settlement-extras/people")
async def settlement_extra_people(
    current_user: BackOfficeMember,
    q: str = Query(..., min_length=2, max_length=80),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """„Kto” dla karty bez kontraktu: osoby z kontraktem po nazwisku."""

    await _settlements_open(db, current_user)
    return await card_extras.people(db, q)


@router.get("/cards/{card_id}/settlement-extras")
async def card_settlement_extras(
    card_id: int, current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _settlements_open(db, current_user)
    card = await db.get(BoCard, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARD_NOT_FOUND_DETAIL)
    viewer = await access.load_viewer(db, current_user)
    return await card_extras.card_view(db, card, viewer)


@router.post("/cards/{card_id}/settlement-extras", status_code=status.HTTP_201_CREATED)
async def add_card_settlement_extra(
    card_id: int,
    body: SettlementExtraBody,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zgłoszenie dodatku z karty: kto, okres, kwota. Czeka na Finanse."""

    await _settlements_open(db, current_user)
    card = await db.get(BoCard, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARD_NOT_FOUND_DETAIL)
    viewer = await access.load_viewer(db, current_user)
    if not (viewer.owns(card.team) or card.assignee_user_id == current_user.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Dodatek zgłasza zespół, do którego należy karta.",
        )
    try:
        await card_extras.add(
            db,
            card,
            contract_id=body.contract_id,
            month=body.month,
            kind=body.kind,
            amount=body.amount,
            description=body.description,
            actor_id=current_user.id,
            now=datetime.now(timezone.utc),
        )
        await db.commit()
    except settlement_extras.ExtraError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.message) from exc
    return await card_extras.card_view(db, card, viewer)


@router.get("/team")
async def get_team(
    current_user: BackOfficeLead, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Jeden zespół z rolami (decyzja 19.11.2026), działy na zewnątrz, osoby spoza."""

    return await team.team_view(db, today=business_today())


class MemberBody(BaseModel):
    role: Literal["deputy", "reception", "accountant", "member"] = "member"
    takes_calls: bool = True


@router.put("/team/members/{user_id}")
async def put_member(
    user_id: int,
    body: MemberBody,
    current_user: BackOfficeLead,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await team.set_member(
            db,
            actor=current_user,
            user_id=user_id,
            role=body.role,
            takes_calls=body.takes_calls,
        )
    except team.TeamError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    return await team.team_view(db, today=business_today())


@router.delete("/team/members/{user_id}")
async def delete_member(
    user_id: int, current_user: BackOfficeLead, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        await team.remove_member(db, user_id=user_id)
    except team.TeamError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return await team.team_view(db, today=business_today())


class OutsideContactsBody(BaseModel):
    contacts: dict[OutsideTeam, Optional[int]]


@router.put("/team/outside-contacts")
async def put_outside_contacts(
    body: OutsideContactsBody,
    current_user: BackOfficeLead,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        value = await team.outside_contacts_value(db, dict(body.contacts))
    except team.TeamError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await _save_setting(db, {"outside_contacts": value}, actor=current_user)
    await db.commit()
    return await team.team_view(db, today=business_today())


@router.post("/team/release-outsiders")
async def release_outsiders(
    current_user: BackOfficeLead, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Sprawy osób spoza zespołu wracają do kolejki (decyzja Artura 19.11.2026)."""

    try:
        released = await service.release_outsiders(
            db,
            actor=current_user,
            member_ids=await access.member_ids(db),
            keep=await access.keep_ids(db),
        )
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    await db.commit()
    return {"released": released}


class OutsideBody(BaseModel):
    team: OutsideTeam
    note: str = Field(min_length=1, max_length=200)
    expected_updated_at: Optional[datetime] = None


@router.post("/cards/{card_id}/outside")
async def send_outside(
    card_id: int,
    body: OutsideBody,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Na zewnątrz”: sprawa czeka na dział poza back office'em (decyzja 10.11)."""

    card = await _card(db, card_id)
    viewer = await access.load_viewer(db, current_user)
    try:
        await service.send_outside(
            db,
            card,
            actor=current_user,
            viewer=viewer,
            team=body.team,
            note=body.note,
            expected_updated_at=body.expected_updated_at,
        )
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    return await _detail(db, card, current_user)


@router.post("/next")
async def take_next(
    current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """„Weź następną”: kolejność liczy serwer — najstarszy termin, potem najdłużej bez osoby."""

    viewer = await access.load_viewer(db, current_user)
    try:
        card = await service.take_next(
            db, actor=current_user, viewer=viewer, today=business_today()
        )
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, service.NOTHING_TO_TAKE)
    return await _detail(db, card, current_user)


class BulkReviewBody(BaseModel):
    card_ids: list[int] = Field(min_length=1, max_length=500)
    decision: Literal["current", "close"]
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


@router.post("/review/bulk")
async def review_bulk(
    body: BulkReviewBody,
    current_user: BackOfficeLead,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Przegląd przed startem hurtem: ta sama decyzja, każda karta z wpisem w historii."""

    viewer = await access.load_viewer(db, current_user)
    try:
        result = await service.review_many(
            db,
            body.card_ids,
            actor=current_user,
            viewer=viewer,
            decision=body.decision,
            note=body.note,
        )
    except _CARD_ERRORS as exc:
        raise _translate(exc) from exc
    await db.commit()
    return result


@router.get("/consultants")
async def get_consultants(
    current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Wszyscy konsultanci z trwającym kontraktem — bez opiekuna i bez kwot."""

    return await people_view.consultants(db)


@router.get("/consultants/{contract_id}")
async def get_consultant(
    contract_id: int, current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    viewer = await access.load_viewer(db, current_user)
    out = await people_view.consultant_card(
        db, contract_id, viewer=viewer, user=current_user, today=business_today()
    )
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego kontraktu.")
    return out


@router.get("/clients")
async def get_clients(
    current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await people_view.clients(db, today=business_today())


@router.get("/clients/{client_id}")
async def get_client_sheet(
    client_id: int, current_user: BackOfficeMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    out = await people_view.client_sheet(db, client_id, today=business_today())
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego klienta.")
    return out


class ClientNoteBody(BaseModel):
    body: str = Field(default="", max_length=CLIENT_NOTE_MAX)


@router.put("/clients/{client_id}/notes/{block}")
async def put_client_note(
    client_id: int,
    block: NoteBlock,
    body: ClientNoteBody,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ściąga klienta: każdy z zespołu poprawia to, co wie (19.11.2026)."""

    try:
        await people_view.save_note(
            db, client_id=client_id, block=block, body=body.body, actor=current_user
        )
    except people_view.SheetError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    out = await people_view.client_sheet(db, client_id, today=business_today())
    assert out is not None
    return out
