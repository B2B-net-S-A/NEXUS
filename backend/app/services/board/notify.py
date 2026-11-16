"""Dzwonek Rady o nowym wpisie w KRS spółki (``board_krs_entry``)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.board.krs import KrsEntry
from app.services.hr.notify import notify_each

LINK = "/rada?tab=dokumenty"


async def recipient_ids(db: AsyncSession) -> list[int]:
    """Aktywni członkowie Rady i admini (rola główna albo dodatkowa)."""

    users = await db.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.id)
    )
    return [
        user.id
        for user in users
        if user.has_role(UserRole.board) or user.has_role(UserRole.admin)
    ]


def entry_message(entries: list[KrsEntry]) -> tuple[str, str]:
    last = entries[-1]
    day = last.day.strftime("%d.%m.%Y") if last.day else "brak daty"
    if len(entries) == 1:
        title = f"Nowy wpis w KRS spółki (nr {last.number})"
    else:
        title = f"{len(entries)} nowe wpisy w KRS spółki (do nr {last.number})"
    court = "" if last.court.upper() == "SYSTEM" else f", {last.court.title()}"
    message = f"Wpis nr {last.number} z {day}: {last.description.capitalize()}{court}."
    return title, message


async def notify_new_entries(
    db: AsyncSession, snapshot_id: int, entries: list[KrsEntry]
) -> int:
    title, message = entry_message(entries)
    return await notify_each(
        db,
        await recipient_ids(db),
        title=title,
        message=message,
        ntype=NotificationType.board_krs_entry,
        link=LINK,
        related_entity_type="board_krs_snapshot",
        related_entity_id=snapshot_id,
        log_tag="board",
    )
