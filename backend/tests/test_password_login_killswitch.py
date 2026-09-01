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


async def test_login_break_glass_email_bypasses_disabled_flag(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Break-glass: konto z listy NIE dostaje 503 mimo wyłączonej flagi.

    Bez tego wyłączenie ``PASSWORD_LOGIN_ENABLED`` na produkcji (tryb SSO-only)
    zamknęłoby na stałe admina, który ma tylko hasło i żadnej ścieżki SSO. Konta
    z ``PASSWORD_LOGIN_BREAK_GLASS_EMAILS`` przechodzą przez bramkę do zwykłego
    sprawdzenia poświadczeń — tu 401 (brak takiego konta w DB), NIE 503.
    """
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    resp = await app_client.post(
        "/api/auth/login", json={"email": "admin@x.com", "password": "cokolwiek"}
    )
    assert resp.status_code != 503
    assert resp.status_code == 401


async def test_login_break_glass_is_case_insensitive(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Dopasowanie po znormalizowanym (lowercase) adresie — wielkość liter nieistotna."""
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "Admin@X.com")
    resp = await app_client.post(
        "/api/auth/login", json={"email": "admin@x.com", "password": "cokolwiek"}
    )
    assert resp.status_code == 401


async def test_login_non_break_glass_email_still_503_when_disabled(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Adres spoza listy dalej dostaje 503 — wyjątek jest wąski, nie globalny."""
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    resp = await app_client.post(
        "/api/auth/login", json={"email": "other@x.com", "password": "cokolwiek"}
    )
    assert resp.status_code == 503


async def test_login_empty_break_glass_list_blocks_everyone(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Pusta lista (domyślnie) = zachowanie sprzed zmiany: wszyscy 503."""
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "")
    resp = await app_client.post(
        "/api/auth/login", json={"email": "admin@x.com", "password": "cokolwiek"}
    )
    assert resp.status_code == 503


async def test_forgot_password_break_glass_bypasses_disabled_flag(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Odzyskiwanie hasła dla admina awaryjnego działa mimo wyłączonej flagi.

    Zwraca generyczne 200 (anti-enumeration) zamiast 503 — inaczej break-glass
    admin nie mógłby nawet poprosić o link resetowy.
    """
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    resp = await app_client.post(
        "/api/auth/forgot-password", json={"email": "admin@x.com"}
    )
    assert resp.status_code == 200


async def test_forgot_password_non_break_glass_still_503(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    resp = await app_client.post(
        "/api/auth/forgot-password", json={"email": "other@x.com"}
    )
    assert resp.status_code == 503


async def test_reset_password_break_glass_defers_gate(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Z niepustą listą reset-password nie blokuje na wejściu (nie zna emaila).

    Token jest zużywany i rozstrzygany; nieprawidłowy token → 400, NIE 503 —
    dowód, że bramka „flag off → 503" została odroczona za rozpoznanie konta.
    """
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    resp = await app_client.post(
        "/api/auth/reset-password",
        json={"token": "a" * 64, "new_password": "NoweHaslo123!@#"},
    )
    assert resp.status_code != 503
    assert resp.status_code == 400


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


async def test_methods_reports_microsoft_off_when_sso_unconfigured(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Pole ``microsoft`` musi odzwierciedlać REALNY stan konfiguracji SSO.

    Wcześniejsze testy sprawdzały tylko, że klucz istnieje — regresja, w której
    ``is_sso_configured()`` zawsze zwraca tę samą wartość, przeszłaby je bez
    mrugnięcia. To nie jest hipotetyczne: pierwsza wersja tego endpointu miała
    warunek zbudowany z niewłaściwych ustawień i zgłaszała SSO jako dostępne
    także tam, gdzie ``/authorize`` zwróciłoby 503.
    """
    monkeypatch.setattr(settings, "M365_INTEGRATION_ENABLED", False)
    body = (await app_client.get("/api/auth/methods")).json()
    assert body["microsoft"] is False


async def test_methods_reports_microsoft_on_when_sso_configured(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Druga strona kontraktu — komplet ustawień = przycisk widoczny."""
    monkeypatch.setattr(settings, "M365_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(settings, "M365_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "M365_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(
        settings, "MICROSOFT_LOGIN_REDIRECT_URI", "https://example.test/cb"
    )
    body = (await app_client.get("/api/auth/methods")).json()
    assert body["microsoft"] is True
