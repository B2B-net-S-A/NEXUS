"""Powiadomienia modułów „Ludzi” — jeden odbiorca nie blokuje reszty.

Wzór, który dotąd miał kilkanaście kopii: odbiorcy bez powtórzeń (kolejność
zostaje), każdy w swoim punkcie zapisu, a awaria ``emit`` u jednej osoby
trafia do logu (same identyfikatory) i nie cofa decyzji ani pozostałych
powiadomień.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_day_start_utc
from app.models.notification import Notification, NotificationType

logger = logging.getLogger(__name__)


async def notify_each(
    db: AsyncSession,
    user_ids: Iterable[Optional[int]],
    *,
    title: str,
    message: str,
    ntype: NotificationType,
    link: Optional[str],
    related_entity_type: Optional[str] = None,
    related_entity_id: Optional[int] = None,
    exclude: Iterable[Optional[int]] = (),
    log_tag: str = "hr",
    fresh: bool = False,
) -> int:
    """Liczba utworzonych powiadomień (deduplikacja ``emit`` też się liczy jako 0).

    ``fresh=True`` — nowa zmiana stanu tej samej sprawy tego samego dnia
    (np. zgoda po poprawce): dzisiejszy wiersz osoby z tym typem i id encji
    zostaje w dzwonku, ale traci ``related_entity_id``, więc dzienny dedup
    (``ix_notif_dedup_daily``) nie połyka nowego dzwonka ani maila.
    """

    # Import w funkcji: ``notification_triggers`` ciągnie pół aplikacji,
    # a serwisy HR importuje się też z tras i pętli.
    from app.services.notification_triggers import emit  # noqa: PLC0415

    skip = {user_id for user_id in exclude if user_id is not None}
    sent = 0
    for user_id in dict.fromkeys(user_ids):
        if user_id is None or user_id in skip:
            continue
        try:
            async with db.begin_nested():
                if fresh and related_entity_id is not None:
                    await db.execute(
                        update(Notification)
                        .where(
                            Notification.user_id == user_id,
                            Notification.notification_type == ntype,
                            Notification.related_entity_id == related_entity_id,
                            Notification.created_at
                            >= local_day_start_utc(business_today()),
                        )
                        .values(related_entity_id=None)
                    )
                created = await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    ntype=ntype,
                    related_entity_type=related_entity_type,
                    related_entity_id=related_entity_id,
                    link=link,
                )
            sent += int(created is not None)
        except Exception:  # noqa: BLE001 — jeden odbiorca nie blokuje reszty
            logger.exception(
                "[%s] powiadomienie nie wyszło type=%s user=%s",
                log_tag,
                ntype.value,
                user_id,
            )
    return sent
