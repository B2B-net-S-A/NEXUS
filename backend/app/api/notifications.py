"""
Notifications API
User notification system with unread badge support.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.notification import Notification, NotificationType
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


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    """List notifications for current user — unread first."""
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.is_read.asc(), Notification.created_at.desc())
        .limit(limit)
    )
    notifications = result.scalars().all()

    unread_result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read == False)
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
        .where(Notification.user_id == current_user.id, Notification.is_read == False)
    )
    count = result.scalar() or 0
    return UnreadCountResponse(count=count)


@router.put("/notifications/{notification_id}/read", response_model=NotificationResponse)
@router.patch("/notifications/{notification_id}/read", response_model=NotificationResponse)
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


@router.put("/notifications/read-all")
@router.patch("/notifications/read-all")
async def mark_all_read(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications as read for current user (supports both PUT and PATCH)."""
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read == False)
        .values(is_read=True)
    )
    await db.commit()
    return {"success": True, "message": "Wszystkie powiadomienia oznaczone jako przeczytane"}


# ── Helper — create notifications from other endpoints ────────────────────────

async def create_notification(
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    notification_type: NotificationType,
    link: Optional[str] = None,
) -> Notification:
    """Helper to create a notification. Call from other API endpoints."""
    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        link=link,
        notification_type=notification_type,
        is_read=False,
    )
    db.add(notif)
    # Note: caller must commit
    return notif
