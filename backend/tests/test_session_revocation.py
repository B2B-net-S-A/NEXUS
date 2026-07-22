"""F-05: zmiana / reset hasła unieważnia wcześniej wybite sesje (JWT).

Dziura: po zmianie lub resecie hasła wcześniej wybite tokeny JWT żyły do
naturalnego wygaśnięcia — nie było żadnego serwerowego punktu unieważnienia,
więc wykradziony/wyciekły token przeżywał reset hasła.

Fix: kolumna ``users.tokens_valid_after`` (migracja 0192). Backend ustawia ją
na ``now()`` przy KAŻDYM zdarzeniu zmiany hasła (self-service change-password,
reset przez token z maila, admin-reset) i odrzuca (401) token, którego ``iat``
jest ściśle wcześniejszy niż ta wartość — w ``get_current_user`` oraz na
ścieżce ``/api/auth/refresh``. NULL floor = brak unieważnienia (istniejący
userzy bez zdarzenia zmiany hasła nie są dotknięci).

Te testy dowodzą:
  (a) token wybity przed zmianą hasła jest po niej odrzucany 401,
  (b) user z NULL ``tokens_valid_after`` NIE jest dotknięty,
  (c) admin-reset też unieważnia sesje,
  (d) ścieżka /refresh respektuje floor.

Wszystkie in-process (fixture ``app_client``) — nie wymagają żywego serwera.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import ALGORITHM, hash_password
from app.models.activity import Activity
from app.models.notification import Notification
from app.models.user import User, UserRole


pytestmark = pytest.mark.asyncio


def _mint_access_token(user_id: int, role: str, iat: datetime) -> str:
    """Wybij access token z KONTROLOWANYM ``iat`` (unixowe sekundy).

    ``create_access_token`` ustawia ``iat`` na "teraz", co przy porównaniu z
    ``tokens_valid_after`` (też "teraz") daje flaky wynik w granicy sekundy.
    Tu ustawiamy ``iat`` jawnie, żeby test był deterministyczny.
    """
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": iat,
        "exp": iat + timedelta(hours=1),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def _mint_refresh_token(user_id: int, iat: datetime) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": iat,
        "exp": iat + timedelta(days=1),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


@pytest_asyncio.fixture
async def fresh_user() -> AsyncIterator[dict]:
    """Seed a fresh non-admin user (tokens_valid_after = NULL na starcie)."""
    unique = uuid.uuid4().hex[:8]
    email = f"pytest-revoke-{unique}@example.com"
    password = f"OldPass_{unique}_X"

    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Pytest Revoke User",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    yield {"id": user_id, "email": email, "password": password}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id == user_id))
        await db.execute(delete(Activity).where(Activity.user_id == user_id))
        u = await db.scalar(select(User).where(User.id == user_id))
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest.fixture(autouse=True)
def mock_email(monkeypatch):
    """No-op maile — zmiana/reset hasła wysyła powiadomienie."""

    def fake_send_email(to: str, subject: str, text_body: str, html_body=None):
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send_email)
    monkeypatch.setattr(
        "app.api.auth.send_password_changed_notification",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "app.api.admin.send_password_changed_notification",
        lambda **kwargs: True,
    )


async def _tokens_valid_after(user_id: int) -> datetime | None:
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == user_id))
        return u.tokens_valid_after


# ── (a) token wybity przed zmianą hasła → 401 po zmianie ──────────────────────


async def test_token_before_self_change_is_rejected_after(
    app_client: AsyncClient, fresh_user: dict
):
    """Self-service change-password unieważnia wcześniej wybity token."""
    old_iat = datetime.now(timezone.utc) - timedelta(seconds=10)
    token = _mint_access_token(fresh_user["id"], UserRole.recruiter.value, old_iat)
    headers = {"Authorization": f"Bearer {token}"}

    # Zanim zmienimy hasło — token działa (floor = NULL).
    before = await app_client.get("/api/auth/me", headers=headers)
    assert before.status_code == 200, before.text

    # Zmiana hasła tym samym tokenem (floor jeszcze NULL, więc autoryzacja
    # przechodzi) — ustawia tokens_valid_after = now().
    resp = await app_client.post(
        "/api/auth/change-password",
        json={
            "current_password": fresh_user["password"],
            "new_password": "BrandNewPass_99!",
        },
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    # Floor zapisany w DB.
    assert await _tokens_valid_after(fresh_user["id"]) is not None

    # Ten sam (stary) token jest już martwy → 401 (nie 403 — sesja martwa).
    after = await app_client.get("/api/auth/me", headers=headers)
    assert after.status_code == 401, (
        "Token wybity przed zmianą hasła musi być odrzucony 401 po zmianie — "
        "inaczej wykradziony token przeżywa reset hasła."
    )


async def test_new_token_after_change_still_works(
    app_client: AsyncClient, fresh_user: dict
):
    """Świeży token (iat po zdarzeniu) NIE jest fałszywie odrzucany."""
    # Ustaw floor bezpośrednio (symuluje wcześniejsze zdarzenie zmiany hasła).
    floor = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == fresh_user["id"]))
        u.tokens_valid_after = floor
        await db.commit()

    fresh_token = _mint_access_token(
        fresh_user["id"], UserRole.recruiter.value, floor + timedelta(seconds=10)
    )
    resp = await app_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {fresh_token}"}
    )
    assert resp.status_code == 200, resp.text


# ── (b) NULL tokens_valid_after → brak unieważnienia ──────────────────────────


async def test_null_floor_user_is_unaffected(app_client: AsyncClient, fresh_user: dict):
    """User bez zdarzenia zmiany hasła (floor NULL) → stary token wciąż ważny."""
    assert await _tokens_valid_after(fresh_user["id"]) is None

    # iat w przeszłości, ale token nadal niewygasły (exp = iat + 1h).
    old_iat = datetime.now(timezone.utc) - timedelta(seconds=30)
    token = _mint_access_token(fresh_user["id"], UserRole.recruiter.value, old_iat)
    resp = await app_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, (
        "NULL tokens_valid_after musi być traktowane jak brak floora — "
        "istniejący userzy nie mogą zostać wylogowani przez deploy."
    )


# ── (c) admin-reset unieważnia sesje ──────────────────────────────────────────


async def test_admin_reset_revokes_existing_token(
    app_client: AsyncClient, app_auth_headers: dict, fresh_user: dict
):
    """POST /api/admin/users/{id}/reset-password unieważnia tokeny usera."""
    old_iat = datetime.now(timezone.utc) - timedelta(seconds=10)
    token = _mint_access_token(fresh_user["id"], UserRole.recruiter.value, old_iat)
    headers = {"Authorization": f"Bearer {token}"}

    before = await app_client.get("/api/auth/me", headers=headers)
    assert before.status_code == 200, before.text

    resp = await app_client.post(
        f"/api/admin/users/{fresh_user['id']}/reset-password",
        json={"new_password": "AdminForced_99!"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert await _tokens_valid_after(fresh_user["id"]) is not None

    after = await app_client.get("/api/auth/me", headers=headers)
    assert after.status_code == 401, (
        "Po admin-resecie hasła wcześniej wybite tokeny usera muszą być martwe."
    )


# ── (d) /refresh respektuje floor ─────────────────────────────────────────────


async def test_refresh_token_before_floor_rejected(
    app_client: AsyncClient, fresh_user: dict
):
    """Refresh token wybity przed floorem → 401 (nie wybija świeżego access)."""
    floor = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == fresh_user["id"]))
        u.tokens_valid_after = floor
        await db.commit()

    stale_refresh = _mint_refresh_token(fresh_user["id"], floor - timedelta(seconds=10))
    resp = await app_client.post(
        "/api/auth/refresh", params={"refresh_token": stale_refresh}
    )
    assert resp.status_code == 401, (
        "Wykradziony refresh token nie może wybijać świeżych access tokenów "
        "po resecie hasła."
    )

    # Świeży refresh token (iat po floorze) — działa normalnie.
    fresh_refresh = _mint_refresh_token(fresh_user["id"], floor + timedelta(seconds=10))
    ok = await app_client.post(
        "/api/auth/refresh", params={"refresh_token": fresh_refresh}
    )
    assert ok.status_code == 200, ok.text
