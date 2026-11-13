"""FIX-07 (audyt 22.09 r2): restart zamienia przerwane wysyłki ``pending``
na ``uncertain``.

Test czyta instrukcję WPROST z ``entrypoint.sh`` i wykonuje ją na bazie —
kopia SQL-a w teście przechodziłaby niezależnie od tego, co jest w skrypcie.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text, update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.m365 import Email, EmailDirection, M365Connection, M365SyncStatus
from app.core.database import engine
from app.core.process_lock import lock_namespace
from app.core.process_role import task_runs_in_role
from app.services.m365.graph_client import _HARD_TIMEOUT_SECONDS
from app.services.m365.startup_reset import (
    PENDING_SEND_MARGIN_MINUTES,
    RESET_PENDING_SENDS_SQL,
    reset_interrupted_m365_state,
)
from app.models.user import User, UserRole

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _reset_sql() -> str:
    return RESET_PENDING_SENDS_SQL


def test_reset_is_a_worker_loop_not_a_startup_step() -> None:
    """Przy rolling update start nie znaczy, że poprzednik nie żyje (etap B2)."""
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "send_state='uncertain'" not in source
    main = (ENTRYPOINT.parent / "app" / "main.py").read_text(encoding="utf-8")
    takeover = main[main.index("async def _on_background_leader_acquired") :]
    takeover = takeover[: takeover.index("async def _on_background_leader_lost")]
    assert "reset_interrupted_m365_state" not in takeover
    assert '"m365_interrupted_reset": asyncio.create_task(' in main
    assert not task_runs_in_role("m365_interrupted_reset", "web")
    assert task_runs_in_role("m365_interrupted_reset", "worker")


def test_pending_margin_outlasts_the_longest_send() -> None:
    """Szkic, załączniki i wysyłka: trzy wywołania Graph po twardym limicie."""
    assert PENDING_SEND_MARGIN_MINUTES * 60 > 3 * _HARD_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_running_sync_with_a_live_lock_stays_running() -> None:
    """Przebieg w drugim procesie trzyma `cross_process_lock` — jego stan zostaje."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        conns = []
        for tag in ("live", "dead"):
            user = User(
                email=f"sync-{tag}-{suffix}@example.com",
                password_hash=hash_password("P@ss"),
                name="SyncReset",
                role=UserRole.recruiter,
                is_active=True,
            )
            db.add(user)
            await db.flush()
            conn = M365Connection(
                user_id=user.id,
                tenant_id="t",
                mailbox_upn=user.email,
                access_token_ct="a",
                refresh_token_ct="r",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                is_active=True,
                last_sync_status=M365SyncStatus.running,
            )
            db.add(conn)
            await db.flush()
            conns.append((user.id, conn.id))
        await db.commit()
    (live_user, live), (dead_user, dead) = conns
    lock = {"ns": lock_namespace("m365_sync"), "id": live}
    try:
        async with AsyncSessionLocal() as holder:
            await holder.execute(
                text("SELECT pg_advisory_lock(CAST(:ns AS int), :id)"), lock
            )
            try:
                async with engine.begin() as conn:
                    await reset_interrupted_m365_state(conn)
            finally:
                await holder.execute(
                    text("SELECT pg_advisory_unlock(CAST(:ns AS int), :id)"), lock
                )
        async with AsyncSessionLocal() as db:
            states = dict(
                (
                    await db.execute(
                        select(
                            M365Connection.id, M365Connection.last_sync_status
                        ).where(M365Connection.id.in_([live, dead]))
                    )
                ).all()
            )
        assert states[live] == M365SyncStatus.running
        assert states[dead] == M365SyncStatus.idle
    finally:
        async with AsyncSessionLocal() as db:
            users = [live_user, dead_user]
            await db.execute(
                delete(M365Connection).where(M365Connection.user_id.in_(users))
            )
            await db.execute(delete(User).where(User.id.in_(users)))
            await db.commit()


@pytest.mark.asyncio
async def test_stale_pending_send_becomes_uncertain_fresh_one_stays() -> None:
    sql = _reset_sql()
    suffix = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"reset-{suffix}@example.com",
            password_hash=hash_password("P@ss"),
            name="Reset",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.flush()

        def _row(tag: str, state: str) -> Email:
            return Email(
                user_id=user.id,
                m365_message_id=f"{tag}-{suffix}",
                m365_conversation_id="conv",
                from_address="me@example.com",
                received_at=now,
                direction=EmailDirection.sent,
                send_state=state,
                idempotency_key=f"{tag}-{suffix}",
            )

        stale, fresh, sent = (
            _row("stale", "pending"),
            _row("fresh", "pending"),
            _row("sent", "sent"),
        )
        db.add_all([stale, fresh, sent])
        await db.flush()
        await db.execute(
            update(Email)
            .where(Email.id.in_([stale.id, sent.id]))
            .values(created_at=now - timedelta(minutes=30))
        )
        await db.commit()
        ids = (user.id, stale.id, fresh.id, sent.id)

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text(sql))
            await db.commit()
        async with AsyncSessionLocal() as db:
            states = {
                row.id: row.send_state
                for row in (
                    await db.execute(
                        text("SELECT id, send_state FROM emails WHERE user_id = :u"),
                        {"u": ids[0]},
                    )
                ).all()
            }
        assert states[ids[1]] == "uncertain"
        assert states[ids[2]] == "pending"
        assert states[ids[3]] == "sent"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Email).where(Email.user_id == ids[0]))
            await db.execute(delete(User).where(User.id == ids[0]))
            await db.commit()
