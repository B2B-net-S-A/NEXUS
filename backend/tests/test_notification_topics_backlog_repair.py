"""Jednorazowe sprzątanie zaległości przy przejściu na ikony paska (16.10.2026).

Decyzja D5: nieprzeczytane powiadomienia starsze niż 7 dni, każdego typu,
stają się przeczytane. Świeże i już przeczytane zostają bez zmian, nic nie
jest kasowane, drugi start kończy się od razu, a paragon niesie same liczby.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.notification_backlog_repair import (
    TOPICS_REPAIR_MARKER,
    run_topics_backlog_repair,
)

_T = NotificationType


@pytest.mark.asyncio
async def test_unread_older_than_a_week_is_marked_read_once():
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        user = User(
            email=f"backlog-{suffix}@example.com",
            password_hash=hash_password(f"T3st_{suffix}!"),
            name=f"Zaległości {suffix}",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.flush()

        def row(ntype: NotificationType, days: int, *, is_read: bool = False):
            # Bez encji: dzienny indeks dedupu obejmuje tylko wiersze z encją.
            return Notification(
                user_id=user.id,
                title="Test",
                message="Treść testowa",
                link="/jobs/1",
                notification_type=ntype,
                is_read=is_read,
                created_at=now - timedelta(days=days),
            )

        rows = {
            "old_move": row(_T.stage_changed, 8),
            "old_chat": row(_T.job_chat_message, 30),
            "fresh": row(_T.stage_changed, 6),
            "old_read": row(_T.cv_ready, 9, is_read=True),
        }
        db.add_all(rows.values())
        await db.execute(
            delete(AppSetting).where(AppSetting.key == TOPICS_REPAIR_MARKER)
        )
        await db.commit()
        user_id = user.id
        ids = {key: r.id for key, r in rows.items()}

    async with AsyncSessionLocal() as db:
        summary = await run_topics_backlog_repair(db, now=now)
        await db.commit()
    assert summary is not None
    assert summary["marked_read"]["stage_changed"] >= 1
    assert summary["marked_read"]["job_chat_message"] >= 1

    async with AsyncSessionLocal() as db:
        state = dict(
            (
                await db.execute(
                    select(Notification.id, Notification.is_read).where(
                        Notification.user_id == user_id
                    )
                )
            ).all()
        )
        assert state == {
            ids["old_move"]: True,
            ids["old_chat"]: True,
            ids["fresh"]: False,
            ids["old_read"]: True,
        }
        assert await run_topics_backlog_repair(db, now=now) is None
        receipt = await db.get(AppSetting, TOPICS_REPAIR_MARKER)
    assert set(receipt.value) == {"done_at", "cutoff", "marked_read", "total"}


def test_startup_phase_runs_the_repair_and_commits():
    from pathlib import Path

    entrypoint = (Path(__file__).parents[1] / "entrypoint.sh").read_text()
    start = entrypoint.index('startup_phase "repair-notification-topics-backlog"')
    phase = entrypoint[start : entrypoint.index("\nPY\n", start)]
    assert "run_topics_backlog_repair" in phase
    assert "await db.commit()" in phase
    # Awaria fazy nie zatrzymuje startu aplikacji.
    assert '|| echo "notification topics backlog repair skipped; continuing"' in phase
