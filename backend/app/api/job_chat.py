"""Job Chat API — internal team chat per recruitment.

Wszystkie endpointy pod `/api/jobs/{job_id}/chat/...`. Auth wymaga
członkostwa w projekcie (admin / recruiter / DL / TAC / aktywny collaborator).

Realtime: po każdej operacji modyfikującej (create/edit/delete/pin) emitujemy
WS event do każdego członka projektu via istniejący `ConnectionManager`
z `app.api.ws`. Eventy z prefix'em `chat:message:`.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import (
    CandidatePIIAccess,
    CandidateWriteAccess,
    user_can_access_candidate_domain,
)
from app.api.deps import DeliveryLeadPlus
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.api.ws import notify_user
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.chat_reaction import JobChatMessageReaction
from app.models.job import Job
from app.models.job_chat import JobChatMention, JobChatMessage, JobChatReadState
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.models.user_activity import UserActionType, UserActivity
from app.schemas.job_chat import (
    ChatMessageCreate,
    ChatMessageList,
    ChatMessageResponse,
    ChatMessageUpdate,
    ChatPinResponse,
    ChatUnreadCount,
    ChatUserMini,
    ReactionAggregate,
    ReactionToggleResponse,
    ReadByUser,
)
from app.services.chat_reactions import aggregate_job_reactions
from app.services.job_membership import (
    is_member_of_job,
    list_job_member_ids,
    list_job_members,
)
from app.services.mention_dispatch import (
    refresh_chat_message_snippets,
    retract_chat_message_notifications,
)
from app.services.mention_parser import parse_mentions

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

DELETED_PLACEHOLDER = "[wiadomość usunięta]"
MAX_PINNED_PER_JOB = 3
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _require_member(db: AsyncSession, user: User, job_id: int) -> None:
    """Dostęp do czatu rekrutacji: każda rola wewnętrzna czyta i pisze.

    Decyzja Artura 23.09.2026 — czat to rozmowa o rekrutacji, a pytanie osoby
    spoza zespołu też ma wartość. Do tej daty wpuszczał wyłącznie zespół
    (nawet DL i HoR spoza zespołu dostawali 403). Stara rola podglądu
    ``user`` i konta nieaktywne nadal przechodzą wyłącznie przez członkostwo.
    """
    if user_can_access_candidate_domain(user):
        if await db.get(Job, job_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rekrutacja nie istnieje.",
            )
        return
    if not await is_member_of_job(db, user, job_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak dostępu do czatu tego projektu.",
        )


async def _require_read_access(db: AsyncSession, user: User, job_id: int) -> None:
    """Odczyt czatu — ta sama reguła co zapis (patrz ``_require_member``)."""
    await _require_member(db, user, job_id)


def _user_to_mini(user: Optional[User]) -> Optional[ChatUserMini]:
    if user is None:
        return None
    return ChatUserMini(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
    )


def _reply_preview(content: str, limit: int = 120) -> str:
    cleaned = " ".join((content or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


async def _serialize_many(
    db: AsyncSession, msgs: list[JobChatMessage]
) -> list[ChatMessageResponse]:
    """Hurtowo: autorzy, cytowane wiadomości, wzmianki, reakcje — stała liczba zapytań.

    Runda 10 (R10-N6-11): wersja per wiadomość robiła ~4 zapytania na wiersz
    (do 800 przy ``limit=200``); lustro ``candidate_chat._serialize_many``.
    """
    if not msgs:
        return []

    author_ids = {m.author_id for m in msgs if m.author_id is not None}
    authors_map: dict[int, User] = {}
    if author_ids:
        rows = await db.execute(select(User).where(User.id.in_(author_ids)))
        for u in rows.scalars().all():
            authors_map[u.id] = u

    parent_ids = {
        m.reply_to_message_id for m in msgs if m.reply_to_message_id is not None
    }
    parents_map: dict[int, JobChatMessage] = {}
    if parent_ids:
        rows = await db.execute(
            select(JobChatMessage).where(JobChatMessage.id.in_(parent_ids))
        )
        for parent in rows.scalars().all():
            parents_map[parent.id] = parent

    msg_ids = [m.id for m in msgs]
    mentions_map: dict[int, list[int]] = {}
    rows = await db.execute(
        select(JobChatMention.message_id, JobChatMention.user_id).where(
            JobChatMention.message_id.in_(msg_ids)
        )
    )
    for mid, uid in rows.all():
        mentions_map.setdefault(mid, []).append(uid)

    reactions_map = await aggregate_job_reactions(db, msg_ids)

    out: list[ChatMessageResponse] = []
    for msg in msgs:
        author = authors_map.get(msg.author_id) if msg.author_id is not None else None
        reply_preview: Optional[str] = None
        parent = (
            parents_map.get(msg.reply_to_message_id)
            if msg.reply_to_message_id is not None
            else None
        )
        if parent is not None:
            reply_preview = (
                DELETED_PLACEHOLDER
                if parent.is_deleted
                else _reply_preview(parent.content)
            )
        out.append(
            ChatMessageResponse(
                id=msg.id,
                job_id=msg.job_id,
                content=DELETED_PLACEHOLDER if msg.is_deleted else msg.content,
                author=_user_to_mini(author),
                reply_to_message_id=msg.reply_to_message_id,
                reply_to_preview=reply_preview,
                is_edited=msg.is_edited,
                edited_at=msg.edited_at,
                is_deleted=msg.is_deleted,
                pinned=msg.pinned,
                pinned_at=msg.pinned_at,
                pinned_by=msg.pinned_by,
                mentions=mentions_map.get(msg.id, []),
                reactions=[
                    ReactionAggregate(**r) for r in reactions_map.get(msg.id, [])
                ],
                created_at=msg.created_at,
                updated_at=msg.updated_at,
            )
        )
    return out


async def _serialize(db: AsyncSession, msg: JobChatMessage) -> ChatMessageResponse:
    """Jedna wiadomość (odpowiedź na zapis, zdarzenie WS)."""
    return (await _serialize_many(db, [msg]))[0]


def _message_link(job_id: int, msg_id: int) -> str:
    return f"/jobs/{job_id}?tab=chat&msg={msg_id}"


async def _broadcast(
    db: AsyncSession, job_id: int, event: dict, exclude_user_id: Optional[int] = None
) -> None:
    """Wyślij WS event do każdego członka projektu (z opcjonalnym wykluczeniem)."""
    member_ids = await list_job_member_ids(db, job_id)
    for uid in member_ids:
        if exclude_user_id is not None and uid == exclude_user_id:
            continue
        try:
            await notify_user(uid, event)
        except Exception:
            # WS broadcast nie powinien blokować ścieżki HTTP — best-effort.
            continue


# ── List messages ────────────────────────────────────────────────────────────


@router.get("/{job_id}/chat/messages", response_model=ChatMessageList)
async def list_messages(
    job_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    before_id: Optional[int] = Query(None, ge=1),
    search: Optional[str] = Query(None, min_length=1, max_length=200),
) -> ChatMessageList:
    """Lista wiadomości w czacie projektu, paginacja w stronę 'starsze'.

    - `before_id`: zwraca wiadomości starsze niż ten id (do nieskończonego
      scrollback w UI).
    - `search`: PG FTS po `search_vector` (`plainto_tsquery('simple', q)`).
    - Zwracamy DESC po `created_at, id` — frontend renderuje od dołu.
    """
    await _require_read_access(db, current_user, job_id)

    q = select(JobChatMessage).where(JobChatMessage.job_id == job_id)
    if before_id is not None:
        q = q.where(JobChatMessage.id < before_id)
    if search:
        # Runda 10 (R10-N6-9): `search_vector` indeksuje treść także po
        # miękkim usunięciu — trafienie zdradzało, co było w usuniętej.
        q = q.where(JobChatMessage.is_deleted.is_(False))
        # plainto_tsquery jest 'safe' — automatycznie escape'uje query.
        q = q.where(
            JobChatMessage.search_vector.op("@@")(
                func.plainto_tsquery("simple", search)
            )
        )
    q = q.order_by(JobChatMessage.created_at.desc(), JobChatMessage.id.desc())
    q = q.limit(limit + 1)  # +1 → wykrywanie has_more

    rows = (await db.execute(q)).scalars().all()
    has_more = len(rows) > limit
    page = list(rows[:limit])

    items = await _serialize_many(db, page)
    next_before_id = page[-1].id if (has_more and page) else None

    return ChatMessageList(
        items=items, has_more=has_more, next_before_id=next_before_id
    )


# ── Create message ───────────────────────────────────────────────────────────


@router.post(
    "/{job_id}/chat/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def create_message(
    request: Request,
    job_id: int,
    data: ChatMessageCreate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ChatMessageResponse:
    """Tworzy wiadomość, parsuje @mentions, persystuje notyfikacje, broadcast WS."""
    await _require_member(db, current_user, job_id)

    # Walidacja reply_to (musi być w tym samym jobie i nie usunięta logicznie)
    if data.reply_to_message_id:
        parent = await db.get(JobChatMessage, data.reply_to_message_id)
        if parent is None or parent.job_id != job_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reply target nie istnieje w tym projekcie.",
            )

    msg = JobChatMessage(
        job_id=job_id,
        author_id=current_user.id,
        content=data.content,
        reply_to_message_id=data.reply_to_message_id,
    )
    db.add(msg)
    await db.flush()

    # @mentions — tylko członkowie projektu
    mentioned_ids = await parse_mentions(db, data.content, job_id)
    # Autor nie wzbudza notyfikacji o swojej @ siebie
    mentioned_ids = [uid for uid in mentioned_ids if uid != current_user.id]
    for uid in mentioned_ids:
        db.add(JobChatMention(message_id=msg.id, user_id=uid))

    # User activity (leaderboard)
    db.add(
        UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.chat_message_added,
            entity_type="job",
            entity_id=job_id,
            details={"message_id": msg.id, "mentioned_count": len(mentioned_ids)},
        )
    )

    # Notyfikacje persistent — każdy członek projektu (poza autorem) dostaje
    # standardowy `job_chat_message`; mention'y dostają DODATKOWO `job_chat_mention`.
    member_ids = await list_job_member_ids(db, job_id)
    target_ids = [uid for uid in member_ids if uid != current_user.id]
    link = _message_link(job_id, msg.id)
    snippet = _reply_preview(data.content, limit=140)

    for uid in target_ids:
        db.add(
            Notification(
                user_id=uid,
                title=f"{current_user.name}: nowa wiadomość",
                message=snippet,
                link=link,
                notification_type=NotificationType.job_chat_message,
                related_entity_type="job_chat_message",
                related_entity_id=None,  # chat notifications nie używają dedup
                # ix_notif_dedup_daily unique on (user, type, entity_id, day)
                # — chat events są per-message, nie per-day; dedup nie ma sensu
            )
        )

    for uid in mentioned_ids:
        db.add(
            Notification(
                user_id=uid,
                title=f"{current_user.name} oznaczył(a) Cię w czacie",
                message=snippet,
                link=link,
                notification_type=NotificationType.job_chat_mention,
                related_entity_type="job_chat_message",
                related_entity_id=None,  # chat notifications nie używają dedup
                # ix_notif_dedup_daily unique on (user, type, entity_id, day)
                # — chat events są per-message, nie per-day; dedup nie ma sensu
            )
        )

    await db.commit()
    await db.refresh(msg)

    payload = await _serialize(db, msg)
    await _broadcast(
        db,
        job_id,
        {
            "type": "chat:message:new",
            "data": {"job_id": job_id, "message": payload.model_dump(mode="json")},
        },
    )
    return payload


# ── Edit message ─────────────────────────────────────────────────────────────


@router.patch("/{job_id}/chat/messages/{msg_id}", response_model=ChatMessageResponse)
async def edit_message(
    job_id: int,
    msg_id: int,
    data: ChatMessageUpdate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ChatMessageResponse:
    """Tylko autor może edytować swoją wiadomość. Nie da się edytować usuniętej."""
    await _require_member(db, current_user, job_id)

    msg = await db.get(JobChatMessage, msg_id)
    if msg is None or msg.job_id != job_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if msg.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nie można edytować usuniętej wiadomości.",
        )
    if msg.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Możesz edytować tylko swoje wiadomości.",
        )

    msg.content = data.content
    msg.is_edited = True
    msg.edited_at = datetime.now(timezone.utc)

    old_mentions = set(
        (
            await db.execute(
                select(JobChatMention.user_id).where(
                    JobChatMention.message_id == msg.id
                )
            )
        )
        .scalars()
        .all()
    )
    # Re-parse @mentions: usuń poprzednie i utwórz nowe
    await db.execute(
        JobChatMention.__table__.delete().where(JobChatMention.message_id == msg.id)
    )
    new_mentions = await parse_mentions(db, data.content, job_id)
    new_mentions = [uid for uid in new_mentions if uid != current_user.id]
    for uid in new_mentions:
        db.add(JobChatMention(message_id=msg.id, user_id=uid))

    link = _message_link(job_id, msg.id)
    snippet = _reply_preview(data.content, limit=140)
    # Runda 10 (R10-N6-3): dzwonek i mail zastępczy niosły pierwotną treść.
    await refresh_chat_message_snippets(
        db,
        related_entity_type="job_chat_message",
        link=link,
        message_created_at=msg.created_at,
        snippet=snippet,
    )
    # Runda 10 (R10-N6-10): wzmianka dopisana przy edycji powiadamia — jak
    # w notatkach (`update_note`).
    for uid in sorted(set(new_mentions) - old_mentions):
        db.add(
            Notification(
                user_id=uid,
                title=f"{current_user.name} oznaczył(a) Cię w czacie",
                message=snippet,
                link=link,
                notification_type=NotificationType.job_chat_mention,
                related_entity_type="job_chat_message",
                related_entity_id=None,  # chat notifications nie używają dedup
            )
        )

    await db.commit()
    await db.refresh(msg)

    payload = await _serialize(db, msg)
    await _broadcast(
        db,
        job_id,
        {
            "type": "chat:message:edit",
            "data": {"job_id": job_id, "message": payload.model_dump(mode="json")},
        },
    )
    return payload


# ── Delete message (soft) ────────────────────────────────────────────────────


@router.delete(
    "/{job_id}/chat/messages/{msg_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_message(
    job_id: int,
    msg_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete. Autor lub admin. Już-usunięta = no-op (idempotent)."""
    await _require_member(db, current_user, job_id)

    msg = await db.get(JobChatMessage, msg_id)
    if msg is None or msg.job_id != job_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if msg.is_deleted:
        return  # idempotentne

    is_author = msg.author_id == current_user.id
    is_admin = current_user.has_role(UserRole.admin)
    if not (is_author or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Możesz usuwać tylko swoje wiadomości.",
        )

    msg.is_deleted = True
    msg.deleted_at = datetime.now(timezone.utc)
    # Usuń pin'a jeśli był
    msg.pinned = False
    msg.pinned_at = None
    msg.pinned_by = None
    # Runda 10 (R10-N6-3): usunięta treść nie zostaje w dzwonku i nie wychodzi
    # mailem zastępczym po 15 min.
    await retract_chat_message_notifications(
        db,
        related_entity_type="job_chat_message",
        link=_message_link(job_id, msg.id),
        message_created_at=msg.created_at,
    )
    await db.commit()

    await _broadcast(
        db,
        job_id,
        {
            "type": "chat:message:delete",
            "data": {"job_id": job_id, "message_id": msg_id},
        },
    )


