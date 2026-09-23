"""Osoba od Cpro — jedna na firmę, z zastępstwem (Rekrutacja v5, 24.09.2026).

Reguła stanu (`next_state`, `effective`) jest czysta i testowana bez bazy;
trasy `GET/PUT /api/board-tasks/cpro/sender` — na bazie (CI).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.services import cpro_sender
from app.services.cpro_sender import CproSenderState, effective, next_state

NOW = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 24)


def _set(current: CproSenderState, user_id, until=None, actor=1):
    return next_state(
        current, user_id=user_id, until=until, actor_id=actor, today=TODAY, now=NOW
    )


def test_permanent_change_has_no_fallback() -> None:
    state = _set(CproSenderState(user_id=4), 5)
    assert state.user_id == 5
    assert state.fallback_user_id is None
    assert state.until is None
    assert state.set_by_user_id == 1 and state.set_at == NOW


def test_substitution_remembers_who_comes_back() -> None:
    state = _set(CproSenderState(user_id=4), 7, until=date(2026, 10, 3))
    assert (state.user_id, state.fallback_user_id) == (7, 4)
    # Ostatni dzień zastępstwa — dalej zastępca.
    assert effective(state, date(2026, 10, 3)).user_id == 7
    # Dzień później wraca osoba sprzed zastępstwa, bez niczyjego kliknięcia.
    back = effective(state, date(2026, 10, 4))
    assert back.user_id == 4
    assert back.until is None and back.fallback_user_id is None


def test_changing_the_substitute_keeps_the_original_fallback() -> None:
    first = _set(CproSenderState(user_id=4), 7, until=date(2026, 10, 3))
    second = _set(first, 8, until=date(2026, 10, 5))
    # Powrót to nadal 4, nie zastępca 7.
    assert (second.user_id, second.fallback_user_id) == (8, 4)


def test_substitution_after_an_expired_one_starts_from_the_returned_person() -> None:
    expired = CproSenderState(
        user_id=7, until=TODAY - timedelta(days=1), fallback_user_id=4
    )
    state = _set(expired, 9, until=TODAY + timedelta(days=2))
    assert (state.user_id, state.fallback_user_id) == (9, 4)


def test_substituting_yourself_has_no_fallback() -> None:
    state = _set(CproSenderState(user_id=4), 4, until=TODAY)
    assert state.fallback_user_id is None


def test_past_until_is_refused() -> None:
    with pytest.raises(HTTPException) as err:
        _set(CproSenderState(user_id=4), 7, until=TODAY - timedelta(days=1))
    assert err.value.status_code == 422


def test_substitution_needs_a_person() -> None:
    with pytest.raises(HTTPException) as err:
        _set(CproSenderState(user_id=4), None, until=TODAY)
    assert err.value.status_code == 422


def test_clearing_the_sender_is_allowed() -> None:
    assert _set(CproSenderState(user_id=4), None).user_id is None


@pytest.mark.parametrize(
    "raw",
    [None, "x", {}, {"user_id": "abc", "until": "nie-data"}],
)
def test_broken_setting_reads_as_nobody(raw) -> None:
    state = cpro_sender.parse_state(raw)
    assert state.user_id is None and state.until is None


def test_state_round_trips_through_json() -> None:
    state = CproSenderState(
        user_id=7,
        until=date(2026, 10, 3),
        fallback_user_id=4,
        set_by_user_id=1,
        set_at=NOW,
    )
    assert cpro_sender.parse_state(state.as_json()) == state


# ── Trasy (baza) ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_client():
    from httpx import ASGITransport, AsyncClient

    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_sender_routes_set_substitute_and_notify(api_client, monkeypatch) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType
    from app.models.user import UserRole
    from tests.test_board_tasks import _login, _seed_user, restore_cpro_sender

    async with restore_cpro_sender():
        rec_id, rec_creds = await _seed_user(UserRole.recruiter)
        sub_id, _ = await _seed_user(UserRole.recruiter)
        rec = await _login(api_client, rec_creds)

        set_ = await api_client.put(
            "/api/board-tasks/cpro/sender",
            headers=rec,
            json={"user_id": rec_id, "until": None},
        )
        assert set_.status_code == 200, set_.text
        assert set_.json()["user_id"] == rec_id

        until = (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat()
        sub = await api_client.put(
            "/api/board-tasks/cpro/sender",
            headers=rec,
            json={"user_id": sub_id, "until": until},
        )
        assert sub.status_code == 200, sub.text
        body = sub.json()
        assert body["user_id"] == sub_id
        assert body["until"] == until
        assert body["fallback_user_id"] == rec_id
        assert body["fallback_user_name"]
        assert body["set_by_name"]

        read = (
            await api_client.get("/api/board-tasks/cpro/sender", headers=rec)
        ).json()
        assert read["user_id"] == sub_id

        async with AsyncSessionLocal() as db:
            notice = await db.scalar(
                select(Notification.id).where(
                    Notification.user_id == sub_id,
                    Notification.notification_type
                    == NotificationType.cpro_send_assigned,
                )
            )
        assert notice is not None

        past = await api_client.put(
            "/api/board-tasks/cpro/sender",
            headers=rec,
            json={"user_id": sub_id, "until": "2000-01-01"},
        )
        assert past.status_code == 422

        async with AsyncSessionLocal() as db:
            from app.models.user import User

            inactive = await db.get(User, sub_id)
            inactive.is_active = False
            await db.commit()
        refused = await api_client.put(
            "/api/board-tasks/cpro/sender",
            headers=rec,
            json={"user_id": sub_id, "until": None},
        )
        assert refused.status_code == 422
