"""
Notifications API
User notification system with unread badge support.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.api.deps import CurrentUser
from app.services.notification_access import (
    notification_types_for_sections,
    notification_visibility_predicate,
    user_may_receive_type,
)
from app.services.notification_categories import (
    CATEGORY_BY_TYPE,
    CATEGORY_INFO,
    NotificationCategory,
    is_mutable,
    muted_categories,
    types_in,
)
from app.services.section_permissions import ProductSection
from app.services.workforce_availability import operational_owner_ids

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    message: str
    link: Optional[str]
    notification_type: str
    is_read: bool
    created_at: Optional[str]
    # Przypomnienie operacyjne kolegi, którego zastępujesz: imię i nazwisko
    # właściciela, żeby dzwonek mówił „w zastępstwie za …" zamiast udawać,
    # że to Twoja sprawa. ``None`` = powiadomienie własne.
    on_behalf_of_name: Optional[str] = None
    # Kategoria z „Moje konto → Powiadomienia" (0349) — dzwonek pokazuje przy
    # pozycji „Nie pokazuj takich" tylko dla kategorii, które wolno wyciszyć.
    category: Optional[str] = None
    category_label: Optional[str] = None
    category_mutable: bool = False

    class Config:
        from_attributes = True


def _category_fields(notification_type: NotificationType) -> dict:
    category = CATEGORY_BY_TYPE.get(notification_type)
    if category is None:
        return {}
    return {
        "category": category.value,
        "category_label": CATEGORY_INFO[category].label,
        "category_mutable": is_mutable(category),
    }


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    unread_count: int
    # Nieprzeczytane WŁASNE (bez przypomnień w zastępstwie). „Oznacz wszystko"
    # oznacza tylko własne, więc front pokazuje przycisk przy `own_unread_count`
    # > 0 — inaczej przy samych cudzych przypomnieniach klik nic nie zmieniał.
    own_unread_count: int = 0


class UnreadCountResponse(BaseModel):
    count: int


class MarkAllReadResponse(BaseModel):
    success: bool
    updated: int
    message: str


# ── Constants ─────────────────────────────────────────────────────────────────

# Bounded page size — keep the bell/list responsive and avoid unbounded scans.
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50

# Historyczna lista „finance-safe" — od 19.08 nieużywana w predykacie
# widoczności (finance widzi feed jak role operacyjne), zostaje wyłącznie
# jako dokumentacja dawnego kontraktu na wypadek powrotu do zawężenia.
_FINANCE_SAFE_NOTIFICATION_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.password_reset_requested,
        NotificationType.password_changed_by_admin,
    }
)


def _notification_visibility(current_user: User):
    """Return the fail-closed notification predicate for the current persona."""

    return notification_visibility_predicate(current_user)


_OPERATIONAL_REMINDERS = frozenset(
    {
        NotificationType.interview_scheduled,
        NotificationType.dl_stage_stale_6h,
        NotificationType.client_feedback_eobd,
        NotificationType.candidate_feedback_1h,
        NotificationType.stage_stuck_7d,
        NotificationType.post_interview_t15,
        NotificationType.post_interview_t45,
        NotificationType.post_interview_t2h_escalation,
        NotificationType.suggest_next_step,
        NotificationType.job_deadline_7d,
        NotificationType.job_deadline_3d,
        NotificationType.job_deadline_1d,
    }
)


def _notification_owner(current_user: User):
    inherited = operational_owner_ids(current_user) - {current_user.id}
    own = Notification.user_id == current_user.id
    if not inherited:
        return own
    return or_(
        own,
        and_(
            Notification.user_id.in_(inherited),
            Notification.is_read.is_(False),
            Notification.notification_type.in_(_OPERATIONAL_REMINDERS),
        ),
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    exclude_section: List[str] = Query(default=[]),
):
    """List notifications for current user — unread first.

    ``exclude_section`` (powtarzalny, np. ``delivery``): widget „Moje zadania"
    pokazuje wyłącznie zdarzenia rekrutacyjne, a sprawy klientów mają osobny
    panel „Moi klienci". Filtr działa i na listę, i na ``unread_count`` —
    licznik liczony bez filtra obiecywałby pozycje, których na liście nie ma.
    Dzwonek nie wysyła parametru i widzi wszystko jak dotąd.

    ``offset`` (B51): dzwonek pokazywał wyłącznie pierwsze ``limit`` pozycji
    bez drogi do starszych; z przesunięciem klient może doładować kolejne.
    Kolejność „nieprzeczytane najpierw" jest stała między stronami, dopóki
    nic nie zostanie oznaczone jako przeczytane — po takiej zmianie klient
    powinien czytać od zera, nie kontynuować przesunięcia.
    """
    try:
        excluded_sections = [ProductSection(value) for value in exclude_section]
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="exclude_section: nieznana sekcja (sourcing, pipeline, delivery, insights)",
        )
    excluded_types = notification_types_for_sections(excluded_sections)
    type_filter = (
        Notification.notification_type.not_in(sorted(excluded_types, key=str))
        if excluded_types
        else true()
    )
    result = await db.execute(
        select(Notification)
        .where(
            _notification_owner(current_user),
            _notification_visibility(current_user),
            type_filter,
        )
        .order_by(
            Notification.is_read.asc(),
            Notification.created_at.desc(),
            Notification.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    notifications = result.scalars().all()

    foreign_owner_ids = {
        n.user_id for n in notifications if n.user_id != current_user.id
    }
    owner_names: dict[int, str] = {}
    if foreign_owner_ids:
        owner_rows = await db.execute(
            select(User.id, User.name).where(User.id.in_(foreign_owner_ids))
        )
        owner_names = {row.id: row.name for row in owner_rows}

    unread_result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            _notification_owner(current_user),
            Notification.is_read.is_(False),
            _notification_visibility(current_user),
            type_filter,
        )
    )
    unread_count = unread_result.scalar() or 0
    own_unread_count = (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == current_user.id,
                Notification.is_read.is_(False),
                _notification_visibility(current_user),
                type_filter,
            )
        )
        or 0
    )

    items = [
        NotificationResponse(
            id=n.id,
            user_id=n.user_id,
            title=n.title,
            message=n.message,
            link=n.link,
            notification_type=n.notification_type.value,
            is_read=n.is_read,
            created_at=n.created_at.isoformat() if n.created_at else None,
            on_behalf_of_name=(
                (owner_names.get(n.user_id) or "nieobecną osobę")
                if n.user_id != current_user.id
                else None
            ),
            **_category_fields(n.notification_type),
        )
        for n in notifications
    ]

    return NotificationListResponse(
        items=items, unread_count=unread_count, own_unread_count=own_unread_count
    )


@router.get("/notifications/count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return just the unread notification count — lightweight for polling."""
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            _notification_owner(current_user),
            Notification.is_read.is_(False),
            _notification_visibility(current_user),
        )
    )
    count = result.scalar() or 0
    return UnreadCountResponse(count=count)


