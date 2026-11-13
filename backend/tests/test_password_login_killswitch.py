"""Killswitch logowania hasłem (``PASSWORD_LOGIN_ENABLED``).

NEXUS jest narzędziem wewnętrznym — na produkcji jedyną drogą wejścia ma być
Microsoft SSO (ograniczony do ``SSO_ALLOWED_DOMAINS``). Flaga domyślnie stoi na
**True**, bo ``tests/conftest.py`` uwierzytelnia się przez POST /api/auth/login
i zależy od tego kilkadziesiąt plików testowych; ochronę daje ustawienie flagi
na False w Coolify, nie usunięcie kodu.

Te testy pilnują obu stron kontraktu:
  • wyłączona  → /login, /forgot-password, /reset-password zwracają 503,
                 a przy niepustej liście break-glass adres spoza niej dostaje
                 tę samą odpowiedź co adres z listy (pentest 13.11.2026),
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


async def test_login_non_break_glass_email_looks_like_wrong_password(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Pentest 13.11.2026: adres spoza listy dostawał 503, a adres z listy 401.

    Ta różnica pozwalała anonimowi ustalić adres konta awaryjnego, więc przy
    skonfigurowanej liście każdy adres dostaje tę samą odpowiedź co złe hasło.
    Wyjątek dalej jest wąski: adres spoza listy nie zaloguje się nawet dobrym
    hasłem (nie sprawdzamy go wcale).
    """
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    on_list = await app_client.post(
        "/api/auth/login", json={"email": "admin@x.com", "password": "cokolwiek"}
    )
    off_list = await app_client.post(
        "/api/auth/login", json={"email": "other@x.com", "password": "cokolwiek"}
    )
    assert off_list.status_code == on_list.status_code == 401
    assert off_list.json() == on_list.json()


async def test_login_non_break_glass_existing_account_cannot_log_in(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Dobre hasło konta spoza listy przy wyłączonym logowaniu = 401, nie token."""
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    resp = await app_client.post(
        "/api/auth/login",
        json={
            "email": app_client.headers["X-Test-Admin-Email"],
            "password": app_client.headers["X-Test-Admin-Password"],
        },
    )
    assert resp.status_code == 401
    assert "access_token" not in resp.json()


async def test_login_spends_bcrypt_for_unknown_and_off_list_addresses(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Pentest 13.11.2026: konto z hasłem odpowiadało w 181 ms, brak konta w 4 ms.

    Każda odmowa liczy bcrypt (na atrapie, gdy nie ma prawdziwego hasha), żeby
    czas odpowiedzi nie zdradzał, które adresy mają konto.
    """
    import app.api.auth as auth_module

    calls: list[object] = []
    real_verify = auth_module.verify_password

    def spy(plain: str, hashed: object) -> bool:
        calls.append(hashed)
        return real_verify(plain, hashed)

    monkeypatch.setattr(auth_module, "verify_password", spy)

    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", True)
    await app_client.post(
        "/api/auth/login",
        json={"email": "nie-ma-takiego@b2bnet.pl", "password": "zle"},
    )
    assert len(calls) == 1

    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    await app_client.post(
        "/api/auth/login", json={"email": "other@x.com", "password": "zle"}
    )
    assert len(calls) == 2


async def test_login_empty_break_glass_list_blocks_everyone(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Pusta lista (domyślnie) = zachowanie sprzed zmiany: wszyscy 503.

    Bez listy nie ma czego wyliczać — każdy adres dostaje to samo 503, a ekran
    logowania pokazuje komunikat „Zaloguj się przez Microsoft”.
    """
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


async def test_forgot_password_non_break_glass_gets_generic_answer(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Ta sama odpowiedź dla adresu z listy i spoza niej (pentest 13.11.2026).

    Inaczej 503 vs 200 zdradza adres konta awaryjnego tak samo jak /login.
    """
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    on_list = await app_client.post(
        "/api/auth/forgot-password", json={"email": "admin@x.com"}
    )
    off_list = await app_client.post(
        "/api/auth/forgot-password", json={"email": "other@x.com"}
    )
    assert off_list.status_code == on_list.status_code == 200
    assert off_list.json() == on_list.json()


async def test_forgot_password_non_break_glass_sends_no_mail(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Konto spoza listy przy wyłączonym logowaniu nie dostaje linku resetowego."""
    import app.api.auth as auth_module

    sent: list[str] = []
    monkeypatch.setattr(
        auth_module,
        "send_password_reset_email",
        lambda **kw: sent.append(kw["to_email"]),
    )
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", "admin@x.com")
    resp = await app_client.post(
        "/api/auth/forgot-password",
        json={"email": app_client.headers["X-Test-Admin-Email"]},
    )
    assert resp.status_code == 200
    assert sent == []


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
