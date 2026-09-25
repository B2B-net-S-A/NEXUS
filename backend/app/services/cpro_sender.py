"""Osoba, która wysyła kandydatów do Cpro Nordei — JEDNA na firmę (24.09.2026).

Decyzja Artura 23.09.2026: nie osoba per rekrutacja (0353,
``jobs.cpro_sender_id``) ani per kandydat (0348,
``candidate_stages.task_assignee_id``), tylko jedna osoba na całą firmę,
którą zmienia KAŻDY z zespołu. Powód: u Nordei wrzucanie do Cpro robi w
praktyce jedna osoba, a typowanie per rekrutacja zostawiało rekrutacje bez
nikogo — kolejka rosła, a dzwonek nie miał do kogo pójść.

Zastępstwo: ``until`` to ostatni dzień zastępstwa (włącznie). Od dnia po nim
wraca ``fallback_user_id`` — osoba, która wysyłała, zanim ustawiono
zastępstwo. Wygaśnięcie liczy się przy ODCZYCIE (``effective``), bez pętli:
nikt nie musi pamiętać, żeby „oddać" kolejkę po urlopie.

Stan żyje w ``app_settings['cpro_sender']``:
``{user_id, until, fallback_user_id, set_by_user_id, set_at}``. Stare kolumny
(``jobs.cpro_sender_id``, ``task_assignee_id``) zostają w bazie i są zapasem
kolejki wyłącznie wtedy, gdy nikt nie jest ustawiony na firmę.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.user import User, UserRole

SETTING_KEY = "cpro_sender"

# Kto — obok osoby od Cpro — przesuwa kartę na „Wysłane do Cpro" i zwraca ją
# do rekrutera (kontrakt Rekrutacji v5).
CPRO_MOVE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)


@dataclass(frozen=True)
class CproSenderState:
    user_id: Optional[int] = None
    until: Optional[date] = None
    fallback_user_id: Optional[int] = None
    set_by_user_id: Optional[int] = None
    set_at: Optional[datetime] = None

    def as_json(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "until": self.until.isoformat() if self.until else None,
            "fallback_user_id": self.fallback_user_id,
            "set_by_user_id": self.set_by_user_id,
            "set_at": self.set_at.isoformat() if self.set_at else None,
        }


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _date_or_none(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _datetime_or_none(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def parse_state(value: Optional[dict]) -> CproSenderState:
    """JSON z ``app_settings`` → stan. Uszkodzony wpis = „nikt", nie 500."""

    if not isinstance(value, dict):
        return CproSenderState()
    return CproSenderState(
        user_id=_int_or_none(value.get("user_id")),
        until=_date_or_none(value.get("until")),
        fallback_user_id=_int_or_none(value.get("fallback_user_id")),
        set_by_user_id=_int_or_none(value.get("set_by_user_id")),
        set_at=_datetime_or_none(value.get("set_at")),
    )


def effective(state: CproSenderState, today: date) -> CproSenderState:
    """Stan obowiązujący dziś: po ``until`` wraca osoba sprzed zastępstwa.

    ``until`` jest włącznie — zastępstwo „do 3.10" obejmuje 3.10.
    """

    if state.until is None or today <= state.until:
        return state
    return replace(
        state, user_id=state.fallback_user_id, until=None, fallback_user_id=None
    )


def next_state(
    current: CproSenderState,
    *,
    user_id: Optional[int],
    until: Optional[date],
    actor_id: int,
    today: date,
    now: datetime,
) -> CproSenderState:
    """Nowy stan po zmianie osoby — czysta reguła (bez bazy).

    Zastępstwo (``until``) pamięta, kto wysyłał dotąd, żeby po nim wrócić.
    Zmiana zastępcy w trakcie zastępstwa zachowuje TĘ SAMĄ osobę powrotu —
    inaczej druga zmiana ustawiłaby jako „powrót" zastępcę. Zmiana bez
    ``until`` jest stała i kasuje powrót.
    """

    if until is not None and user_id is None:
        raise HTTPException(
            status_code=422,
            detail="Zastępstwo wymaga wskazania osoby, która wysyła do Cpro.",
        )
    if until is not None and until < today:
        raise HTTPException(
            status_code=422,
            detail="Data końca zastępstwa nie może być w przeszłości.",
        )
    now_state = effective(current, today)
    fallback: Optional[int] = None
    if until is not None:
        if now_state.until is not None:
            fallback = now_state.fallback_user_id
        else:
            fallback = now_state.user_id
        if fallback == user_id:
            fallback = None
    return CproSenderState(
        user_id=user_id,
        until=until,
        fallback_user_id=fallback,
        set_by_user_id=actor_id,
        set_at=now,
    )


async def load_state(db: AsyncSession, *, for_update: bool = False) -> CproSenderState:
    query = select(AppSetting.value).where(AppSetting.key == SETTING_KEY)
    if for_update:
        query = query.with_for_update()
    return parse_state(await db.scalar(query))


