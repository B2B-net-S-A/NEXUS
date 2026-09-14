"""Sonda `checks.m365` uwzględnia stan synchronizacji skrzynek (UAT M11-B07).

Do 09.2026 wystarczało jedno aktywne połączenie, żeby sonda mówiła
``healthy`` — także gdy skrzynka od dwóch tygodni tkwiła w błędzie Graph.

Stany w testach bazodanowych odtwarzają to, co naprawdę zapisuje produkcja:
nieudana próba stempluje ŚWIEŻE ``last_sync_at``, a stany końcowe wyłączają
połączenie (``is_active=False``). Wcześniejsza wersja sondy patrzyła na wiek
``last_sync_at`` i przechodziła testy zbudowane na stanie, którego produkcja
nigdy nie trzyma.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.services.m365_health import M365ConnectionSyncState, m365_sync_verdict


def _state(status: str, *, active: bool = True) -> M365ConnectionSyncState:
    return M365ConnectionSyncState(status=status, is_active=active)


def test_no_active_connection_is_degraded():
    assert m365_sync_verdict([]) == "degraded"
    assert m365_sync_verdict([_state("idle", active=False)]) == "degraded"


def test_active_mailbox_whose_last_attempt_failed_is_degraded():
    assert m365_sync_verdict([_state("idle"), _state("error")]) == "degraded"


def test_connection_switched_off_by_a_failure_is_degraded():
    states = [_state("idle"), _state("reconnect_required", active=False)]
    assert m365_sync_verdict(states) == "degraded"
    states = [_state("idle"), _state("error", active=False)]
    assert m365_sync_verdict(states) == "degraded"


def test_idle_and_running_connections_are_healthy():
    assert m365_sync_verdict([_state("idle"), _state("running")]) == "healthy"


async def _make_user(db, unique: str, *, is_active: bool = True):
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    user = User(
        email=f"m365-health-{unique}@example.com",
        password_hash=hash_password(f"T3st_{unique}!PassX"),
        name="M365 Health Test",
        role=UserRole.recruiter,
        is_active=is_active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _connection(user_id: int, unique: str, **fields):
    from app.models.m365 import M365Connection

    now = datetime.now(timezone.utc)
    return M365Connection(
        user_id=user_id,
        tenant_id="test-tenant",
        mailbox_upn=f"m365-health-{unique}@example.com",
        access_token_ct="ct-access",
        refresh_token_ct="ct-refresh",
        expires_at=now + timedelta(hours=1),
        **fields,
    )


async def test_mailbox_failing_on_every_retry_is_degraded():
    """Błąd ponawiany co 30 min ma ŚWIEŻĄ datę próby — to jej wiek zmylił sondę."""
    from app.core.database import AsyncSessionLocal
    from app.models.m365 import M365SyncStatus
    from app.services.m365_health import m365_health_status

    unique = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = await _make_user(db, unique)
        db.add(
            _connection(
                user.id,
                unique,
                is_active=True,
                last_sync_status=M365SyncStatus.error,
                last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                last_error="retry_after cap exceeded (5x)",
            )
        )
        await db.commit()

        assert await m365_health_status(db) == "degraded"


async def test_reconnect_required_mailbox_of_active_user_is_degraded():
    from app.core.database import AsyncSessionLocal
    from app.models.m365 import M365SyncStatus
    from app.services.m365_health import m365_health_status

    unique = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = await _make_user(db, unique)
        db.add(
            _connection(
                user.id,
                unique,
                is_active=False,
                last_sync_status=M365SyncStatus.reconnect_required,
                last_error="refresh token invalid — user must reconnect",
            )
        )
        await db.commit()

        assert await m365_health_status(db) == "degraded"
