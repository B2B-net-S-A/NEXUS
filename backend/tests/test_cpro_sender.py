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


def test_substituting_yourself_keeps_you_after_the_date() -> None:
    # Audyt 25.09.2026 (runda 4): zastępstwo z datą dla osoby, która i tak
    # wysyła na stałe, nie może zostawić kolejki bez nikogo po tej dacie.
    state = _set(CproSenderState(user_id=4), 4, until=TODAY)
    assert state.fallback_user_id == 4
    assert effective(state, TODAY + timedelta(days=1)).user_id == 4


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
        _admin_id, admin_creds = await _seed_user(UserRole.admin)
        recruiter = await _login(api_client, rec_creds)
        # Od 25.09.2026 osobę od Cpro ustawia admin albo DL Nordei.
        refused_role = await api_client.put(
            "/api/board-tasks/cpro/sender",
            headers=recruiter,
            json={"user_id": rec_id, "until": None},
        )
        assert refused_role.status_code == 403, refused_role.text
        assert "admin" in refused_role.json()["detail"]
        rec = await _login(api_client, admin_creds)

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

        # Audyt 25.09.2026 (runda 4): martwe konto nie jest osobą od Cpro —
        # dezaktywowany zastępca = „nikt", a uprawniony widzi przełącznik.
        dead = (
            await api_client.get("/api/board-tasks/cpro/sender", headers=rec)
        ).json()
        assert dead["user_id"] is None
        assert dead["can_set"] is True


@pytest.mark.asyncio
async def test_only_a_nordea_delivery_lead_or_admin_sets_the_sender(
    api_client, monkeypatch
) -> None:
    """Decyzja Artura 25.09.2026: osobę od Cpro ustawia admin albo DL
    przypisany do klienta Nordei. DL innego klienta, HoR i rekruter — 403."""

    import uuid

    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import UserRole
    from tests.test_board_tasks import _login, _seed_user, restore_cpro_sender

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        nordea = Client(name=f"Nordea R4 {unique}")
        other = Client(name=f"Inny R4 {unique}")
        db.add_all([nordea, other])
        await db.commit()
        nordea_id, other_id = nordea.id, other.id
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(nordea_id))

    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    other_dl_id, other_dl_creds = await _seed_user(UserRole.delivery_lead)
    _hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    try:
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    DeliveryLeadClientAssignment(
                        delivery_lead_user_id=dl_id, client_id=nordea_id
                    ),
                    DeliveryLeadClientAssignment(
                        delivery_lead_user_id=other_dl_id, client_id=other_id
                    ),
                ]
            )
            await db.commit()
        async with restore_cpro_sender():
            body = {"user_id": rec_id, "until": None}
            for creds in (other_dl_creds, hor_creds, rec_creds):
                headers = await _login(api_client, creds)
                refused = await api_client.put(
                    "/api/board-tasks/cpro/sender", headers=headers, json=body
                )
                assert refused.status_code == 403, refused.text
                read = await api_client.get(
                    "/api/board-tasks/cpro/sender", headers=headers
                )
                assert read.json()["can_set"] is False
                tasks = await api_client.get("/api/board-tasks", headers=headers)
                assert tasks.json()["can_set_cpro_sender"] is False

            dl = await _login(api_client, dl_creds)
            ok = await api_client.put(
                "/api/board-tasks/cpro/sender", headers=dl, json=body
            )
            assert ok.status_code == 200, ok.text
            assert ok.json()["user_id"] == rec_id
            assert ok.json()["can_set"] is True
            tasks = await api_client.get("/api/board-tasks", headers=dl)
            assert tasks.json()["can_set_cpro_sender"] is True
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(DeliveryLeadClientAssignment).where(
                    DeliveryLeadClientAssignment.client_id.in_([nordea_id, other_id])
                )
            )
            await db.execute(delete(Client).where(Client.id.in_([nordea_id, other_id])))
            await db.commit()
