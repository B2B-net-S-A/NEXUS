"""Alert przy logowaniu hasłem z listy awaryjnej (0803, decyzja Artura z 27.11.2026).

Konto z ``PASSWORD_LOGIN_BREAK_GLASS_EMAILS`` wchodzi hasłem mimo trybu
SSO-only, czyli bez MFA Entra. Każde takie logowanie zostawia zdarzenie na
ekranie Bezpieczeństwo i dzwonek (z mailem) u każdego aktywnego admina; konto
„Automatyzacje” (E2E) zostawia samo zdarzenie. Zwykłe logowanie hasłem przy
włączonej fladze (testy, awaria SSO) nie alarmuje.

Dane fikcyjne: adres z puli dokumentacyjnej, e-maile z ``example.com``.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.security import SecurityEvent
from app.models.user import User, UserRole
from app.services.security_screen import BREAK_GLASS_LOGIN

LOGIN = "/api/auth/login"
IP = "203.0.113.7"


async def _last_event_id() -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.coalesce(func.max(SecurityEvent.id), 0)).where(
                    SecurityEvent.kind == BREAK_GLASS_LOGIN
                )
            )
        )


async def _events_after(event_id: int) -> list[SecurityEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == BREAK_GLASS_LOGIN,
                    SecurityEvent.id > event_id,
                )
                .order_by(SecurityEvent.id)
            )
        )


async def _bells(event_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.break_glass_password_login,
                    Notification.related_entity_type == "security_event",
                    Notification.related_entity_id == event_id,
                )
            )
        )


async def test_break_glass_login_rings_every_admin_with_ip(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = app_client.headers["X-Test-Admin-Email"]
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", email)
    before = await _last_event_id()

    resp = await app_client.post(
        LOGIN,
        json={"email": email, "password": app_client.headers["X-Test-Admin-Password"]},
        headers={"X-Forwarded-For": IP},
    )

    assert resp.status_code == 200, resp.text
    (event,) = await _events_after(before)
    assert event.severity == "high" and event.source == "nexus"
    # Zdarzenia ekranu nie trzymają danych osobowych — w opisie tylko id i rola.
    assert email not in event.summary and IP not in event.summary
    async with AsyncSessionLocal() as db:
        me = await db.scalar(select(User).where(User.email == email))
    bells = await _bells(event.id)
    assert me.id in {b.user_id for b in bells}
    mine = next(b for b in bells if b.user_id == me.id)
    assert email in mine.message and IP in mine.message
    assert mine.link == "/settings?area=sys&item=security"


async def test_second_break_glass_login_same_day_rings_again(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dzienny dedup ``emit`` nie może skleić dwóch logowań w jeden dzwonek."""
    email = app_client.headers["X-Test-Admin-Email"]
    password = app_client.headers["X-Test-Admin-Password"]
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", email)
    before = await _last_event_id()

    for _ in range(2):
        resp = await app_client.post(LOGIN, json={"email": email, "password": password})
        assert resp.status_code == 200, resp.text

    first, second = await _events_after(before)
    assert await _bells(first.id) and await _bells(second.id)


async def test_wrong_password_on_break_glass_address_does_not_ring(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = app_client.headers["X-Test-Admin-Email"]
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", email)
    before = await _last_event_id()

    resp = await app_client.post(LOGIN, json={"email": email, "password": "zle-haslo"})

    assert resp.status_code == 401
    assert await _events_after(before) == []


async def test_password_login_with_flag_on_is_not_an_alert(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flaga włączona (testy, awaria SSO) = zwykłe logowanie, bez alarmu."""
    email = app_client.headers["X-Test-Admin-Email"]
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", email)
    before = await _last_event_id()

    resp = await app_client.post(
        LOGIN,
        json={"email": email, "password": app_client.headers["X-Test-Admin-Password"]},
    )

    assert resp.status_code == 200, resp.text
    assert await _events_after(before) == []


async def test_automation_account_leaves_event_without_bells(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Konto E2E loguje się co noc i po każdym wdrożeniu — sam ślad, bez maila."""
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    password = "Haslo-E2E-" + uuid.uuid4().hex[:12]
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Automatyzacje E2E",
                role=UserRole.automation,
                is_active=True,
                email_verified=True,
            )
        )
        await db.commit()
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", email)
    before = await _last_event_id()

    resp = await app_client.post(LOGIN, json={"email": email, "password": password})

    assert resp.status_code == 200, resp.text
    (event,) = await _events_after(before)
    assert event.severity == "info"
    assert await _bells(event.id) == []