async def effective_sender(
    db: AsyncSession, now: Optional[datetime] = None
) -> CproSenderState:
    """Kto dziś wysyła do Cpro (stan po wygaśnięciu zastępstwa)."""

    today = (
        now.astimezone(_business_tz()).date() if now is not None else business_today()
    )
    return effective(await load_state(db), today)


def _business_tz():
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    from app.core.config import settings  # noqa: PLC0415

    return ZoneInfo(settings.BUSINESS_TZ)


async def set_sender(
    db: AsyncSession,
    *,
    user_id: Optional[int],
    until: Optional[date],
    actor: User,
    now: Optional[datetime] = None,
) -> tuple[CproSenderState, CproSenderState]:
    """Zapisuje nową osobę; zwraca (stan obowiązujący przed, stan po).

    Blokada wiersza ustawienia: dwie równoczesne zmiany nie mogą obie policzyć
    „powrotu" z tego samego stanu. Nie commituje.
    """

    moment = now or datetime.now(timezone.utc)
    today = moment.astimezone(_business_tz()).date()
    current = await load_state(db, for_update=True)
    before = effective(current, today)
    new = next_state(
        current,
        user_id=user_id,
        until=until,
        actor_id=actor.id,
        today=today,
        now=moment,
    )
    stmt = pg_insert(AppSetting).values(
        key=SETTING_KEY, value=new.as_json(), updated_by=actor.id
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": stmt.excluded.value, "updated_by": actor.id},
        )
    )
    return before, new


async def user_names(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(
        select(User.id, User.name, User.email).where(User.id.in_(wanted))
    )
    return {uid: (name or email) for uid, name, email in rows.all()}


async def describe(db: AsyncSession, state: CproSenderState) -> dict[str, Any]:
    """Kształt odpowiedzi `GET /api/board-tasks/cpro/sender`."""

    names = await user_names(
        db, {state.user_id, state.fallback_user_id, state.set_by_user_id}
    )
    return {
        "user_id": state.user_id,
        "user_name": names.get(state.user_id) if state.user_id else None,
        "until": state.until,
        "fallback_user_id": state.fallback_user_id,
        "fallback_user_name": (
            names.get(state.fallback_user_id) if state.fallback_user_id else None
        ),
        "set_by_name": (
            names.get(state.set_by_user_id) if state.set_by_user_id else None
        ),
        "set_at": state.set_at,
    }


async def can_send_to_cpro(
    db: AsyncSession,
    user: User,
    now: Optional[datetime] = None,
    *,
    fallback_sender_ids: Iterable[Optional[int]] = (),
) -> bool:
    """Czy ``user`` może przesunąć kartę z kolejki Cpro („✓ Wrzucone",
    „Zwróć do rekrutera"): osoba od Cpro albo admin / DL / HoR.

    Gdy nikt nie jest ustawiony na firmę, kolejka pokazuje zadanie osobie
    zapasowej tej rekrutacji (``jobs.cpro_sender_id`` albo
    ``task_assignee_id`` wiersza — ``fallback_sender_ids``), więc ta osoba
    musi też móc je wrzucić. Bez tego rekruter widział zadanie „do wrzucenia"
    i dostawał 403 na „✓ Wrzucone" (audyt 25.09.2026). Osoba ustawiona na
    firmę wygrywa — zapas wtedy nie daje prawa.
    """

    if user.has_any_role(*CPRO_MOVE_ROLES):
        return True
    firm = (await effective_sender(db, now)).user_id
    if firm is not None:
        return firm == user.id
    return user.id in {uid for uid in fallback_sender_ids if uid is not None}


async def notify_new_sender(
    db: AsyncSession,
    *,
    sender_id: int,
    until: Optional[date],
    waiting: int,
    actor: User,
) -> None:
    """Dzwonek dla osoby, która od teraz wysyła do Cpro. Nie dla siebie.

    Encją jest sam odbiorca (jak poranny skrót) — to przypisanie do firmowej
    kolejki, nie do rekrutacji. Dedup dobowy `ix_notif_dedup_daily` (osoba,
    typ, encja): drugie ustawienie tego samego dnia nie daje drugiego dzwonka,
    zmianę widać w historii (`Activity`).
    """

    if sender_id == actor.id:
        return
    from app.models.notification import NotificationType  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    period = f" do {until.strftime('%d.%m.%Y')} (zastępstwo)" if until else ""
    waits = f" W kolejce czeka: {waiting}." if waiting else ""
    await emit(
        db,
        user_id=sender_id,
        title="Wysyłasz kandydatów do Cpro",
        message=(
            f"{actor.name or 'Ktoś z zespołu'} ustawił(a) Cię jako osobę, która "
            f"wrzuca kandydatów Nordei do Cpro{period}.{waits}"
        ),
        ntype=NotificationType.cpro_send_assigned,
        related_entity_type="user",
        related_entity_id=sender_id,
        link="/dashboard#czeka-na-ciebie",
    )


__all__ = [
    "CPRO_MOVE_ROLES",
    "SETTING_KEY",
    "CproSenderState",
    "can_send_to_cpro",
    "describe",
    "effective",
    "effective_sender",
    "load_state",
    "next_state",
    "notify_new_sender",
    "parse_state",
    "set_sender",
    "user_names",
]
