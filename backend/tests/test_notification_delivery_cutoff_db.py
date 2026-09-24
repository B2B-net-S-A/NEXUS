"""Hosted PostgreSQL acceptance: no replay of old or disabled-period email."""

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import notification_delivery as delivery
from app.tasks.chat_email_fallback import pending_candidate_query


async def test_activation_and_reactivation_exclude_backlog_without_erasing_history(
    monkeypatch,
):
    setting_key = f"test_notification_delivery_{uuid.uuid4().hex}"
    monkeypatch.setattr(delivery, "SETTING_KEY", setting_key)
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"policy-{uuid.uuid4().hex}@example.invalid",
            password_hash="test-only",
            name="Policy test",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            last_seen_at=None,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
        old = Notification(
            user_id=user.id,
            notification_type=NotificationType.job_chat_message,
            title="Historical test",
            message="Keep in-app history",
            created_at=datetime.now(timezone.utc) - timedelta(days=113),
            is_read=False,
            email_next_attempt_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(old)
        await db.commit()
        await db.refresh(old)
        old_id = old.id
        try:
            assert not (await delivery.load_policy(db)).effective_enabled
            await delivery.save_policy(
                db, enabled=True, toggles={"chat_unread": True}, admin_id=user_id
            )
            first = await delivery.load_policy(db)
            activation = first.cutoff_for("chat_unread")
            assert activation is not None
            fresh = Notification(
                user_id=user_id,
                notification_type=NotificationType.job_chat_message,
                title="Fresh test",
                message="New chat notification",
                created_at=activation + timedelta(seconds=1),
                is_read=False,
            )
            db.add(fresh)
            await db.commit()
            await db.refresh(fresh)
            visible = (
                await db.execute(
                    pending_candidate_query(
                        activation + timedelta(minutes=20), first
                    ).where(Notification.user_id == user_id)
                )
            ).all()
            assert [notification.id for notification, _ in visible] == [fresh.id]

            await delivery.save_policy(db, enabled=False, toggles={}, admin_id=user_id)
            # Zdarzenie z okresu wyłączenia — przed ponownym włączeniem. Sekunda
            # wstecz, bo „teraz” zdarzenia i „teraz” reaktywacji mogą być równe
            # (zamrożony zegar, zbyt gruba rozdzielczość), a wtedy nie ma „przed”.
            disabled_event_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            while_off = Notification(
                user_id=user_id,
                notification_type=NotificationType.job_chat_message,
                title="Disabled period",
                message="No replay after reactivation",
                created_at=disabled_event_at,
                is_read=False,
            )
            db.add(while_off)
            await db.commit()
            await delivery.save_policy(db, enabled=True, toggles={}, admin_id=user_id)
            second = await delivery.load_policy(db)
            assert second.cutoff_for("chat_unread") > disabled_event_at
            assert not second.allows("chat_unread", disabled_event_at)
            preserved = await db.scalar(
                select(Notification).where(Notification.id == old_id)
            )
            assert preserved.message == "Keep in-app history"
            assert preserved.email_sent_at is None
            assert preserved.is_read is False
            assert preserved.email_next_attempt_at is not None
        finally:
            await db.rollback()
            await db.execute(
                delete(Notification).where(Notification.user_id == user_id)
            )
            await db.execute(delete(AppSetting).where(AppSetting.key == setting_key))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
