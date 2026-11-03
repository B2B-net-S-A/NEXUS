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
from sqlalchemy import delete, text, update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.m365 import Email, EmailDirection
from app.services.m365.startup_reset import RESET_PENDING_SENDS_SQL
from app.models.user import User, UserRole

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _reset_sql() -> str:
    return RESET_PENDING_SENDS_SQL


def test_reset_runs_when_taking_over_the_loops_not_at_container_start() -> None:
    """Przy nakładaniu kontenerów start nie znaczy, że poprzednik nie żyje."""
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "send_state='uncertain'" not in source
    main = (ENTRYPOINT.parent / "app" / "main.py").read_text(encoding="utf-8")
    takeover = main.index("async def _on_background_leader_acquired")
    assert main.index("reset_interrupted_m365_state", takeover) < main.index(
        "_start_background_tasks()", takeover
    )


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