# ── Pin / Unpin ──────────────────────────────────────────────────────────────


@router.post("/{job_id}/chat/messages/{msg_id}/pin", response_model=ChatPinResponse)
async def pin_message(
    job_id: int,
    msg_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> ChatPinResponse:
    """Pin wiadomości — DL + admin. Limit 3 pinned per job (twardy)."""
    # DeliveryLeadPlus już wymusza role; sprawdzamy jeszcze członkostwo.
    await _require_member(db, current_user, job_id)

    msg = await db.get(JobChatMessage, msg_id)
    if msg is None or msg.job_id != job_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if msg.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nie można przypiąć usuniętej wiadomości.",
        )
    if msg.pinned:
        return ChatPinResponse(message_id=msg.id, pinned=True)

    pinned_count = (
        await db.execute(
            select(func.count(JobChatMessage.id))
            .where(JobChatMessage.job_id == job_id)
            .where(JobChatMessage.pinned.is_(True))
            .where(JobChatMessage.is_deleted.is_(False))
        )
    ).scalar() or 0
    if pinned_count >= MAX_PINNED_PER_JOB:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Limit przypiętych wiadomości w projekcie: {MAX_PINNED_PER_JOB}.",
        )

    msg.pinned = True
    msg.pinned_at = datetime.now(timezone.utc)
    msg.pinned_by = current_user.id
    await db.commit()

    await _broadcast(
        db,
        job_id,
        {
            "type": "chat:message:pin",
            "data": {"job_id": job_id, "message_id": msg.id, "pinned": True},
        },
    )
    return ChatPinResponse(message_id=msg.id, pinned=True)


