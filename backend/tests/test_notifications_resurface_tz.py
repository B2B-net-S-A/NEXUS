"""`create_notification(dedupe_resurface=True)` liczy dobę tak jak indeks.

Indeks ``ix_notif_dedup_daily`` klucza dobę lokalną Europe/Warsaw, a do
09.2026 wyszukiwanie „dzisiejszego" wiersza porównywało dobę w strefie sesji
(UTC). Wiersz zapisany tuż po północy czasu polskiego należał wtedy dla
zapytania do „wczoraj": INSERT trafiał w indeks i całe żądanie (np. zapis
profilu Championa) kończyło się 500.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.api.notifications import create_notification


async def _seed_user() -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"resurface-tz-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!PassX"),
            name="Resurface TZ",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def test_row_from_early_warsaw_morning_is_resurfaced_not_reinserted():
    user_id = await _seed_user()
    entity_id = 900_000_000 + int(uuid.uuid4().int % 1_000_000)

    async with AsyncSessionLocal() as db:
        # Początek dzisiejszej doby w Warszawie (+1 s) — w UTC to jeszcze
        # „wczoraj" przez większość dnia, czyli dokładnie przypadek z audytu
        # (np. 23:30 UTC = 01:30 w Warszawie następnego dnia).
        warsaw_midnight = await db.scalar(
            text(
                "SELECT (date_trunc('day', now() AT TIME ZONE 'Europe/Warsaw') "
                "+ interval '1 second') AT TIME ZONE 'Europe/Warsaw'"
            )
        )
        db.add(
            Notification(
                user_id=user_id,
                title="Stary tytuł",
                message="stara treść",
                notification_type=NotificationType.champion_profile_updated,
                related_entity_type="job",
                related_entity_id=entity_id,
                is_read=True,
                created_at=warsaw_midnight,
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        notif = await create_notification(
            db,
            user_id=user_id,
            title="Nowy tytuł",
            message="nowa treść",
            notification_type=NotificationType.champion_profile_updated,
            link="/jobs/1?tab=champion",
            related_entity_type="job",
            related_entity_id=entity_id,
            dedupe_resurface=True,
        )
        await db.commit()
        assert notif.id is not None

    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.related_entity_id == entity_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].title == "Nowy tytuł"
    assert rows[0].is_read is False


async def test_concurrent_insert_collision_resurfaces_instead_of_raising(monkeypatch):
    """Wyścig: wyszukiwanie nie widzi wiersza, a INSERT trafia w indeks."""
    user_id = await _seed_user()
    entity_id = 910_000_000 + int(uuid.uuid4().int % 1_000_000)

    async with AsyncSessionLocal() as db:
        db.add(
            Notification(
                user_id=user_id,
                title="Pierwszy",
                message="pierwszy zapis",
                notification_type=NotificationType.champion_profile_updated,
                # Inny `related_entity_type` — nie wchodzi w klucz indeksu.
                related_entity_type="legacy",
                related_entity_id=entity_id,
                is_read=True,
            )
        )
        await db.commit()

    import app.api.notifications as notifications_api

    real_lookup = notifications_api._todays_notification
    calls = {"n": 0}

    async def blind_first_lookup(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # równoległe żądanie jeszcze nie widziało wiersza
        return await real_lookup(*args, **kwargs)

    monkeypatch.setattr(notifications_api, "_todays_notification", blind_first_lookup)
    async with AsyncSessionLocal() as db:
        await create_notification(
            db,
            user_id=user_id,
            title="Drugi",
            message="drugi zapis",
            notification_type=NotificationType.champion_profile_updated,
            related_entity_type="job",
            related_entity_id=entity_id,
            dedupe_resurface=True,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.related_entity_id == entity_id,
            )
        )
        title = await db.scalar(
            select(Notification.title).where(
                Notification.user_id == user_id,
                Notification.related_entity_id == entity_id,
            )
        )
    assert count == 1
    assert title == "Drugi"
