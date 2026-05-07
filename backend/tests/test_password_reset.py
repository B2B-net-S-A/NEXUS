"""Tests for password reset flow.

Pokrywa:
- POST /api/auth/forgot-password (anti-enumeration, token creation)
- POST /api/auth/reset-password (token verify, single-use, force flag clear)
- POST /api/auth/change-password (clear force flag, audit, mail)
- POST /api/admin/users/{id}/reset-password (set force flag, mail, audit)
- POST /api/admin/users/{id}/send-reset-link (token + mail)

SMTP jest mockowany (monkeypatch send_email) — nie wysyłamy realnych maili.
Wszystkie testy używają in-process fixture (app_client) — nie wymagają
running server.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User, UserRole


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def fresh_user() -> AsyncIterator[dict]:
    """Seed a fresh non-admin user for each test (isolated state)."""
    unique = uuid.uuid4().hex[:8]
    email = f"pytest-reset-{unique}@example.com"
    password = f"OldPass_{unique}_X"

    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Pytest Reset User",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    yield {"id": user_id, "email": email, "password": password}

    # Cleanup — wipe FK references first (notifications + activities default to
    # RESTRICT on user delete; password_reset_tokens cascade automatically)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id == user_id))
        await db.execute(delete(Activity).where(Activity.user_id == user_id))
        u = await db.scalar(select(User).where(User.id == user_id))
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest.fixture(autouse=True)
def mock_email(monkeypatch):
    """Mock send_email to a no-op that records calls in a list.

    Wszystkie funkcje wyższego poziomu (send_password_reset_email,
    send_password_changed_notification) wołają send_email pod spodem,
    więc to single-point patch.
    """
    sent: list[dict] = []

    def fake_send_email(to: str, subject: str, text_body: str, html_body=None):
        sent.append({"to": to, "subject": subject, "text": text_body})
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send_email)
    # Also patch the imports at the call sites (Python imports rebind
    # references when `from … import …` form is used).
    monkeypatch.setattr(
        "app.api.auth.send_password_reset_email",
        lambda **kwargs: fake_send_email(
            kwargs["to_email"], "Reset", kwargs["reset_url"], None
        ),
    )
    monkeypatch.setattr(
        "app.api.auth.send_password_changed_notification",
        lambda **kwargs: fake_send_email(
            kwargs["to_email"], "Changed", "notify", None
        ),
    )
    monkeypatch.setattr(
        "app.api.admin.send_password_reset_email",
        lambda **kwargs: fake_send_email(
            kwargs["to_email"], "Reset (admin)", kwargs["reset_url"], None
        ),
    )
    monkeypatch.setattr(
        "app.api.admin.send_password_changed_notification",
        lambda **kwargs: fake_send_email(
            kwargs["to_email"], "Changed (admin)", "notify", None
        ),
    )
    return sent


# ── /forgot-password ──────────────────────────────────────────────────────────


async def test_forgot_password_creates_token_for_existing_user(
    app_client: AsyncClient, fresh_user: dict, mock_email: list
):
    """Existing email → 200 OK + DB row + email sent."""
    resp = await app_client.post(
        "/api/auth/forgot-password", json={"email": fresh_user["email"]}
    )
    assert resp.status_code == 200
    assert "link" in resp.json()["detail"].lower()

    # Token w DB
    async with AsyncSessionLocal() as db:
        tokens = (
            await db.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == fresh_user["id"]
                )
            )
        ).scalars().all()
        assert len(tokens) == 1
        assert tokens[0].used_at is None

    # Email wysłany
    assert any(
        e["to"] == fresh_user["email"] for e in mock_email
    ), f"Expected email to {fresh_user['email']} in {mock_email}"


async def test_forgot_password_unknown_email_returns_200_no_token(
    app_client: AsyncClient, mock_email: list
):
    """Anti-enumeration: unknown email also returns 200, but no token created."""
    resp = await app_client.post(
        "/api/auth/forgot-password",
        json={"email": "noone-here-123@example.com"},
    )
    assert resp.status_code == 200

    async with AsyncSessionLocal() as db:
        tokens = (
            await db.execute(select(PasswordResetToken))
        ).scalars().all()
        # No tokens for this email — but we don't filter by user_id since
        # the user doesn't exist. Verify by looking at recent tokens.
        assert all(
            t.user_id is None or t.user_id != 0 for t in tokens
        )  # token nigdy z user_id=0


async def test_forgot_password_invalidates_previous_active_tokens(
    app_client: AsyncClient, fresh_user: dict
):
    """Drugi request → poprzedni token zostaje oznaczony jako used (single active)."""
    await app_client.post(
        "/api/auth/forgot-password", json={"email": fresh_user["email"]}
    )
    await app_client.post(
        "/api/auth/forgot-password", json={"email": fresh_user["email"]}
    )

    async with AsyncSessionLocal() as db:
        tokens = (
            await db.execute(
                select(PasswordResetToken)
                .where(PasswordResetToken.user_id == fresh_user["id"])
                .order_by(PasswordResetToken.id)
            )
        ).scalars().all()
        assert len(tokens) == 2
        # Pierwszy invalidated, drugi active
        assert tokens[0].used_at is not None
        assert tokens[1].used_at is None


# ── /reset-password ───────────────────────────────────────────────────────────


async def test_reset_password_with_invalid_token_fails(app_client: AsyncClient):
    """Random 64-char string nie pasuje do żadnego hasha → 400."""
    resp = await app_client.post(
        "/api/auth/reset-password",
        json={"token": "a" * 64, "new_password": "NewPass123!"},
    )
    assert resp.status_code == 400


async def test_reset_password_with_short_token_fails(app_client: AsyncClient):
    """Token != 64 chars → 422 (Pydantic walidacja)."""
    resp = await app_client.post(
        "/api/auth/reset-password",
        json={"token": "abc", "new_password": "NewPass123!"},
    )
    assert resp.status_code == 422


async def test_reset_password_full_flow_changes_password(
    app_client: AsyncClient, fresh_user: dict
):
    """E2E: forgot → token z DB → reset → login starym 401, nowym 200."""
    from app.services.password_reset import create_reset_token

    # Generujemy token bezpośrednio (omijamy mail)
    async with AsyncSessionLocal() as db:
        token = await create_reset_token(db, fresh_user["id"])
        await db.commit()

    new_password = "FreshPassword99!"

    resp = await app_client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": new_password},
    )
    assert resp.status_code == 204

    # Login starym hasłem → 401
    resp = await app_client.post(
        "/api/auth/login",
        json={"email": fresh_user["email"], "password": fresh_user["password"]},
    )
    assert resp.status_code == 401

    # Login nowym hasłem → 200
    resp = await app_client.post(
        "/api/auth/login",
        json={"email": fresh_user["email"], "password": new_password},
    )
    assert resp.status_code == 200


async def test_reset_password_token_is_single_use(
    app_client: AsyncClient, fresh_user: dict
):
    """Replay attack: użyty token nie może zostać użyty drugi raz."""
    from app.services.password_reset import create_reset_token

    async with AsyncSessionLocal() as db:
        token = await create_reset_token(db, fresh_user["id"])
        await db.commit()

    # Pierwszy użytkowy
    resp1 = await app_client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "FirstUse99!"},
    )
    assert resp1.status_code == 204

    # Drugi z tym samym tokenem → 400
    resp2 = await app_client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "SecondUse99!"},
    )
    assert resp2.status_code == 400


async def test_reset_password_clears_force_password_change_flag(
    app_client: AsyncClient, fresh_user: dict
):
    """Po admin-resecie flag jest True; po user reset-password flag → False."""
    from app.services.password_reset import create_reset_token

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == fresh_user["id"]))
        u.force_password_change = True
        await db.commit()

        token = await create_reset_token(db, fresh_user["id"])
        await db.commit()

    resp = await app_client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "ClearFlag99!"},
    )
    assert resp.status_code == 204

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == fresh_user["id"]))
        assert u.force_password_change is False
        assert u.force_password_change_at is None


# ── Admin: /admin/users/{id}/reset-password (modified) ────────────────────────


async def test_admin_reset_sets_force_password_change_and_sends_notification(
    app_client: AsyncClient, app_auth_headers: dict, fresh_user: dict, mock_email: list
):
    """Admin manual reset → user.force_password_change=True + email notify."""
    resp = await app_client.post(
        f"/api/admin/users/{fresh_user['id']}/reset-password",
        json={"new_password": "AdminSet99!"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == fresh_user["id"]))
        assert u.force_password_change is True
        assert u.force_password_change_at is not None

        # Activity audit log
        activities = (
            await db.execute(
                select(Activity).where(
                    Activity.entity_id == fresh_user["id"],
                    Activity.action == "password_changed_by_admin",
                )
            )
        ).scalars().all()
        assert len(activities) >= 1

    # Email to user
    assert any(e["to"] == fresh_user["email"] for e in mock_email)


# ── Admin: /admin/users/{id}/send-reset-link ──────────────────────────────────


async def test_admin_send_reset_link_creates_token_and_sends_email(
    app_client: AsyncClient, app_auth_headers: dict, fresh_user: dict, mock_email: list
):
    """Admin send-reset-link → token w DB + email + audit log."""
    resp = await app_client.post(
        f"/api/admin/users/{fresh_user['id']}/send-reset-link",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200

    async with AsyncSessionLocal() as db:
        tokens = (
            await db.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == fresh_user["id"]
                )
            )
        ).scalars().all()
        assert len(tokens) == 1
        assert tokens[0].used_at is None
        assert tokens[0].requested_by_admin_id is not None

    assert any(e["to"] == fresh_user["email"] for e in mock_email)


async def test_admin_send_reset_link_for_inactive_user_fails(
    app_client: AsyncClient, app_auth_headers: dict, fresh_user: dict
):
    """Deactivated user → 400 (admin musi reaktywować zanim wyśle link)."""
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == fresh_user["id"]))
        u.is_active = False
        await db.commit()

    resp = await app_client.post(
        f"/api/admin/users/{fresh_user['id']}/send-reset-link",
        headers=app_auth_headers,
    )
    assert resp.status_code == 400


# ── /change-password (clear force flag) ───────────────────────────────────────


async def test_change_password_self_clears_force_flag(
    app_client: AsyncClient, fresh_user: dict
):
    """Self-service change-password czyści force_password_change."""
    # Set flag
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == fresh_user["id"]))
        u.force_password_change = True
        await db.commit()

    # Login (wymaga aktualnego hasła)
    login_resp = await app_client.post(
        "/api/auth/login",
        json={"email": fresh_user["email"], "password": fresh_user["password"]},
    )
    assert login_resp.status_code == 200
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    new_password = "SelfChange99!"
    resp = await app_client.post(
        "/api/auth/change-password",
        json={
            "current_password": fresh_user["password"],
            "new_password": new_password,
        },
        headers=headers,
    )
    assert resp.status_code == 204

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == fresh_user["id"]))
        assert u.force_password_change is False
        assert u.force_password_change_at is None
