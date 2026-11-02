"""Zapis na karcie: „Biorę”, „Zastępuję”, przydział, stan, notatka, krok.

Przy sprawie osoba i stan zostają w ``admin_cases``: karta je lustruje w tej
samej transakcji, a przejęcie idzie przez ``update_case``, które pilnuje śladu
i dzwonka. Dwie osoby naraz: blokada wiersza i ``expected_updated_at`` dają 409.
Limit 5 w toku blokuje tylko nowe „Biorę”; karta już wzięta zostaje.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_case import AdminCase
from app.models.back_office import BoCard, BoCardEvent
from app.models.notification import NotificationType
from app.models.user import User
from app.services.admin_cases import service as cases
from app.services.back_office import steps
from app.services.back_office.access import Viewer
from app.services.back_office_schema import LANES, NOTE_MAX, TEAM_LANES, TEAMS
from app.services.hr.notify import notify_each

#: Limit kart „W toku” na osobę (decyzja 02.11).
IN_PROGRESS_LIMIT = 5
#: Pierwszeństwo osoby, która ostatnio rozmawiała z konsultantem.
PRIORITY_DAYS = 3
STALE_DETAIL = "Karta zmieniła się w międzyczasie. Odśwież tablicę."


class CardError(ValueError):
    """Odmowa z komunikatem dla użytkownika (422)."""


class CardConflict(Exception):
    """Ktoś był szybszy albo limit (409); ``code`` rozróżnia powód na froncie."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class CardForbidden(Exception):
    """Karta innego zespołu bez „Zastępuję” albo akcja dla kierownika (403)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def locked_card(db: AsyncSession, card_id: int) -> Optional[BoCard]:
    return await db.scalar(
        select(BoCard)
        .where(BoCard.id == card_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _event(
    db: AsyncSession,
    card: BoCard,
    *,
    actor_id: Optional[int],
    action: str,
    details: Optional[dict[str, Any]] = None,
    now: datetime,
) -> None:
    db.add(
        BoCardEvent(
            card_id=card.id,
            actor_user_id=actor_id,
            action=action,
            details=details or {},
            created_at=now,
        )
    )


def _check_version(card: BoCard, expected: Optional[datetime]) -> None:
    if expected is None:
        return
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    if abs((card.updated_at - expected).total_seconds()) >= 0.001:
        raise CardConflict(STALE_DETAIL, code="stale")


async def in_progress_count(db: AsyncSession, user_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(BoCard)
            .where(BoCard.assignee_user_id == user_id, BoCard.state == "in_progress")
        )
        or 0
    )


async def _case_of(db: AsyncSession, card: BoCard) -> Optional[AdminCase]:
    if card.source_kind != "case" or card.case_id is None:
        return None
    return await cases.get_case(db, card.case_id, lock=True)


async def _mirror_case(
    db: AsyncSession, card: BoCard, *, actor: User, changes: dict[str, Any]
) -> None:
    case = await _case_of(db, card)
    if case is None:
        return
    try:
        await cases.update_case(db, case, actor=actor, changes=changes)
    except cases.CaseError as exc:
        raise CardError(str(exc)) from exc


async def take(
    db: AsyncSession,
    card: BoCard,
    *,
    actor: User,
    viewer: Viewer,
    substitute: bool,
    override_priority: bool,
    expected_updated_at: Optional[datetime],
    today: date,
) -> None:
    now = _now()
    _check_version(card, expected_updated_at)
    if card.state == "done":
        raise CardConflict("Ta karta jest już zamknięta.", code="closed")
    if card.assignee_user_id is not None:
        raise CardConflict("Tę kartę ktoś już wziął.", code="taken")
    own_team = viewer.owns(card.team)
    if not own_team and not substitute:
        raise CardForbidden("To karta innego zespołu. Użyj „Zastępuję”.")
    if (
        card.priority_user_id not in (None, actor.id)
        and card.priority_until is not None
        and card.priority_until >= today
        and not override_priority
        and not viewer.is_lead
    ):
        raise CardConflict(
            f"Pierwszeństwo do {card.priority_until:%d.%m} ma osoba, która ostatnio "
            "rozmawiała z konsultantem.",
            code="priority",
        )
    if await in_progress_count(db, actor.id) >= IN_PROGRESS_LIMIT:
        raise CardConflict(
            f"Masz już {IN_PROGRESS_LIMIT} spraw w toku. Zamknij albo oddaj jedną, "
            "zanim weźmiesz kolejną.",
            code="limit",
        )
    await _mirror_case(
        db,
        card,
        actor=actor,
        changes={"assignee_user_id": actor.id, "status": "in_progress"},
    )
    card.assignee_user_id = actor.id
    card.substituting = not own_team
    card.state = "in_progress"
    card.taken_at = now
    card.escalated_at = None
    card.updated_at = now
    _event(
        db,
        card,
        actor_id=actor.id,
        action="substituted" if not own_team else "taken",
        now=now,
    )
    await db.flush()


async def release(
    db: AsyncSession, card: BoCard, *, actor: User, viewer: Viewer
) -> None:
    if card.assignee_user_id != actor.id and not viewer.is_lead:
        raise CardForbidden(
            "Oddać kartę może osoba, która ją prowadzi, albo kierownik."
        )
    now = _now()
    await _mirror_case(
        db, card, actor=actor, changes={"assignee_user_id": None, "status": "new"}
    )
    card.assignee_user_id = None
    card.substituting = False
    card.state = "new"
    card.taken_at = None
    card.updated_at = now
    _event(db, card, actor_id=actor.id, action="released", now=now)
    await db.flush()


async def assign(db: AsyncSession, card: BoCard, *, actor: User, user_id: int) -> None:
    """Przydział kierownika. Limit go nie blokuje: decyzja należy do kierownika."""

    person = await db.get(User, user_id)
    if person is None or not person.is_active:
        raise CardError("Nie ma takiego aktywnego konta.")
    now = _now()
    await _mirror_case(
        db,
        card,
        actor=actor,
        changes={"assignee_user_id": user_id, "status": "in_progress"},
    )
    card.assignee_user_id = user_id
    card.substituting = False
    card.state = "in_progress"
    card.taken_at = now
    card.escalated_at = None
    card.updated_at = now
    _event(
        db,
        card,
        actor_id=actor.id,
        action="assigned",
        details={"user_id": user_id},
        now=now,
    )
    await db.flush()
    if card.source_kind != "case":
        # Sprawa ma własny dzwonek w ``update_case``.
        await notify_each(
            db,
            [user_id],
            exclude=[actor.id],
            title="Przydzielono Ci kartę back office",
            message=card.title,
            ntype=NotificationType.back_office_assigned,
            related_entity_type="bo_card",
            related_entity_id=card.id,
            link=f"/back-office?karta={card.id}",
            log_tag="back_office",
        )


async def set_state(
    db: AsyncSession,
    card: BoCard,
    *,
    actor: User,
    viewer: Viewer,
    state: str,
    waiting_on: Optional[str],
    expected_updated_at: Optional[datetime],
) -> None:
    if card.assignee_user_id != actor.id and not viewer.owns(card.team):
        raise CardForbidden("Stan zmienia osoba prowadząca albo jej zespół.")
    _check_version(card, expected_updated_at)
    if state == "waiting" and not (waiting_on or "").strip():
        raise CardError("Napisz, na kogo czeka ta sprawa.")
    now = _now()
    await _mirror_case(db, card, actor=actor, changes={"status": state})
    card.state = state
    card.waiting_on = (
        (waiting_on or "").strip()[:200] or None if state == "waiting" else None
    )
    card.updated_at = now
    _event(db, card, actor_id=actor.id, action=f"state_{state}", now=now)
    await db.flush()


async def dismiss(
    db: AsyncSession, card: BoCard, *, actor: User, viewer: Viewer, note: str
) -> None:
    """„Nie dotyczy”: karta znika i nie wraca, choć źródło dalej ją liczy."""

    if not viewer.owns(card.team):
        raise CardForbidden("„Nie dotyczy” ustawia zespół karty albo kierownik.")
    reason = (note or "").strip()
    if not reason:
        raise CardError("Napisz krótko, dlaczego ta karta nie dotyczy.")
    now = _now()
    await _mirror_case(db, card, actor=actor, changes={"status": "closed"})
    card.state = "done"
    card.closed_at = now
    card.updated_at = now
    card.meta = {**(card.meta or {}), "dismissed": True}
    _event(
        db,
        card,
        actor_id=actor.id,
        action="dismissed",
        details={"note": reason[:NOTE_MAX]},
        now=now,
    )
    await db.flush()


async def add_note(db: AsyncSession, card: BoCard, *, actor: User, body: str) -> None:
    text_value = (body or "").replace("\x00", "").strip()
    if not text_value:
        raise CardError("Notatka nie może być pusta.")
    if len(text_value) > NOTE_MAX:
        raise CardError(f"Notatka może mieć najwyżej {NOTE_MAX} znaków.")
    now = _now()
    case = await _case_of(db, card)
    if case is not None:
        await cases.add_comment(db, case, actor=actor, body=text_value)
    _event(
        db,
        card,
        actor_id=actor.id,
        action="note",
        details={"body": text_value},
        now=now,
    )
    card.updated_at = now
    await db.flush()


async def complete_step(
    db: AsyncSession, card: BoCard, *, actor: User, viewer: Viewer
) -> None:
    """Krok zrobiony: odhacza pozycje checklisty sprawy i sprawdza całość."""

    if card.source_kind != "step":
        raise CardError("To nie jest krok sprawy.")
    if card.assignee_user_id != actor.id and not viewer.owns(card.team):
        raise CardForbidden("Krok zalicza jego zespół albo kierownik.")
    now = _now()
    slug = (card.meta or {}).get("step")
    case = await cases.get_case(db, card.case_id, lock=True) if card.case_id else None
    if case is not None:
        definition = next(
            (s for s in steps.steps_for_case(case.source_key) if s.slug == slug), None
        )
        if definition is not None and definition.checklist:
            ticked = [
                {**item, "done": True}
                if any(
                    str(item.get("text", "")).startswith(p)
                    for p in definition.checklist
                )
                else item
                for item in case.checklist or []
            ]
            if ticked != case.checklist:
                await cases.update_case(
                    db, case, actor=actor, changes={"checklist": ticked}
                )
    card.state = "done"
    card.closed_at = now
    card.updated_at = now
    _event(db, card, actor_id=actor.id, action="step_done", now=now)
    await db.flush()
    if case is not None:
        open_left = await db.scalar(
            select(func.count())
            .select_from(BoCard)
            .where(BoCard.parent_card_id == card.parent_card_id, BoCard.state != "done")
        )
        if not open_left:
            await steps.close_case_when_all_done(db, case, now=now)


async def move(
    db: AsyncSession, card: BoCard, *, actor: User, team: str, lane: str
) -> None:
    """Przeniesienie do innej kolumny (kierownik, przegląd, „Do rozdzielenia”)."""

    if team not in TEAMS or lane not in LANES or lane not in TEAM_LANES[team]:
        raise CardError("Nie ma takiej kolumny.")
    now = _now()
    card.team = team
    card.lane = lane
    card.lane_locked = True
    card.updated_at = now
    _event(
        db,
        card,
        actor_id=actor.id,
        action="moved",
        details={"team": team, "lane": lane},
        now=now,
    )
    await db.flush()


async def apply_priorities(db: AsyncSession, *, today: date) -> int:
    """Pierwszeństwo dla ostatniego rozmówcy: 3 dni od założenia karty.

    Tylko karty bez osoby, z kontraktem, bez ustawionego pierwszeństwa.
    Rozmowa nie starsza niż 90 dni, bo dawny opiekun nic już nie wie.
    """

    from app.models.contract_care import CareConversation  # noqa: PLC0415

    cards = (
        await db.scalars(
            select(BoCard).where(
                BoCard.state == "new",
                BoCard.assignee_user_id.is_(None),
                BoCard.priority_user_id.is_(None),
                BoCard.contract_id.is_not(None),
                BoCard.team == "care",
            )
        )
    ).all()
    if not cards:
        return 0
    latest: dict[int, int] = {}
    rows = (
        await db.execute(
            select(CareConversation.contract_id, CareConversation.author_user_id)
            .where(
                CareConversation.contract_id.in_({c.contract_id for c in cards}),
                CareConversation.occurred_on >= today - timedelta(days=90),
                CareConversation.author_user_id.is_not(None),
            )
            .order_by(CareConversation.occurred_on, CareConversation.id)
        )
    ).all()
    for contract_id, user_id in rows:
        latest[contract_id] = user_id
    applied = 0
    for card in cards:
        user_id = latest.get(card.contract_id)
        if user_id is None:
            continue
        card.priority_user_id = user_id
        card.priority_until = today + timedelta(days=PRIORITY_DAYS)
        applied += 1
    await db.flush()
    return applied
