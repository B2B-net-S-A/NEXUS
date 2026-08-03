"""Atomic-claim guard for the chat email fallback loop.

`tasks/chat_email_fallback.py` used to SELECT notifications with
`email_sent_at IS NULL`, send the email, then stamp `email_sent_at` — with no
row lock between the SELECT and the send. Two overlapping passes (multi-worker
or restart overlap) both saw NULL and sent the SAME email twice. The loop now
claims each row atomically BEFORE sending, so exactly one pass sends.

Real Postgres (in-process, migrations applied by CI before pytest).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.tasks.chat_email_fallback import _claim_notification, _process_one_pass


async def _seed_offline_chat_notification() -> tuple[int, int]:
    """Create an offline user + an old, unread, unsent chat notification.

    Returns (user_id, notification_id). The notification qualifies for the
    fallback: chat type, older than the threshold, unread, email_sent_at NULL,
    and a user who was never online (last_seen_at NULL).
    """
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    async with AsyncSessionLocal() as db:
        u = User(
            email=f"chatfb-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("T3st_pass_xxxxxxx!"),
            name="Chat Fallback",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
            profile_completed=True,
            last_seen_at=None,  # never online → qualifies
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)

        n = Notification(
            user_id=u.id,
            title="Nowa wiadomość",
            message="Ktoś napisał na czacie rekrutacji",
            notification_type=NotificationType.job_chat_message,
            is_read=False,
            created_at=old,  # explicit value overrides server_default now()
        )
        db.add(n)
        await db.commit()
        await db.refresh(n)
        return u.id, n.id


async def _cleanup(user_id: int, notif_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.id == notif_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


async def test_claim_is_atomic_two_sequential_attempts() -> None:
    """First claim wins; the second finds no NULL row left to claim."""
    user_id, notif_id = await _seed_offline_chat_notification()
    try:
        async with AsyncSessionLocal() as db:
            first = await _claim_notification(db, notif_id)
            second = await _claim_notification(db, notif_id)
        assert first is True
        assert second is False
    finally:
        await _cleanup(user_id, notif_id)


async def test_process_one_pass_sends_exactly_once(monkeypatch) -> None:
    """Two passes over the same row send the email exactly once (no double send)."""
    calls: list[dict] = []

    def fake_send(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(
        "app.tasks.chat_email_fallback.send_chat_fallback_email", fake_send
    )

    user_id, notif_id = await _seed_offline_chat_notification()
    try:
        async with AsyncSessionLocal() as db:
            first = await _process_one_pass(db)
        async with AsyncSessionLocal() as db:
            second = await _process_one_pass(db)

        assert first == 1
        assert second == 0
        assert len(calls) == 1  # sent once, not twice

        async with AsyncSessionLocal() as db:
            row = await db.get(Notification, notif_id)
            assert row is not None
            assert row.email_sent_at is not None  # claimed + kept on success
    finally:
        await _cleanup(user_id, notif_id)


async def test_release_on_smtp_off_keeps_row_retryable(monkeypatch) -> None:
    """When the send does not go out (SMTP off → False) the claim is released,
    so a later pass retries: email_sent_at stays NULL and nothing is 'sent'."""

    def fake_send(**kwargs):
        return False  # SMTP disabled / send failed

    monkeypatch.setattr(
        "app.tasks.chat_email_fallback.send_chat_fallback_email", fake_send
    )

    user_id, notif_id = await _seed_offline_chat_notification()
    try:
        async with AsyncSessionLocal() as db:
            fired = await _process_one_pass(db)
        assert fired == 0
        async with AsyncSessionLocal() as db:
            row = await db.get(Notification, notif_id)
            assert row is not None
            assert row.email_sent_at is None  # released → retryable next pass
    finally:
        await _cleanup(user_id, notif_id)
