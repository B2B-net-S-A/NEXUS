"""
Notifications API
User notification system with unread badge support.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, case, func, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.api.deps import CurrentUser
from app.services import chat_notifications
from app.services.mention_dispatch import CHAT_NOTIFICATION_TYPES
from app.services.notification_access import (
    notification_types_for_sections,
    notification_visibility_predicate,
    role_muted_types_of,
    user_may_receive_type,
)
from app.services.hr import program as hr_program
from app.services.notification_categories import (
    CATEGORY_BY_TYPE,
    CATEGORY_INFO,
    NotificationCategory,
    is_mutable,
    muted_categories,
    types_in,
)
from app.services.notification_topics import (
    TOAST_TYPES,
    NotificationTopic,
    job_key_expression,
    topic_for,
    types_in_topic,
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
    # Nieprzeczytane według tematu ikony paska (16.10.2026) — poranny brief
    # Jarvisa mówi o rekrutacjach i CV, nie o sumie dawnego dzwonka.
    by_topic: dict[str, int] = Field(default_factory=dict)


class ChatThreadResponse(BaseModel):
    """Jedna rozmowa w okienku „Wiadomości”: czat rekrutacji, kandydata
    albo wątek notatki (wzmianka, odpowiedź)."""

    kind: Literal["job", "candidate", "note"]
    entity_id: int
    title: str
    subtitle: Optional[str] = None
    unread_count: int
    has_mention: bool
    last_author_name: Optional[str] = None
    last_message: str
    last_at: Optional[str] = None
    link: str


class ChatThreadListResponse(BaseModel):
    items: List[ChatThreadResponse]
    # Rozmowy z nowymi wiadomościami w całym oknie 30 dni, nie tylko na
    # zwróconej stronie — to jest licznik na ikonie.
    unread_threads: int


class ChatThreadsReadRequest(BaseModel):
    kind: Optional[Literal["job", "candidate", "note"]] = None
    entity_id: Optional[int] = None
    # Wątek notatki rozpoznajemy po linku (jak w liście wątków).
    link: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _thread_is_complete(self) -> "ChatThreadsReadRequest":
        if self.kind == "note":
            if not self.link or not self.link.startswith("/"):
                raise ValueError("Podaj link wątku notatki.")
            return self
        if (self.kind is None) != (self.entity_id is None):
            raise ValueError("Podaj rodzaj rozmowy razem z jej numerem.")
        return self


class MarkAllReadResponse(BaseModel):
    success: bool
    updated: int
    message: str


# ── Constants ─────────────────────────────────────────────────────────────────

# Bounded page size — keep the bell/list responsive and avoid unbounded scans.
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50
_CHAT_THREADS_DEFAULT_LIMIT = 30
_CHAT_THREADS_MAX_LIMIT = 100

# Okienko „Rozmowy” (13.10.2026): cała kategoria „Rozmowy” — rozmowy u klienta,
# prepy, terminy, telefon po rozmowie i przypomnienia kalendarza.
_INTERVIEW_TYPES = tuple(sorted(types_in(NotificationCategory.interviews), key=str))
# Starszej sprawy nikt już nie załatwia z powiadomienia — zostaje na ekranie
# „Rozmowy u klienta”.
_INTERVIEW_WINDOW_DAYS = 7
_INTERVIEW_WINDOW_LIMIT = 50
_INTERVIEW_READ_MAX_IDS = 100


class InterviewNotificationListResponse(BaseModel):
    items: List[NotificationResponse]


class InterviewNotificationsReadRequest(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=_INTERVIEW_READ_MAX_IDS)


# Okienko „Rekrutacje” (16.10.2026, w miejscu dzwonka): moje rekrutacje
# z nowościami z 7 dni — ruchy kandydatów, przydział, termin, Champion,
# osoby od automatu. Jedna pozycja na rekrutację; wiersz bez rekrutacji
# („Twoje requesty na dziś”) to pozycja po swoim linku.
_JOB_TOPIC_TYPES = tuple(sorted(types_in_topic(NotificationTopic.jobs), key=str))
_JOB_TOPIC_TASK_TYPES = tuple(
    sorted((t for t in _JOB_TOPIC_TYPES if t in TOAST_TYPES), key=str)
)
_JOB_THREADS_WINDOW_DAYS = 7
_JOB_THREADS_LIMIT = 30
_TOPIC_READ_MAX_IDS = 100


class JobThreadResponse(BaseModel):
    """Jedna rekrutacja (albo pozycja bez rekrutacji) w okienku „Rekrutacje”."""

    job_id: Optional[int] = None
    title: str
    subtitle: Optional[str] = None
    unread_count: int
    # Wśród nowych jest coś imiennego (przydział, zadanie stawki…).
    has_task: bool
    last_title: str
    last_message: str
    last_at: Optional[str] = None
    link: str


class JobThreadListResponse(BaseModel):
    items: List[JobThreadResponse]
    # Rekrutacje (i pozycje bez rekrutacji) z nowymi w całym oknie 7 dni —
    # liczba na ikonie.
    unread_jobs: int


# Okienko „Umowy” (26.10.2026): umowy w podpisie — czeka na mój podpis,
# kontraktor podpisał, podpisana, link wygasł, prośba o potwierdzenie.
# Jedna pozycja na umowę (encja zdarzenia); wiersz bez encji — po linku.
_CONTRACT_TOPIC_TYPES = tuple(
    sorted(types_in_topic(NotificationTopic.contracts), key=str)
)
_CONTRACT_THREADS_WINDOW_DAYS = 14
_CONTRACT_THREADS_LIMIT = 30
_CONTRACT_DEFAULT_LINK = "/contracts/b2b-generator?tab=generated"


class ContractThreadResponse(BaseModel):
    """Jedna umowa w okienku „Umowy”."""

    key: str
    title: str
    message: str
    unread_count: int
    # Nieprzeczytane wiersze tej pozycji — klik gasi je przez `topics/read`.
    unread_ids: List[int]
    last_at: Optional[str] = None
    link: str


class ContractThreadListResponse(BaseModel):
    items: List[ContractThreadResponse]
    # Umowy z nowymi w całym oknie — liczba na ikonie.
    unread_contracts: int


_INT4_MAX = 2_147_483_647


class TopicReadRequest(BaseModel):
    topic: NotificationTopic
    job_id: Optional[int] = Field(default=None, ge=1, le=_INT4_MAX)
    link: Optional[str] = Field(default=None, max_length=1000)
    ids: Optional[List[Annotated[int, Field(ge=1, le=_INT4_MAX)]]] = Field(
        default=None, min_length=1, max_length=_TOPIC_READ_MAX_IDS
    )
    # Klik w pozycję okienka gasi też przypomnienia nieobecnego kolegi
    # (świadomie, jak klik w dzwonku). Samo wejście na ekran rekrutacji wysyła
    # `false` — wtedy tylko własne wiersze.
    include_covered: bool = True

    @model_validator(mode="after")
    def _one_target(self) -> "TopicReadRequest":
        targets = [x for x in (self.job_id, self.link, self.ids) if x is not None]
        if len(targets) > 1:
            raise ValueError("Wskaż rekrutację, link albo listę — jedno naraz.")
        if self.link is not None and not self.link.startswith("/"):
            raise ValueError("Link musi prowadzić do ekranu NEXUSA.")
        return self


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


async def _list_items(
    db: AsyncSession, notifications, current_user: User
) -> List[NotificationResponse]:
    """Wiersze listy z podpisem „w zastępstwie za …” przy cudzych przypomnieniach."""
    foreign_owner_ids = {
        n.user_id for n in notifications if n.user_id != current_user.id
    }
    owner_names: dict[int, str] = {}
    if foreign_owner_ids:
        owner_rows = await db.execute(
            select(User.id, User.name).where(User.id.in_(foreign_owner_ids))
        )
        owner_names = {row.id: row.name for row in owner_rows}
    return [
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


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    exclude_section: List[str] = Query(default=[]),
    exclude_chat: bool = Query(False),
    exclude_interviews: bool = Query(False),
    topic: List[NotificationTopic] = Query(default=[]),
):
    """List notifications for current user — unread first.

    ``topic`` (powtarzalny, 16.10.2026): tylko typy wskazanych tematów ikon
    paska (`services/notification_topics.py`). Filtr pozytywny — backend,
    który go nie zna, zwróci więcej, nigdy mniej.

    ``exclude_chat``: dzwonek nie pokazuje ani nie liczy powiadomień czatów —
    od 09.10.2026 mają własne okienko (``GET /notifications/chats``).

    ``exclude_interviews``: to samo dla kategorii „Rozmowy” u osób, które mają
    okienko „Rozmowy” (``GET /notifications/interviews``, 13.10.2026).

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
    excluded_types = set(notification_types_for_sections(excluded_sections))
    if exclude_chat:
        excluded_types.update(CHAT_NOTIFICATION_TYPES)
    if exclude_interviews:
        excluded_types.update(_INTERVIEW_TYPES)
    type_filter = (
        Notification.notification_type.not_in(sorted(excluded_types, key=str))
        if excluded_types
        else true()
    )
    if topic:
        wanted = set().union(*(types_in_topic(t) for t in topic))
        type_filter = and_(
            type_filter,
            Notification.notification_type.in_(sorted(wanted, key=str)),
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

    return NotificationListResponse(
        items=await _list_items(db, notifications, current_user),
        unread_count=unread_count,
        own_unread_count=own_unread_count,
    )


@router.get("/notifications/count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return just the unread notification count — lightweight for polling.

    ``by_topic``: te same nieprzeczytane rozbite na tematy ikon paska.
    """
    result = await db.execute(
        select(Notification.notification_type, func.count())
        .where(
            _notification_owner(current_user),
            Notification.is_read.is_(False),
            _notification_visibility(current_user),
        )
        .group_by(Notification.notification_type)
    )
    by_topic: dict[str, int] = {}
    count = 0
    for ntype, n in result.all():
        count += int(n)
        key = topic_for(ntype).value
        by_topic[key] = by_topic.get(key, 0) + int(n)
    return UnreadCountResponse(count=count, by_topic=by_topic)


# ── Okienko „Czaty”: powiadomienia czatów pogrupowane w rozmowy ──────────────


@router.get("/notifications/chats", response_model=ChatThreadListResponse)
async def list_chat_threads(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(_CHAT_THREADS_DEFAULT_LIMIT, ge=1, le=_CHAT_THREADS_MAX_LIMIT),
    include_notes: bool = Query(False),
):
    """Rozmowy z ostatnich 30 dni — nieprzeczytane najpierw.

    Jedna pozycja na czat rekrutacji albo kandydata; ``link`` prowadzi do
    pierwszej nieprzeczytanej wiadomości. Widoczność jak w dzwonku (sekcja
    i wyciszona kategoria „Czat”) stosuje ``chat_notifications.list_threads``.
    ``include_notes`` (okienko „Wiadomości”, 16.10.2026): także wątki wzmianek
    i odpowiedzi w notatkach (``kind="note"``, jeden na link notatki).
    """
    threads, unread_threads = await chat_notifications.list_threads(
        db, current_user, limit=limit, include_notes=include_notes
    )
    return ChatThreadListResponse(
        items=[
            ChatThreadResponse(
                kind=thread.kind,
                entity_id=thread.entity_id,
                title=thread.title,
                subtitle=thread.subtitle,
                unread_count=thread.unread_count,
                has_mention=thread.has_mention,
                last_author_name=thread.last_author_name,
                last_message=thread.last_message,
                last_at=thread.last_at.isoformat() if thread.last_at else None,
                link=thread.link,
            )
            for thread in threads
        ],
        unread_threads=unread_threads,
    )


@router.put("/notifications/chats/read", response_model=MarkAllReadResponse)
async def mark_chat_threads_read(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    body: Optional[ChatThreadsReadRequest] = None,
    include_notes: bool = Query(False),
):
    """Oznacz powiadomienia czatów jako przeczytane: jednej rozmowy albo wszystkich.

    ``kind="note"`` z ``link`` — jeden wątek notatki. Bez ciała
    z ``include_notes`` — wszystkie czaty i notatki („Oznacz wszystkie”
    w okienku „Wiadomości”). Backend bez tego parametru zgasi same czaty —
    nigdy więcej, niż okienko pokazuje.
    """
    updated = await chat_notifications.mark_read(
        db,
        current_user.id,
        kind=body.kind if body else None,
        entity_id=body.entity_id if body else None,
        link=body.link if body else None,
        include_notes=include_notes,
        extra=_notification_visibility(current_user),
    )
    await db.commit()
    return MarkAllReadResponse(
        success=True,
        updated=updated,
        message="Powiadomienia czatów oznaczone jako przeczytane",
    )


# ── Okienko „Rozmowy”: rozmowy u klienta, prepy, przypomnienia kalendarza ────


@router.get(
    "/notifications/interviews", response_model=InterviewNotificationListResponse
)
async def list_interview_notifications(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Nieprzeczytane powiadomienia kategorii „Rozmowy” z ostatnich 7 dni.

    Okienko „Rozmowy” w górnym pasku: zadania bierze z ``GET /interview-cycle``,
    stąd — to, co przyszło i czego nikt jeszcze nie otworzył. Własne wiersze
    i przypomnienia w zastępstwie, jak w dzwonku.
    """
    since = datetime.now(timezone.utc) - timedelta(days=_INTERVIEW_WINDOW_DAYS)
    result = await db.execute(
        select(Notification)
        .where(
            _notification_owner(current_user),
            _notification_visibility(current_user),
            Notification.notification_type.in_(_INTERVIEW_TYPES),
            Notification.is_read.is_(False),
            Notification.created_at >= since,
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(_INTERVIEW_WINDOW_LIMIT)
    )
    return InterviewNotificationListResponse(
        items=await _list_items(db, result.scalars().all(), current_user)
    )


@router.put("/notifications/interviews/read", response_model=MarkAllReadResponse)
async def mark_interview_notifications_read(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    body: Optional[InterviewNotificationsReadRequest] = None,
):
    """Oznacz powiadomienia kategorii „Rozmowy” jako przeczytane.

    Z ``ids`` — wskazane wiersze (klik w pozycję okienka), także przypomnienie
    w zastępstwie, jak pojedyncze kliknięcie w dzwonku. Bez ciała — wszystkie
    WŁASNE, jak ``read-all``. Osobna trasa, nie parametr ``read-all``: backend
    sprzed tej zmiany zignorowałby nieznany parametr i zgasił cały dzwonek.
    """
    owner = (
        and_(_notification_owner(current_user), Notification.id.in_(body.ids))
        if body
        else Notification.user_id == current_user.id
    )
    result = await db.execute(
        update(Notification)
        .where(
            owner,
            Notification.is_read.is_(False),
            Notification.notification_type.in_(_INTERVIEW_TYPES),
            _notification_visibility(current_user),
        )
        .values(is_read=True)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return MarkAllReadResponse(
        success=True,
        updated=result.rowcount or 0,
        message="Powiadomienia o rozmowach oznaczone jako przeczytane",
    )


# ── Okienko „Rekrutacje”: moje rekrutacje z nowościami (16.10.2026) ──────────


@router.get("/notifications/jobs", response_model=JobThreadListResponse)
async def list_job_threads(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Rekrutacje z powiadomieniami tematu „Rekrutacje” z 7 dni — nowe najpierw.

    Jedna pozycja na rekrutację (ścieżka ``/jobs/{id}``, parametr ``?job=``
    albo encja „job”); wiersz bez rekrutacji to pozycja po swoim linku.
    Własne wiersze i przypomnienia w zastępstwie, widoczność jak w każdym
    okienku. Liczba na ikonie = ``unread_jobs``.
    """
    since = datetime.now(timezone.utc) - timedelta(days=_JOB_THREADS_WINDOW_DAYS)
    rows_in_window = (
        select(
            Notification.id,
            Notification.link,
            Notification.is_read,
            Notification.notification_type,
            job_key_expression(Notification).label("job_key"),
        )
        .where(
            _notification_owner(current_user),
            _notification_visibility(current_user),
            Notification.notification_type.in_(_JOB_TOPIC_TYPES),
            Notification.created_at >= since,
        )
        .subquery()
    )
    job_key = rows_in_window.c.job_key
    # Bez parametrów wiązanych w kluczu grupy: ten sam tekst w SELECT i GROUP BY.
    link_key = case((job_key.is_(None), rows_in_window.c.link), else_=None)
    unread = rows_in_window.c.is_read.is_(False)
    unread_rows = func.count().filter(unread)
    latest_id = func.max(rows_in_window.c.id)
    grouped = (
        await db.execute(
            select(
                job_key.label("job_id"),
                link_key.label("link_key"),
                unread_rows.label("unread_count"),
                func.count()
                .filter(
                    unread,
                    rows_in_window.c.notification_type.in_(_JOB_TOPIC_TASK_TYPES),
                )
                .label("unread_tasks"),
                latest_id.label("latest_id"),
            )
            .group_by(job_key, link_key)
            .order_by((unread_rows > 0).desc(), latest_id.desc())
            .limit(_JOB_THREADS_LIMIT)
        )
    ).all()
    unread_groups = (
        select(job_key, link_key).where(unread).group_by(job_key, link_key).subquery()
    )
    unread_jobs = int(
        await db.scalar(select(func.count()).select_from(unread_groups)) or 0
    )
    if not grouped:
        return JobThreadListResponse(items=[], unread_jobs=unread_jobs)

    latest_rows = {
        n.id: n
        for n in (
            await db.execute(
                select(Notification).where(
                    Notification.id.in_(sorted(row.latest_id for row in grouped))
                )
            )
        )
        .scalars()
        .all()
    }
    titles = await chat_notifications.job_names(
        db, [row.job_id for row in grouped if row.job_id is not None]
    )
    items: List[JobThreadResponse] = []
    for row in grouped:
        latest = latest_rows.get(row.latest_id)
        if latest is None:
            continue
        if row.job_id is not None:
            title, client = titles.get(row.job_id, ("", None))
            title = title or f"Rekrutacja #{row.job_id}"
            link = f"/jobs/{row.job_id}"
        else:
            title, client = latest.title, None
            link = latest.link or "/jobs"
        items.append(
            JobThreadResponse(
                job_id=row.job_id,
                title=title,
                subtitle=client,
                unread_count=int(row.unread_count or 0),
                has_task=bool(row.unread_tasks),
                last_title=latest.title,
                last_message=latest.message,
                last_at=latest.created_at.isoformat() if latest.created_at else None,
                link=link,
            )
        )
    return JobThreadListResponse(items=items, unread_jobs=unread_jobs)


# ── Okienko „Umowy”: umowy w podpisie z nowościami (26.10.2026) ──────────────


@router.get("/notifications/contracts", response_model=ContractThreadListResponse)
async def list_contract_threads(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Umowy z powiadomieniami tematu „Umowy” z 14 dni — nowe najpierw.

    Jedna pozycja na umowę: para (typ encji, id encji) zdarzenia; wiersz bez
    encji to pozycja po swoim linku. Własne wiersze i przypomnienia
    w zastępstwie, widoczność jak w każdym okienku. Liczba na ikonie =
    ``unread_contracts`` (każde nowe zdarzenie umowy ją podbija).
    """
    since = datetime.now(timezone.utc) - timedelta(days=_CONTRACT_THREADS_WINDOW_DAYS)
    rows_in_window = (
        select(
            Notification.id,
            Notification.link,
            Notification.is_read,
            Notification.related_entity_type,
            Notification.related_entity_id,
        )
        .where(
            _notification_owner(current_user),
            _notification_visibility(current_user),
            Notification.notification_type.in_(_CONTRACT_TOPIC_TYPES),
            Notification.created_at >= since,
        )
        .subquery()
    )
    entity_id = rows_in_window.c.related_entity_id
    entity_type = case(
        (entity_id.is_(None), None), else_=rows_in_window.c.related_entity_type
    )
    # Bez parametrów wiązanych w kluczu grupy: ten sam tekst w SELECT i GROUP BY.
    link_key = case((entity_id.is_(None), rows_in_window.c.link), else_=None)
    unread = rows_in_window.c.is_read.is_(False)
    unread_rows = func.count().filter(unread)
    latest_id = func.max(rows_in_window.c.id)
    grouped = (
        await db.execute(
            select(
                entity_type.label("entity_type"),
                entity_id.label("entity_id"),
                link_key.label("link_key"),
                unread_rows.label("unread_count"),
                func.array_agg(rows_in_window.c.id).filter(unread).label("unread_ids"),
                latest_id.label("latest_id"),
            )
            .group_by(entity_type, entity_id, link_key)
            .order_by((unread_rows > 0).desc(), latest_id.desc())
            .limit(_CONTRACT_THREADS_LIMIT)
        )
    ).all()
    unread_groups = (
        select(entity_type, entity_id, link_key)
        .where(unread)
        .group_by(entity_type, entity_id, link_key)
        .subquery()
    )
    unread_contracts = int(
        await db.scalar(select(func.count()).select_from(unread_groups)) or 0
    )
    if not grouped:
        return ContractThreadListResponse(items=[], unread_contracts=unread_contracts)

    latest_rows = {
        n.id: n
        for n in (
            await db.execute(
                select(Notification).where(
                    Notification.id.in_(sorted(row.latest_id for row in grouped))
                )
            )
        )
        .scalars()
        .all()
    }
    items: List[ContractThreadResponse] = []
    for row in grouped:
        latest = latest_rows.get(row.latest_id)
        if latest is None:
            continue
        key = (
            f"{row.entity_type}:{row.entity_id}"
            if row.entity_id is not None
            else f"link:{row.link_key or ''}"
        )
        items.append(
            ContractThreadResponse(
                key=key,
                title=latest.title,
                message=latest.message,
                unread_count=int(row.unread_count or 0),
                unread_ids=sorted(row.unread_ids or [])[:_TOPIC_READ_MAX_IDS],
                last_at=latest.created_at.isoformat() if latest.created_at else None,
                link=latest.link or _CONTRACT_DEFAULT_LINK,
            )
        )
    return ContractThreadListResponse(items=items, unread_contracts=unread_contracts)


@router.put("/notifications/topics/read", response_model=MarkAllReadResponse)
async def mark_topic_read(
    body: TopicReadRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Oznacz jako przeczytane powiadomienia jednego tematu ikony paska.

    Z ``job_id`` — jednej rekrutacji (klik w pozycję albo wejście na jej
    ekran), z ``link`` — pozycji bez rekrutacji, z ``ids`` — wskazanych
    wierszy; także przypomnienia w zastępstwie, jak pojedynczy klik. Bez
    wskazania — wszystkie WŁASNE wiersze tematu. Osobna trasa, nie parametr
    ``read-all``: backend sprzed zmiany zignorowałby nieznany parametr
    i zgasił wszystko.
    """
    whose = (
        _notification_owner(current_user)
        if body.include_covered
        else Notification.user_id == current_user.id
    )
    if body.job_id is not None:
        owner = and_(whose, job_key_expression(Notification) == body.job_id)
    elif body.link is not None:
        owner = and_(whose, Notification.link == body.link)
    elif body.ids is not None:
        owner = and_(whose, Notification.id.in_(body.ids))
    else:
        owner = Notification.user_id == current_user.id
    result = await db.execute(
        update(Notification)
        .where(
            owner,
            Notification.is_read.is_(False),
            Notification.notification_type.in_(
                sorted(types_in_topic(body.topic), key=str)
            ),
            _notification_visibility(current_user),
        )
        .values(is_read=True)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return MarkAllReadResponse(
        success=True,
        updated=result.rowcount or 0,
        message="Powiadomienia oznaczone jako przeczytane",
    )


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
    exclude_chat: bool = Query(False),
    exclude_interviews: bool = Query(False),
):
    """Mark all notifications as read for current user (supports both PUT and PATCH).

    ``exclude_chat``: „Oznacz wszystko” w dzwonku nie gasi czatów, których
    dzwonek nie pokazuje — te gasi okienko „Czaty” albo wejście do czatu.
    ``exclude_interviews``: to samo dla kategorii „Rozmowy” i okienka „Rozmowy”.

    Tylko WŁASNE wiersze: przypomnienia nieobecnego kolegi widoczne
    w zastępstwie zostają nieprzeczytane — „Oznacz wszystko" zastępcy nie może
    zamknąć spraw, które właściciel zobaczy po powrocie. Pojedyncze
    przypomnienie zastępca nadal gasi świadomie kliknięciem.
    """
    excluded_types = [
        *(CHAT_NOTIFICATION_TYPES if exclude_chat else ()),
        *(_INTERVIEW_TYPES if exclude_interviews else ()),
    ]
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
            _notification_visibility(current_user),
            (
                Notification.notification_type.not_in(excluded_types)
                if excluded_types
                else true()
            ),
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
    # Administrator wyłączył całą kategorię dla ról tego konta (tabela „Kto co
    # dostaje”) — własny przełącznik niczego wtedy nie włączy.
    role_muted: bool = False


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
    if hr_program.hides_category(category.value):
        return False
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
    role_muted = role_muted_types_of(user)
    return NotificationPreferencesResponse(
        categories=[
            NotificationCategoryPreference(
                key=category.value,
                label=info.label,
                description=info.description,
                mandatory=info.mandatory,
                muted=category in muted,
                received_30d=per_category.get(category, 0),
                role_muted=types_in(category) <= role_muted,
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
