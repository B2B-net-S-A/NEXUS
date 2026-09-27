"""Runda 9 audytu — konta zakładane i resetowane przez admina (z bazą).

- R9-N1-1: adres konta zapisywany małymi literami, logowanie i „nie pamiętam
  hasła” bez rozróżniania wielkości liter.
- R9-N13-7: hasło od admina ma granice, imię nie dłuższe niż kolumna, nowe
  konto musi zmienić hasło przy pierwszym logowaniu.
- R9-N2-4: drugi reset hasła / drugi link resetu tego samego dnia nie wywraca
  operacji na ``ix_notif_dedup_daily``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.notification import Notification, NotificationType
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _company_domain(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "firma.example")


def _domain() -> str:
    return "firma.example"


async def _create(app_client, headers, **overrides):
    sfx = uuid.uuid4().hex[:8]
    payload = {
        "email": f"Nowy.Uzytkownik-{sfx}@{_domain().upper()}",
        "password": "Haslo-testowe-123!",
        "name": "Nowy Użytkownik",
    }
    payload.update(overrides)
    return payload, await app_client.post(
        "/api/admin/users", headers=headers, json=payload
    )


async def test_admin_created_account_is_lowercase_and_must_change_password(
    app_client, app_auth_headers
):
    payload, resp = await _create(app_client, app_auth_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == payload["email"].lower()

    async with AsyncSessionLocal() as db:
        user = await db.scalar(
            select(User).where(User.email == payload["email"].lower())
        )
        assert user is not None
        assert user.force_password_change is True

    # Logowanie adresem z INNYMI wielkimi literami działa.
    login = await app_client.post(
        "/api/auth/login",
        json={"email": payload["email"].upper(), "password": payload["password"]},
    )
    assert login.status_code == 200, login.text

    # Duplikat różniący się wielkością liter = 409.
    duplicate = await app_client.post(
        "/api/admin/users",
        headers=app_auth_headers,
        json={**payload, "email": payload["email"].swapcase()},
    )
    assert duplicate.status_code == 409


@pytest.mark.parametrize(
    "overrides",
    [
        {"password": ""},
        {"password": "krotkie"},
        {"password": "x" * 129},
        {"name": "x" * 256},
    ],
)
async def test_admin_create_user_validates_password_and_name(
    app_client, app_auth_headers, overrides
):
    _payload, resp = await _create(app_client, app_auth_headers, **overrides)
    assert resp.status_code == 422, resp.text


async def test_legacy_mixed_case_account_logs_in_and_gets_reset_link(
    app_client, app_auth_headers
):
    from app.core.security import hash_password

    sfx = uuid.uuid4().hex[:8]
    stored = f"Stare.Konto-{sfx}@Example.com"
    async with AsyncSessionLocal() as db:
        user = User(
            email=stored,
            password_hash=hash_password("Haslo-testowe-123!"),
            name="Stare Konto",
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    login = await app_client.post(
        "/api/auth/login",
        json={"email": stored.lower(), "password": "Haslo-testowe-123!"},
    )
    assert login.status_code == 200, login.text

    forgot = await app_client.post(
        "/api/auth/forgot-password", json={"email": stored.lower()}
    )
    assert forgot.status_code == 200, forgot.text
    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(func.count())
            .select_from(Activity)
            .where(
                Activity.entity_id == user_id,
                Activity.action == "password_reset_requested",
            )
        )
    assert found == 1


async def test_second_reset_and_second_link_on_the_same_day_do_not_500(
    app_client, app_auth_headers
):
    payload, created = await _create(app_client, app_auth_headers)
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    for _ in range(2):
        resp = await app_client.post(
            f"/api/admin/users/{user_id}/reset-password",
            headers=app_auth_headers,
            json={"new_password": "Nowe-haslo-456!"},
        )
        assert resp.status_code == 200, resp.text
        link = await app_client.post(
            f"/api/admin/users/{user_id}/send-reset-link",
            headers=app_auth_headers,
        )
        assert link.status_code == 200, link.text

    async with AsyncSessionLocal() as db:
        counts = {
            kind: await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.notification_type == kind,
                )
            )
            for kind in (
                NotificationType.password_changed_by_admin,
                NotificationType.password_reset_requested,
            )
        }
    assert set(counts.values()) == {1}, counts


async def test_admin_reset_password_rejects_empty_password(
    app_client, app_auth_headers
):
    _payload, created = await _create(app_client, app_auth_headers)
    user_id = created.json()["id"]
    resp = await app_client.post(
        f"/api/admin/users/{user_id}/reset-password",
        headers=app_auth_headers,
        json={"new_password": ""},
    )
    assert resp.status_code == 422
