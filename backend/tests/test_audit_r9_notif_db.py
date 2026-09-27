"""Runda 9 audytu — powiadomienia (NOTIF): testy na prawdziwym Postgresie.

R9-N2-1  wiersze odrzucone w Pythonie nie blokują maili czatu reszcie;
         wyciszony „Czat” w ogóle nie trafia do kolejki.
R9-N2-2  osoba z otwartym gniazdem nie dostaje maila.
R9-N2-5  ``emit`` wypycha zdarzenie WS dopiero po commicie.
R9-N2-6  ponowna @wzmianka tego samego dnia nie wywraca zapisu notatki.
R9-N12-5 drugi wpis tej samej encji tego dnia nie wywraca cyklu alertów.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.tasks import chat_email_fallback as fallback

pytestmark = pytest.mark.usefixtures("routine_notification_email_enabled")


def _entity_id() -> int:
    return 900_000_000 + uuid.uuid4().int % 90_000_000


async def _seed_user(**extra) -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"r9notif-{uuid.uuid4().hex[:10]}@example.com",
            password_hash=hash_password("T3st_pass_xxxxxxx!"),
            name="R9 Notif",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
            profile_completed=True,
            last_seen_at=None,
            **extra,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _seed_chat(user_id: int, created_at: datetime, *, message: str) -> int:
    async with AsyncSessionLocal() as db:
        notif = Notification(
            user_id=user_id,
            title="Nowa wiadomość",
            message=message,
            notification_type=NotificationType.job_chat_message,
            is_read=False,
            created_at=created_at,
        )
        db.add(notif)
        await db.commit()
        return notif.id


async def _cleanup(user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id.in_(user_ids)))
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


def _near_cutoff(minutes: int) -> datetime:
    # Tuż za granicą polityki z fixture'a (rok wstecz): nic starszego z innych
    # testów nie stanie przed tymi wierszami w kolejce.
    return datetime.now(timezone.utc) - timedelta(days=365) + timedelta(minutes=minutes)


async def test_rows_rejected_in_python_do_not_starve_the_rest(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(
        fallback,
        "send_chat_fallback_email",
        lambda **kw: sent.append(kw["notification_message"]) or True,
    )
    monkeypatch.setattr(fallback, "BATCH_SIZE", 1)
    blocked = await _seed_user()
    ok = await _seed_user()
    marker = uuid.uuid4().hex
    await _seed_chat(blocked, _near_cutoff(1), message=f"blocked {marker}")
    await _seed_chat(ok, _near_cutoff(2), message=f"ok {marker}")
    monkeypatch.setattr(
        fallback, "_eligible_chat_email_recipient", lambda user: user.id != blocked
    )
    try:
        async with AsyncSessionLocal() as db:
            await fallback._process_one_pass(db)
        assert f"ok {marker}" in sent
        assert f"blocked {marker}" not in sent
    finally:
        await _cleanup([blocked, ok])


async def test_muted_chat_never_enters_the_queue() -> None:
    muted = await _seed_user(
        muted_notification_categories={"chat": "2026-09-01T00:00:00+00:00"}
    )
    notif_id = await _seed_chat(muted, _near_cutoff(3), message="muted")
    try:
        async with AsyncSessionLocal() as db:
            query = fallback.pending_candidate_query(datetime.now(timezone.utc)).where(
                Notification.id == notif_id
            )
            assert (await db.execute(query)).first() is None
    finally:
        await _cleanup([muted])


async def test_user_with_open_socket_gets_no_chat_email(monkeypatch) -> None:
    from app.api import ws

    sent: list[str] = []
    monkeypatch.setattr(
        fallback,
        "send_chat_fallback_email",
        lambda **kw: sent.append(kw["notification_message"]) or True,
    )
    online = await _seed_user()
    marker = uuid.uuid4().hex
    await _seed_chat(online, _near_cutoff(4), message=f"online {marker}")
    monkeypatch.setitem(ws.manager._connections, online, [object()])
    try:
        async with AsyncSessionLocal() as db:
            await fallback._process_one_pass(db)
        assert f"online {marker}" not in sent
    finally:
        await _cleanup([online])


async def test_emit_pushes_ws_only_after_commit(monkeypatch) -> None:
    from app.api import ws
    from app.services.notification_triggers import emit

    pushed: list[int] = []

    async def fake_notify(user_id, _payload):
        pushed.append(user_id)

    monkeypatch.setattr(ws, "notify_user", fake_notify)
    user_id = await _seed_user()
    try:
        async with AsyncSessionLocal() as db:
            notif = await emit(
                db,
                user_id=user_id,
                title="t",
                message="m",
                ntype=NotificationType.stage_stuck_7d,
                related_entity_type="candidate_stage",
                related_entity_id=_entity_id(),
                link="/jobs/1",
            )
            assert notif is not None
            await asyncio.sleep(0.05)
            assert user_id not in pushed
            await db.commit()
        for _ in range(20):
            if user_id in pushed:
                break
            await asyncio.sleep(0.05)
        assert pushed.count(user_id) == 1
    finally:
        await _cleanup([user_id])


async def test_re_mention_on_the_same_day_does_not_break_the_note_save() -> None:
    from app.services.mention_dispatch import enqueue_mention_notifications

    author_id = await _seed_user()
    user_id = await _seed_user()
    note_id = _entity_id()
    link = f"/candidates/{_entity_id()}?tab=activity&activity=notes&note={note_id}"
    try:
        for round_no in range(2):
            async with AsyncSessionLocal() as db:
                author = await db.get(User, author_id)
                pairs = await enqueue_mention_notifications(
                    db,
                    mentioned_user_ids=[user_id],
                    author=author,
                    deep_link_path=link,
                    snippet=f"runda {round_no}",
                    notification_title="Oznaczono Cię",
                    related_entity_type="note",
                    related_entity_id=note_id,
                )
                assert len(pairs) == 1
                assert pairs[0][1].created_at is not None
                await db.commit()
            if round_no == 0:
                async with AsyncSessionLocal() as db:
                    notif = await db.scalar(
                        select(Notification).where(
                            Notification.user_id == user_id,
                            Notification.related_entity_id == note_id,
                        )
                    )
                    notif.is_read = True
                    await db.commit()
        async with AsyncSessionLocal() as db:
            rows = (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.related_entity_id == note_id,
                    )
                )
            ).all()
        assert len(rows) == 1
        assert rows[0].message == "runda 1"
        assert rows[0].is_read is False
    finally:
        await _cleanup([author_id, user_id])


async def test_contract_alert_insert_skips_a_same_day_duplicate() -> None:
    from app.tasks.contract_alerts import _insert_dedup_notification

    user_id = await _seed_user()
    entity = _entity_id()
    values = dict(
        user_id=user_id,
        title="t",
        message="m",
        link="/contracts/1",
        notification_type=NotificationType.client_order_ending_30d,
        related_entity_type="contract",
        related_entity_id=entity,
    )
    try:
        async with AsyncSessionLocal() as db:
            # Dzwonek zamówienia #N ze skanera portalu DL — ten sam klucz indeksu.
            db.add(Notification(**{**values, "related_entity_type": "client_order"}))
            await db.flush()
            assert await _insert_dedup_notification(db, **values) is False
            await db.commit()
        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.related_entity_id == entity)
            )
        assert count == 1
    finally:
        await _cleanup([user_id])