@router.put(
    "/notifications/{notification_id}/read", response_model=NotificationResponse
)
@router.patch(
    "/notifications/{notification_id}/read", response_model=NotificationResponse
)
async def mark_as_read(
    notification_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Mark a single notification as read (supports both PUT and PATCH)."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            _notification_owner(current_user),
            _notification_visibility(current_user),
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Powiadomienie nie znalezione")

    notif.is_read = True
    await db.commit()
    await db.refresh(notif)

    return NotificationResponse(
        id=notif.id,
        user_id=notif.user_id,
        title=notif.title,
        message=notif.message,
        link=notif.link,
        notification_type=notif.notification_type.value,
        is_read=notif.is_read,
        created_at=notif.created_at.isoformat() if notif.created_at else None,
        **_category_fields(notif.notification_type),
    )


@router.put("/notifications/read-all", response_model=MarkAllReadResponse)
@router.patch("/notifications/read-all", response_model=MarkAllReadResponse)
async def mark_all_read(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications as read for current user (supports both PUT and PATCH).

    Tylko WŁASNE wiersze: przypomnienia nieobecnego kolegi widoczne
    w zastępstwie zostają nieprzeczytane — „Oznacz wszystko" zastępcy nie może
    zamknąć spraw, które właściciel zobaczy po powrocie. Pojedyncze
    przypomnienie zastępca nadal gasi świadomie kliknięciem.
    """
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
            _notification_visibility(current_user),
        )
        .values(is_read=True)
    )
    await db.commit()
    return MarkAllReadResponse(
        success=True,
        updated=result.rowcount or 0,
        message="Wszystkie powiadomienia oznaczone jako przeczytane",
    )


# ── Własne ustawienia: które kategorie powiadomień przychodzą (0349) ─────────


class NotificationCategoryPreference(BaseModel):
    key: str
    label: str
    description: str
    mandatory: bool
    muted: bool
    # Ile powiadomień tej kategorii przyszło w ostatnich 30 dniach (także
    # w czasie wyciszenia) — pomaga zdecydować, co wyłączyć.
    received_30d: int


class NotificationPreferencesResponse(BaseModel):
    categories: List[NotificationCategoryPreference]


class NotificationCategoryUpdate(BaseModel):
    muted: bool


# Typy kontekstowe nie mają stałej sekcji — decyduje link albo rodzaj czatu.
# Kategoria jest pokazywana, gdy KTÓRYKOLWIEK z tych wariantów może dotrzeć.
_CONTEXT_PROBES: dict[
    NotificationType, tuple[tuple[Optional[str], Optional[str]], ...]
] = {
    NotificationType.job_chat_message: ((None, None), ("candidate_chat_message", None)),
    NotificationType.job_chat_mention: ((None, None), ("candidate_chat_message", None)),
    NotificationType.note_mention: tuple(
        (None, link)
        for link in ("/candidates", "/jobs", "/clients", "/insights", "/finance")
    ),
    NotificationType.pending_verification: ((None, "/jobs/0"),),
}


def _category_reachable(user: User, category: NotificationCategory) -> bool:
    for ntype in types_in(category):
        probes = _CONTEXT_PROBES.get(ntype, ((None, None),))
        for related_entity_type, link in probes:
            if user_may_receive_type(
                user, ntype, related_entity_type=related_entity_type, link=link
            ):
                return True
    return False


async def _preferences_response(
    db: AsyncSession, user: User
) -> NotificationPreferencesResponse:
    counts_rows = await db.execute(
        select(Notification.notification_type, func.count())
        .where(
            Notification.user_id == user.id,
            Notification.created_at >= func.now() - func.make_interval(0, 0, 0, 30),
        )
        .group_by(Notification.notification_type)
    )
    per_category: dict[NotificationCategory, int] = {}
    for ntype, count in counts_rows.all():
        category = CATEGORY_BY_TYPE.get(ntype)
        if category is not None:
            per_category[category] = per_category.get(category, 0) + int(count)

    muted = muted_categories(user.muted_notification_categories)
    return NotificationPreferencesResponse(
        categories=[
            NotificationCategoryPreference(
                key=category.value,
                label=info.label,
                description=info.description,
                mandatory=info.mandatory,
                muted=category in muted,
                received_30d=per_category.get(category, 0),
            )
            for category, info in CATEGORY_INFO.items()
            if _category_reachable(user, category)
        ]
    )


@router.get(
    "/notifications/preferences", response_model=NotificationPreferencesResponse
)
async def get_notification_preferences(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Kategorie powiadomień, które mogą do mnie trafić, i czy są wyciszone."""
    return await _preferences_response(db, current_user)


@router.put(
    "/notifications/preferences/{category}",
    response_model=NotificationPreferencesResponse,
)
async def set_notification_category(
    category: str,
    payload: NotificationCategoryUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Włącza albo wycisza jedną kategorię — ze strony ustawień i z dzwonka.

    Ponowne włączenie oznacza jako przeczytane powiadomienia tej kategorii
    utworzone W CZASIE wyciszenia: bez tego dzwonek po włączeniu pokazałby
    naraz wszystko, co przyszło przez ten czas. Starsze nieprzeczytane
    zostają — „Cofnij" tuż po wyciszeniu niczego nie gasi.
    """
    try:
        target = NotificationCategory(category)
    except ValueError:
        raise HTTPException(status_code=404, detail="Nieznana kategoria powiadomień")
    if not is_mutable(target):
        raise HTTPException(
            status_code=422,
            detail=f"Kategorii „{CATEGORY_INFO[target].label}” nie można wyłączyć.",
        )

    # Blokada wiersza: dwie karty zmieniające różne kategorie naraz nie mogą
    # nadpisać sobie nawzajem słownika wyciszeń.
    await db.refresh(current_user, with_for_update=True)
    stored = dict(current_user.muted_notification_categories or {})
    key = target.value

    if payload.muted and key not in stored:
        stored[key] = datetime.now(timezone.utc).isoformat()
        current_user.muted_notification_categories = stored
    elif not payload.muted and key in stored:
        muted_at_raw = stored.pop(key)
        current_user.muted_notification_categories = stored
        try:
            muted_at = datetime.fromisoformat(str(muted_at_raw))
        except ValueError:
            muted_at = None
        if muted_at is not None:
            await db.execute(
                update(Notification)
                .where(
                    Notification.user_id == current_user.id,
                    Notification.is_read.is_(False),
                    Notification.notification_type.in_(
                        sorted(types_in(target), key=str)
                    ),
                    Notification.created_at >= muted_at,
                )
                .values(is_read=True)
            )
    await db.commit()
    await db.refresh(current_user)
    return await _preferences_response(db, current_user)


# ── Helper — create notifications from other endpoints ────────────────────────


async def create_notification(
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    notification_type: NotificationType,
    link: Optional[str] = None,
    related_entity_type: Optional[str] = None,
    related_entity_id: Optional[int] = None,
    dedupe_resurface: bool = False,
) -> Notification:
    """Helper to create a notification. Call from other API endpoints.

    When ``dedupe_resurface`` is True and an entity reference is supplied,
    an existing notification for the same (user, type, entity) that was
    created today is updated in place instead of inserting a new row —
    the notification is re-surfaced as unread and its message/created_at
    are refreshed. This keeps bursts of edits from piling up multiple
    unread rows while still re-notifying a user who already read today's
    alert when a new change arrives.

    Works with the partial unique index ``ix_notif_dedup_daily`` added in
    migration 0029_notifications_triggers — that index guarantees at most
    one row per (user, type, entity, day).

    Note: caller is responsible for ``db.commit()``.
    """
    if dedupe_resurface and related_entity_id is not None:
        existing = await _todays_notification(
            db, user_id, notification_type, related_entity_id
        )
        if existing is not None:
            return _resurface(existing, title, message, link, related_entity_type)

    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        link=link,
        notification_type=notification_type,
        is_read=False,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
    if not (dedupe_resurface and related_entity_id is not None):
        db.add(notif)
        return notif

    # Dwa równoległe zapisy (np. dwa zapisy profilu Championa w tej samej
    # sekundzie) oba nie widzą dzisiejszego wiersza i oba wstawiają — drugi
    # trafia w `ix_notif_dedup_daily`. Savepoint zamienia to w ponowne
    # wyświetlenie istniejącego wiersza zamiast 500 na całym żądaniu.
    try:
        async with db.begin_nested():
            db.add(notif)
            await db.flush()
    except IntegrityError:
        existing = await _todays_notification(
            db, user_id, notification_type, related_entity_id
        )
        if existing is None:
            raise
        return _resurface(existing, title, message, link, related_entity_type)
    return notif


def _warsaw_day(column):
    """Doba lokalna Europe/Warsaw — TO SAMO wyrażenie co w indeksie
    ``ix_notif_dedup_daily`` (``entrypoint.sh``). Do 09.2026 porównanie szło
    po dobie w strefie sesji (UTC): wiersz z 00:30 czasu polskiego należał do
    „wczoraj", zapytanie go nie znajdowało, a INSERT wywracał się na indeksie."""
    return func.date_trunc("day", func.timezone("Europe/Warsaw", column))


async def _todays_notification(
    db: AsyncSession,
    user_id: int,
    notification_type: NotificationType,
    related_entity_id: int,
) -> Optional[Notification]:
    # Klucz indeksu nie zawiera `related_entity_type`, więc wyszukiwanie też
    # go pomija — inaczej wiersz kolidujący z indeksem byłby „niewidoczny".
    return await db.scalar(
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.notification_type == notification_type,
            Notification.related_entity_id == related_entity_id,
            _warsaw_day(Notification.created_at) == _warsaw_day(func.now()),
        )
        .order_by(Notification.created_at.desc())
        .limit(1)
    )


def _resurface(
    existing: Notification,
    title: str,
    message: str,
    link: Optional[str],
    related_entity_type: Optional[str],
) -> Notification:
    existing.title = title
    existing.message = message
    existing.link = link
    existing.related_entity_type = related_entity_type
    existing.is_read = False
    existing.created_at = func.now()
    return existing