@router.delete("/{job_id}/chat/messages/{msg_id}/pin", response_model=ChatPinResponse)
async def unpin_message(
    job_id: int,
    msg_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> ChatPinResponse:
    """Unpin wiadomości — DL + admin."""
    await _require_member(db, current_user, job_id)

    msg = await db.get(JobChatMessage, msg_id)
    if msg is None or msg.job_id != job_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if not msg.pinned:
        return ChatPinResponse(message_id=msg.id, pinned=False)

    msg.pinned = False
    msg.pinned_at = None
    msg.pinned_by = None
    await db.commit()

    await _broadcast(
        db,
        job_id,
        {
            "type": "chat:message:pin",
            "data": {"job_id": job_id, "message_id": msg.id, "pinned": False},
        },
    )
    return ChatPinResponse(message_id=msg.id, pinned=False)


@router.get("/{job_id}/chat/pinned", response_model=list[ChatMessageResponse])
async def list_pinned(
    job_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> list[ChatMessageResponse]:
    """Lista przypiętych wiadomości (max 3) — w kolejności od najstarszego pin."""
    await _require_read_access(db, current_user, job_id)
    rows = (
        (
            await db.execute(
                select(JobChatMessage)
                .where(JobChatMessage.job_id == job_id)
                .where(JobChatMessage.pinned.is_(True))
                .where(JobChatMessage.is_deleted.is_(False))
                .order_by(JobChatMessage.pinned_at.asc())
                .limit(MAX_PINNED_PER_JOB)
            )
        )
        .scalars()
        .all()
    )
    return await _serialize_many(db, list(rows))


# ── Read state / unread ──────────────────────────────────────────────────────


@router.put("/{job_id}/chat/read", response_model=ChatUnreadCount)
async def mark_read(
    job_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> ChatUnreadCount:
    """Oznacza wszystkie wiadomości w projekcie jako przeczytane przez current_user."""
    await _require_member(db, current_user, job_id)

    last_id = (
        await db.execute(
            select(func.max(JobChatMessage.id)).where(JobChatMessage.job_id == job_id)
        )
    ).scalar()

    state = (
        await db.execute(
            select(JobChatReadState).where(
                and_(
                    JobChatReadState.job_id == job_id,
                    JobChatReadState.user_id == current_user.id,
                )
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if state is None:
        state = JobChatReadState(
            job_id=job_id,
            user_id=current_user.id,
            last_read_message_id=last_id,
            last_read_at=now,
        )
        db.add(state)
    else:
        state.last_read_message_id = last_id
        state.last_read_at = now

    await db.commit()
    return ChatUnreadCount(job_id=job_id, unread_count=0, last_read_message_id=last_id)


@router.get("/{job_id}/chat/unread-count", response_model=ChatUnreadCount)
async def unread_count(
    job_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> ChatUnreadCount:
    """Liczba wiadomości nowszych od `last_read_message_id` (poza własnymi)."""
    await _require_read_access(db, current_user, job_id)

    state = (
        await db.execute(
            select(JobChatReadState).where(
                and_(
                    JobChatReadState.job_id == job_id,
                    JobChatReadState.user_id == current_user.id,
                )
            )
        )
    ).scalar_one_or_none()
    last_id = state.last_read_message_id if state else None

    q = (
        select(func.count(JobChatMessage.id))
        .where(JobChatMessage.job_id == job_id)
        .where(JobChatMessage.is_deleted.is_(False))
        .where(JobChatMessage.author_id != current_user.id)
    )
    if last_id is not None:
        q = q.where(JobChatMessage.id > last_id)

    count = (await db.execute(q)).scalar() or 0
    return ChatUnreadCount(
        job_id=job_id, unread_count=int(count), last_read_message_id=last_id
    )


# ── Members (for @mention autocomplete) ──────────────────────────────────────


@router.get("/{job_id}/chat/members", response_model=list[ChatUserMini])
async def list_members(
    job_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> list[ChatUserMini]:
    """Lista członków projektu (do autocomplete @mention'a w UI)."""
    await _require_read_access(db, current_user, job_id)
    members = await list_job_members(db, job_id)
    return [_user_to_mini(u) for u in members if u is not None]


# ── Reactions (Feature 7) ────────────────────────────────────────────────────


async def _job_reactions_for_msg(
    db: AsyncSession, msg_id: int
) -> list[ReactionAggregate]:
    aggs = await aggregate_job_reactions(db, [msg_id])
    return [ReactionAggregate(**r) for r in aggs.get(msg_id, [])]


@router.post(
    "/{job_id}/chat/messages/{msg_id}/reactions",
    response_model=ReactionToggleResponse,
)
async def add_reaction(
    job_id: int,
    msg_id: int,
    payload: dict,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ReactionToggleResponse:
    """Dodaje reakcję emoji na wiadomość (idempotentne — duplikat = no-op)."""
    await _require_member(db, current_user, job_id)
    msg = await db.get(JobChatMessage, msg_id)
    if msg is None or msg.job_id != job_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Nie można reagować na usuniętą.")

    emoji = (payload or {}).get("emoji")
    emoji = emoji.strip() if isinstance(emoji, str) else ""
    if not emoji or len(emoji) > 16:
        raise HTTPException(
            status_code=400, detail="Emoji jest wymagane (max 16 znaków)."
        )

    existing = (
        await db.execute(
            select(JobChatMessageReaction).where(
                and_(
                    JobChatMessageReaction.message_id == msg_id,
                    JobChatMessageReaction.user_id == current_user.id,
                    JobChatMessageReaction.emoji == emoji,
                )
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            JobChatMessageReaction(
                message_id=msg_id, user_id=current_user.id, emoji=emoji
            )
        )
        await db.commit()

    reactions = await _job_reactions_for_msg(db, msg_id)
    await _broadcast(
        db,
        job_id,
        {
            "type": "chat:message:reaction",
            "data": {
                "job_id": job_id,
                "message_id": msg_id,
                "reactions": [r.model_dump(mode="json") for r in reactions],
            },
        },
    )
    return ReactionToggleResponse(message_id=msg_id, reactions=reactions)


@router.delete(
    "/{job_id}/chat/messages/{msg_id}/reactions/{emoji}",
    response_model=ReactionToggleResponse,
)
async def remove_reaction(
    job_id: int,
    msg_id: int,
    emoji: str,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ReactionToggleResponse:
    await _require_member(db, current_user, job_id)
    msg = await db.get(JobChatMessage, msg_id)
    if msg is None or msg.job_id != job_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")

    await db.execute(
        JobChatMessageReaction.__table__.delete().where(
            and_(
                JobChatMessageReaction.message_id == msg_id,
                JobChatMessageReaction.user_id == current_user.id,
                JobChatMessageReaction.emoji == emoji,
            )
        )
    )
    await db.commit()

    reactions = await _job_reactions_for_msg(db, msg_id)
    await _broadcast(
        db,
        job_id,
        {
            "type": "chat:message:reaction",
            "data": {
                "job_id": job_id,
                "message_id": msg_id,
                "reactions": [r.model_dump(mode="json") for r in reactions],
            },
        },
    )
    return ReactionToggleResponse(message_id=msg_id, reactions=reactions)


# ── Read receipts (Feature 9) ────────────────────────────────────────────────


@router.get(
    "/{job_id}/chat/messages/{msg_id}/read-by",
    response_model=list[ReadByUser],
)
async def message_read_by(
    job_id: int,
    msg_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> list[ReadByUser]:
    """Lista użytkowników którzy przeczytali tę (lub późniejszą) wiadomość.

    Derived z `job_chat_read_state.last_read_message_id >= msg_id`.
    """
    await _require_read_access(db, current_user, job_id)
    msg = await db.get(JobChatMessage, msg_id)
    if msg is None or msg.job_id != job_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")

    eligible_member_ids = await list_job_member_ids(db, job_id)
    rows = await db.execute(
        select(
            JobChatReadState.user_id,
            JobChatReadState.last_read_at,
            User.name,
        )
        .join(User, User.id == JobChatReadState.user_id)
        .where(JobChatReadState.job_id == job_id)
        .where(JobChatReadState.last_read_message_id >= msg_id)
        .where(JobChatReadState.user_id != current_user.id)
        .where(JobChatReadState.user_id.in_(eligible_member_ids))
        .order_by(JobChatReadState.last_read_at.asc())
    )
    return [
        ReadByUser(user_id=uid, name=name, read_at=ts) for uid, ts, name in rows.all()
    ]
