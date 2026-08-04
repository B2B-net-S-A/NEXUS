"""Candidate Chat API — internal team chat per candidate.

Mirror of job_chat.py but scoped to a single candidate. Members determined
by app.services.candidate_membership.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidatePIIAccess, CandidateWriteAccess
from app.api.deps import DeliveryLeadPlus
from app.api.ws import notify_user
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate_chat import (
    CandidateChatMention,
    CandidateChatMessage,
    CandidateChatReadState,
)
from app.models.chat_reaction import CandidateChatMessageReaction
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.models.user_activity import UserActionType, UserActivity
from app.schemas.candidate_chat import (
    CandidateChatMessageCreate,
    CandidateChatMessageList,
    CandidateChatMessageResponse,
    CandidateChatMessageUpdate,
    CandidateChatPinResponse,
    CandidateChatUnreadCount,
    ReactionAggregate,
    ReactionToggleResponse,
    ReadByUser,
)
from app.schemas.job_chat import ChatUserMini
from app.services.candidate_membership import (
    is_member_of_candidate_chat,
    list_candidate_chat_member_ids,
    list_candidate_chat_members,
)
from app.services.chat_reactions import aggregate_candidate_reactions
from app.services.mention_parser import parse_mentions_candidate


router = APIRouter()

DELETED_PLACEHOLDER = "[wiadomość usunięta]"
MAX_PINNED_PER_CANDIDATE = 3
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _require_member(db: AsyncSession, user: User, candidate_id: int) -> None:
    if not await is_member_of_candidate_chat(db, user, candidate_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak dostępu do czatu tego kandydata.",
        )


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
    db: AsyncSession, msgs: list[CandidateChatMessage]
) -> list[CandidateChatMessageResponse]:
    if not msgs:
        return []

    # Bulk-fetch authors
    author_ids = {m.author_id for m in msgs if m.author_id is not None}
    authors_map: dict[int, User] = {}
    if author_ids:
        rows = await db.execute(select(User).where(User.id.in_(author_ids)))
        for u in rows.scalars().all():
            authors_map[u.id] = u

    # Bulk-fetch reply parents (for preview)
    parent_ids = {
        m.reply_to_message_id for m in msgs if m.reply_to_message_id is not None
    }
    parents_map: dict[int, CandidateChatMessage] = {}
    if parent_ids:
        rows = await db.execute(
            select(CandidateChatMessage).where(CandidateChatMessage.id.in_(parent_ids))
        )
        for p in rows.scalars().all():
            parents_map[p.id] = p

    # Bulk mentions
    msg_ids = [m.id for m in msgs]
    mentions_map: dict[int, list[int]] = {}
    if msg_ids:
        rows = await db.execute(
            select(CandidateChatMention.message_id, CandidateChatMention.user_id).where(
                CandidateChatMention.message_id.in_(msg_ids)
            )
        )
        for mid, uid in rows.all():
            mentions_map.setdefault(mid, []).append(uid)

    reactions_map = await aggregate_candidate_reactions(db, msg_ids)

    out: list[CandidateChatMessageResponse] = []
    for m in msgs:
        author = authors_map.get(m.author_id) if m.author_id is not None else None
        parent = (
            parents_map.get(m.reply_to_message_id)
            if m.reply_to_message_id is not None
            else None
        )
        reply_preview = None
        if parent is not None:
            reply_preview = (
                DELETED_PLACEHOLDER
                if parent.is_deleted
                else _reply_preview(parent.content)
            )
        out.append(
            CandidateChatMessageResponse(
                id=m.id,
                candidate_id=m.candidate_id,
                content=DELETED_PLACEHOLDER if m.is_deleted else m.content,
                author=_user_to_mini(author),
                reply_to_message_id=m.reply_to_message_id,
                reply_to_preview=reply_preview,
                is_edited=m.is_edited,
                edited_at=m.edited_at,
                is_deleted=m.is_deleted,
                pinned=m.pinned,
                pinned_at=m.pinned_at,
                pinned_by=m.pinned_by,
                mentions=mentions_map.get(m.id, []),
                reactions=[ReactionAggregate(**r) for r in reactions_map.get(m.id, [])],
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
        )
    return out


async def _broadcast(
    db: AsyncSession,
    candidate_id: int,
    event: dict,
    exclude_user_id: Optional[int] = None,
) -> None:
    member_ids = await list_candidate_chat_member_ids(db, candidate_id)
    for uid in member_ids:
        if exclude_user_id is not None and uid == exclude_user_id:
            continue
        try:
            await notify_user(uid, event)
        except Exception:
            continue


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/{candidate_id}/chat/messages", response_model=CandidateChatMessageList)
async def list_messages(
    candidate_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    before_id: Optional[int] = Query(None, ge=1),
    search: Optional[str] = Query(None, min_length=1, max_length=200),
) -> CandidateChatMessageList:
    await _require_member(db, current_user, candidate_id)

    q = select(CandidateChatMessage).where(
        CandidateChatMessage.candidate_id == candidate_id
    )
    if before_id is not None:
        q = q.where(CandidateChatMessage.id < before_id)
    if search:
        q = q.where(
            CandidateChatMessage.search_vector.op("@@")(
                func.plainto_tsquery("simple", search)
            )
        )
    q = q.order_by(
        CandidateChatMessage.created_at.desc(), CandidateChatMessage.id.desc()
    )
    q = q.limit(limit + 1)

    rows = (await db.execute(q)).scalars().all()
    has_more = len(rows) > limit
    page = list(rows[:limit])
    items = await _serialize_many(db, page)
    next_before_id = page[-1].id if (has_more and page) else None
    return CandidateChatMessageList(
        items=items, has_more=has_more, next_before_id=next_before_id
    )


@router.post(
    "/{candidate_id}/chat/messages",
    response_model=CandidateChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def create_message(
    request: Request,
    candidate_id: int,
    data: CandidateChatMessageCreate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateChatMessageResponse:
    await _require_member(db, current_user, candidate_id)

    if data.reply_to_message_id:
        parent = await db.get(CandidateChatMessage, data.reply_to_message_id)
        if parent is None or parent.candidate_id != candidate_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reply target nie istnieje przy tym kandydacie.",
            )

    msg = CandidateChatMessage(
        candidate_id=candidate_id,
        author_id=current_user.id,
        content=data.content,
        reply_to_message_id=data.reply_to_message_id,
    )
    db.add(msg)
    await db.flush()

    mentioned_ids = await parse_mentions_candidate(db, data.content, candidate_id)
    mentioned_ids = [uid for uid in mentioned_ids if uid != current_user.id]
    for uid in mentioned_ids:
        db.add(CandidateChatMention(message_id=msg.id, user_id=uid))

    db.add(
        UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.chat_message_added,
            entity_type="candidate",
            entity_id=candidate_id,
            details={"message_id": msg.id, "mentioned_count": len(mentioned_ids)},
        )
    )

    member_ids = await list_candidate_chat_member_ids(db, candidate_id)
    target_ids = [uid for uid in member_ids if uid != current_user.id]
    link = f"/candidates/{candidate_id}?tab=chat&msg={msg.id}"
    snippet = _reply_preview(data.content, limit=140)

    for uid in target_ids:
        db.add(
            Notification(
                user_id=uid,
                title=f"{current_user.name}: nowa wiadomość o kandydacie",
                message=snippet,
                link=link,
                notification_type=NotificationType.job_chat_message,
                related_entity_type="candidate_chat_message",
                related_entity_id=None,  # chat notifications nie używają dedup
            )
        )

    for uid in mentioned_ids:
        db.add(
            Notification(
                user_id=uid,
                title=f"{current_user.name} oznaczył(a) Cię w czacie kandydata",
                message=snippet,
                link=link,
                notification_type=NotificationType.job_chat_mention,
                related_entity_type="candidate_chat_message",
                related_entity_id=None,  # chat notifications nie używają dedup
            )
        )

    await db.commit()
    await db.refresh(msg)

    payload_list = await _serialize_many(db, [msg])
    payload = payload_list[0]
    await _broadcast(
        db,
        candidate_id,
        {
            "type": "candidate-chat:message:new",
            "data": {
                "candidate_id": candidate_id,
                "message": payload.model_dump(mode="json"),
            },
        },
    )
    return payload


@router.patch(
    "/{candidate_id}/chat/messages/{msg_id}",
    response_model=CandidateChatMessageResponse,
)
async def edit_message(
    candidate_id: int,
    msg_id: int,
    data: CandidateChatMessageUpdate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateChatMessageResponse:
    await _require_member(db, current_user, candidate_id)
    msg = await db.get(CandidateChatMessage, msg_id)
    if msg is None or msg.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Nie można edytować usuniętej.")
    if msg.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Możesz edytować tylko swoje.")

    msg.content = data.content
    msg.is_edited = True
    msg.edited_at = datetime.now(timezone.utc)

    await db.execute(
        CandidateChatMention.__table__.delete().where(
            CandidateChatMention.message_id == msg.id
        )
    )
    new_mentions = await parse_mentions_candidate(db, data.content, candidate_id)
    new_mentions = [uid for uid in new_mentions if uid != current_user.id]
    for uid in new_mentions:
        db.add(CandidateChatMention(message_id=msg.id, user_id=uid))

    await db.commit()
    await db.refresh(msg)
    payload = (await _serialize_many(db, [msg]))[0]
    await _broadcast(
        db,
        candidate_id,
        {
            "type": "candidate-chat:message:edit",
            "data": {
                "candidate_id": candidate_id,
                "message": payload.model_dump(mode="json"),
            },
        },
    )
    return payload


@router.delete(
    "/{candidate_id}/chat/messages/{msg_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_message(
    candidate_id: int,
    msg_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_member(db, current_user, candidate_id)
    msg = await db.get(CandidateChatMessage, msg_id)
    if msg is None or msg.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if msg.is_deleted:
        return
    is_author = msg.author_id == current_user.id
    is_admin = current_user.has_role(UserRole.admin)
    if not (is_author or is_admin):
        raise HTTPException(status_code=403, detail="Możesz usuwać tylko swoje.")
    msg.is_deleted = True
    msg.deleted_at = datetime.now(timezone.utc)
    msg.pinned = False
    msg.pinned_at = None
    msg.pinned_by = None
    await db.commit()
    await _broadcast(
        db,
        candidate_id,
        {
            "type": "candidate-chat:message:delete",
            "data": {"candidate_id": candidate_id, "message_id": msg_id},
        },
    )


@router.post(
    "/{candidate_id}/chat/messages/{msg_id}/pin",
    response_model=CandidateChatPinResponse,
)
async def pin_message(
    candidate_id: int,
    msg_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> CandidateChatPinResponse:
    await _require_member(db, current_user, candidate_id)
    msg = await db.get(CandidateChatMessage, msg_id)
    if msg is None or msg.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Nie można przypiąć usuniętej.")
    if msg.pinned:
        return CandidateChatPinResponse(message_id=msg.id, pinned=True)

    pinned_count = (
        await db.execute(
            select(func.count(CandidateChatMessage.id))
            .where(CandidateChatMessage.candidate_id == candidate_id)
            .where(CandidateChatMessage.pinned.is_(True))
            .where(CandidateChatMessage.is_deleted.is_(False))
        )
    ).scalar() or 0
    if pinned_count >= MAX_PINNED_PER_CANDIDATE:
        raise HTTPException(
            status_code=400,
            detail=f"Limit przypiętych wiadomości: {MAX_PINNED_PER_CANDIDATE}.",
        )

    msg.pinned = True
    msg.pinned_at = datetime.now(timezone.utc)
    msg.pinned_by = current_user.id
    await db.commit()
    await _broadcast(
        db,
        candidate_id,
        {
            "type": "candidate-chat:message:pin",
            "data": {
                "candidate_id": candidate_id,
                "message_id": msg.id,
                "pinned": True,
            },
        },
    )
    return CandidateChatPinResponse(message_id=msg.id, pinned=True)


@router.delete(
    "/{candidate_id}/chat/messages/{msg_id}/pin",
    response_model=CandidateChatPinResponse,
)
async def unpin_message(
    candidate_id: int,
    msg_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> CandidateChatPinResponse:
    await _require_member(db, current_user, candidate_id)
    msg = await db.get(CandidateChatMessage, msg_id)
    if msg is None or msg.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if not msg.pinned:
        return CandidateChatPinResponse(message_id=msg.id, pinned=False)
    msg.pinned = False
    msg.pinned_at = None
    msg.pinned_by = None
    await db.commit()
    await _broadcast(
        db,
        candidate_id,
        {
            "type": "candidate-chat:message:pin",
            "data": {
                "candidate_id": candidate_id,
                "message_id": msg.id,
                "pinned": False,
            },
        },
    )
    return CandidateChatPinResponse(message_id=msg.id, pinned=False)


@router.get(
    "/{candidate_id}/chat/pinned",
    response_model=list[CandidateChatMessageResponse],
)
async def list_pinned(
    candidate_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> list[CandidateChatMessageResponse]:
    await _require_member(db, current_user, candidate_id)
    rows = (
        (
            await db.execute(
                select(CandidateChatMessage)
                .where(CandidateChatMessage.candidate_id == candidate_id)
                .where(CandidateChatMessage.pinned.is_(True))
                .where(CandidateChatMessage.is_deleted.is_(False))
                .order_by(CandidateChatMessage.pinned_at.asc())
                .limit(MAX_PINNED_PER_CANDIDATE)
            )
        )
        .scalars()
        .all()
    )
    return await _serialize_many(db, list(rows))


@router.put("/{candidate_id}/chat/read", response_model=CandidateChatUnreadCount)
async def mark_read(
    candidate_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateChatUnreadCount:
    await _require_member(db, current_user, candidate_id)
    last_id = (
        await db.execute(
            select(func.max(CandidateChatMessage.id)).where(
                CandidateChatMessage.candidate_id == candidate_id
            )
        )
    ).scalar()
    state = (
        await db.execute(
            select(CandidateChatReadState).where(
                and_(
                    CandidateChatReadState.candidate_id == candidate_id,
                    CandidateChatReadState.user_id == current_user.id,
                )
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if state is None:
        state = CandidateChatReadState(
            candidate_id=candidate_id,
            user_id=current_user.id,
            last_read_message_id=last_id,
            last_read_at=now,
        )
        db.add(state)
    else:
        state.last_read_message_id = last_id
        state.last_read_at = now
    await db.commit()
    return CandidateChatUnreadCount(
        candidate_id=candidate_id, unread_count=0, last_read_message_id=last_id
    )


@router.get(
    "/{candidate_id}/chat/unread-count",
    response_model=CandidateChatUnreadCount,
)
async def unread_count(
    candidate_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateChatUnreadCount:
    await _require_member(db, current_user, candidate_id)
    state = (
        await db.execute(
            select(CandidateChatReadState).where(
                and_(
                    CandidateChatReadState.candidate_id == candidate_id,
                    CandidateChatReadState.user_id == current_user.id,
                )
            )
        )
    ).scalar_one_or_none()
    last_id = state.last_read_message_id if state else None
    q = (
        select(func.count(CandidateChatMessage.id))
        .where(CandidateChatMessage.candidate_id == candidate_id)
        .where(CandidateChatMessage.is_deleted.is_(False))
        .where(CandidateChatMessage.author_id != current_user.id)
    )
    if last_id is not None:
        q = q.where(CandidateChatMessage.id > last_id)
    count = (await db.execute(q)).scalar() or 0
    return CandidateChatUnreadCount(
        candidate_id=candidate_id, unread_count=int(count), last_read_message_id=last_id
    )


@router.get("/{candidate_id}/chat/members", response_model=list[ChatUserMini])
async def list_members(
    candidate_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> list[ChatUserMini]:
    await _require_member(db, current_user, candidate_id)
    members = await list_candidate_chat_members(db, candidate_id)
    return [_user_to_mini(u) for u in members if u is not None]


# ── Reactions (Feature 7) ────────────────────────────────────────────────────


async def _reactions_for_msg(db: AsyncSession, msg_id: int) -> list[ReactionAggregate]:
    aggs = await aggregate_candidate_reactions(db, [msg_id])
    raw = aggs.get(msg_id, [])
    return [ReactionAggregate(**r) for r in raw]


@router.post(
    "/{candidate_id}/chat/messages/{msg_id}/reactions",
    response_model=ReactionToggleResponse,
)
async def add_reaction(
    candidate_id: int,
    msg_id: int,
    payload: dict,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ReactionToggleResponse:
    await _require_member(db, current_user, candidate_id)
    msg = await db.get(CandidateChatMessage, msg_id)
    if msg is None or msg.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Nie można reagować na usuniętą.")

    emoji = (payload or {}).get("emoji", "").strip()
    if not emoji or len(emoji) > 16:
        raise HTTPException(
            status_code=400, detail="Emoji jest wymagane (max 16 znaków)."
        )

    existing = (
        await db.execute(
            select(CandidateChatMessageReaction).where(
                and_(
                    CandidateChatMessageReaction.message_id == msg_id,
                    CandidateChatMessageReaction.user_id == current_user.id,
                    CandidateChatMessageReaction.emoji == emoji,
                )
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            CandidateChatMessageReaction(
                message_id=msg_id, user_id=current_user.id, emoji=emoji
            )
        )
        await db.commit()

    reactions = await _reactions_for_msg(db, msg_id)
    await _broadcast(
        db,
        candidate_id,
        {
            "type": "candidate-chat:message:reaction",
            "data": {
                "candidate_id": candidate_id,
                "message_id": msg_id,
                "reactions": [r.model_dump(mode="json") for r in reactions],
            },
        },
    )
    return ReactionToggleResponse(message_id=msg_id, reactions=reactions)


@router.delete(
    "/{candidate_id}/chat/messages/{msg_id}/reactions/{emoji}",
    response_model=ReactionToggleResponse,
)
async def remove_reaction(
    candidate_id: int,
    msg_id: int,
    emoji: str,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ReactionToggleResponse:
    await _require_member(db, current_user, candidate_id)
    msg = await db.get(CandidateChatMessage, msg_id)
    if msg is None or msg.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")

    await db.execute(
        CandidateChatMessageReaction.__table__.delete().where(
            and_(
                CandidateChatMessageReaction.message_id == msg_id,
                CandidateChatMessageReaction.user_id == current_user.id,
                CandidateChatMessageReaction.emoji == emoji,
            )
        )
    )
    await db.commit()

    reactions = await _reactions_for_msg(db, msg_id)
    await _broadcast(
        db,
        candidate_id,
        {
            "type": "candidate-chat:message:reaction",
            "data": {
                "candidate_id": candidate_id,
                "message_id": msg_id,
                "reactions": [r.model_dump(mode="json") for r in reactions],
            },
        },
    )
    return ReactionToggleResponse(message_id=msg_id, reactions=reactions)


# ── Read receipts (Feature 9) ────────────────────────────────────────────────


@router.get(
    "/{candidate_id}/chat/messages/{msg_id}/read-by",
    response_model=list[ReadByUser],
)
async def message_read_by(
    candidate_id: int,
    msg_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> list[ReadByUser]:
    """Lista użytkowników którzy przeczytali tę (lub późniejszą) wiadomość.

    Derived z `candidate_chat_read_state.last_read_message_id >= msg_id`.
    """
    await _require_member(db, current_user, candidate_id)
    msg = await db.get(CandidateChatMessage, msg_id)
    if msg is None or msg.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="Wiadomość nie znaleziona.")

    eligible_member_ids = await list_candidate_chat_member_ids(db, candidate_id)
    rows = await db.execute(
        select(
            CandidateChatReadState.user_id,
            CandidateChatReadState.last_read_at,
            User.name,
        )
        .join(User, User.id == CandidateChatReadState.user_id)
        .where(CandidateChatReadState.candidate_id == candidate_id)
        .where(CandidateChatReadState.last_read_message_id >= msg_id)
        .where(CandidateChatReadState.user_id != current_user.id)
        .where(CandidateChatReadState.user_id.in_(eligible_member_ids))
        .order_by(CandidateChatReadState.last_read_at.asc())
    )
    return [
        ReadByUser(user_id=uid, name=name, read_at=ts) for uid, ts, name in rows.all()
    ]
