"""Killswitch logowania hasłem (``PASSWORD_LOGIN_ENABLED``).

NEXUS jest narzędziem wewnętrznym — na produkcji jedyną drogą wejścia ma być
Microsoft SSO (ograniczony do ``SSO_ALLOWED_DOMAINS``). Flaga domyślnie stoi na
**True**, bo ``tests/conftest.py`` uwierzytelnia się przez POST /api/auth/login
i zależy od tego kilkadziesiąt plików testowych; ochronę daje ustawienie flagi
na False w Coolify, nie usunięcie kodu.

Te testy pilnują obu stron kontraktu:
  • wyłączona  → /login, /forgot-password, /reset-password zwracają 503,
  • włączona   → działają normalnie (żeby killswitch nie zepsuł CI ani
                 drogi awaryjnej, gdy Azure padnie).
"""
import pytest
from httpx import AsyncClient

from app.core.config import settings


async def test_login_returns_503_when_disabled(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    resp = await app_client.post(
        "/api/auth/login", json={"email": "ktos@b2bnet.pl", "password": "cokolwiek"}
    )
    assert resp.status_code == 503
    assert "Microsoft" in resp.json()["detail"]


async def test_forgot_password_returns_503_when_disabled(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Reset hasła, którym i tak nie da się zalogować, tylko myli i wysyła maile."""
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    resp = await app_client.post(
        "/api/auth/forgot-password", json={"email": "ktos@b2bnet.pl"}
    )
    assert resp.status_code == 503


async def test_reset_password_returns_503_when_disabled(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Domyka też linki resetowe wysłane ZANIM flagę wyłączono."""
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    resp = await app_client.post(
        "/api/auth/reset-password",
        json={"token": "a" * 64, "new_password": "NoweHaslo123!@#"},
    )
    assert resp.status_code == 503


async def test_login_not_gated_when_enabled(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Włączona flaga = zachowanie sprzed zmiany (401 za złe hasło, NIE 503).

    Pilnuje drogi awaryjnej: gdy Azure/SSO padnie, przestawienie flagi w
    Coolify musi realnie przywrócić logowanie hasłem.
    """
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", True)
    resp = await app_client.post(
        "/api/auth/login",
        json={"email": "nie-ma-takiego@b2bnet.pl", "password": "zle"},
    )
    assert resp.status_code == 401


async def test_methods_reports_disabled_password(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "SELF_REGISTRATION_ENABLED", False)
    body = (await app_client.get("/api/auth/methods")).json()
    assert body["password"] is False
    assert body["self_registration"] is False


async def test_methods_reports_enabled_password(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "SELF_REGISTRATION_ENABLED", True)
    body = (await app_client.get("/api/auth/methods")).json()
    assert body["password"] is True
    assert body["self_registration"] is True


async def test_methods_is_public(app_client: AsyncClient):
    """Ekran /login musi móc odpytać to bez tokenu — inaczej pokaże zły wariant."""
    resp = await app_client.get("/api/auth/methods")
    assert resp.status_code == 200
    assert set(resp.json()) == {"password", "microsoft", "self_registration"}
