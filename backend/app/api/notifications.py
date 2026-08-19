"""
Notifications API
User notification system with unread badge support.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.api.deps import CurrentUser

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

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    unread_count: int


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

    # Finance widzi feed jak pozostałe role operacyjne (decyzja produktowa
    # 19.08 — pełny dostęp; dawna lista „finance-safe" zdjęta).
    if current_user.has_role(UserRole.admin):
        return true()
    return Notification.notification_type != NotificationType.pending_verification


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
):
    """List notifications for current user — unread first."""
    result = await db.execute(
        select(Notification)
        .where(
            Notification.user_id == current_user.id,
            _notification_visibility(current_user),
        )
        .order_by(Notification.is_read.asc(), Notification.created_at.desc())
        .limit(limit)
    )
    notifications = result.scalars().all()

    unread_result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
            _notification_visibility(current_user),
        )
    )
    unread_count = unread_result.scalar() or 0

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
        )
        for n in notifications
    ]

    return NotificationListResponse(items=items, unread_count=unread_count)


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
            Notification.user_id == current_user.id,
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
            Notification.user_id == current_user.id,
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
    )


@router.put("/notifications/read-all", response_model=MarkAllReadResponse)
@router.patch("/notifications/read-all", response_model=MarkAllReadResponse)
async def mark_all_read(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications as read for current user (supports both PUT and PATCH)."""
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
        from sqlalchemy import and_

        existing = await db.scalar(
            select(Notification)
            .where(
                and_(
                    Notification.user_id == user_id,
                    Notification.notification_type == notification_type,
                    Notification.related_entity_id == related_entity_id,
                    Notification.related_entity_type == related_entity_type,
                    func.date_trunc("day", Notification.created_at)
                    == func.date_trunc("day", func.now()),
                )
            )
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            existing.title = title
            existing.message = message
            existing.link = link
            existing.is_read = False
            existing.created_at = func.now()
            return existing

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
    db.add(notif)
    return notif
