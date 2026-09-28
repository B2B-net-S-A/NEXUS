"""Runda 13 audytu — obszar AUTH (podłoga unieważnienia tokenów).

Do tej rundy ``token_is_revoked`` porównywał pełne sekundy
(``int(iat) < int(floor)``), więc token wybity w tej samej sekundzie co
zmiana/reset hasła — PRZED nią — przeżywał unieważnienie. Teraz ``iat``
nowych tokenów niesie mikrosekundy, a porównanie idzie z pełną precyzją.
Token sprzed wdrożenia (``iat`` całkowite) zachowuje dotychczasowe
porównanie po sekundach — wdrożenie nikogo nie wylogowuje.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import app.models  # noqa: F401  (register every mapper)
import pytest
from jose import jwt


def _decode(token: str) -> dict:
    from app.core.security import decode_token

    return decode_token(token)


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


# ── Porównanie z pełną precyzją ─────────────────────────────────────────────


def test_new_format_token_from_the_same_second_before_the_floor_is_revoked() -> None:
    from app.core.security import token_is_revoked

    # Token wybity 0,3 s przed zmianą hasła, w tej samej sekundzie.
    floor = _dt(1_790_000_100.4)
    assert token_is_revoked({"iat": 1_790_000_100.1}, floor)
    # Ułamek zerowy nadal jest nowym formatem (JSON zachowuje „.0”).
    assert token_is_revoked({"iat": 1_790_000_100.0}, floor)


def test_token_after_the_floor_in_the_same_second_stays_valid() -> None:
    from app.core.security import token_is_revoked

    floor = _dt(1_790_000_100.4)
    assert not token_is_revoked({"iat": 1_790_000_100.6}, floor)
    # Ta sama mikrosekunda = token wybity „z” podłogą, nie przed nią.
    assert not token_is_revoked({"iat": floor.timestamp()}, floor)


def test_legacy_integer_iat_keeps_whole_second_semantics() -> None:
    from app.core.security import token_is_revoked

    floor = _dt(1_790_000_100.4)
    # Sesja sprzed wdrożenia: brak podłogi albo podłoga wcześniejsza — ważna.
    assert not token_is_revoked({"iat": 1_790_000_100}, None)
    assert not token_is_revoked({"iat": 1_790_000_100}, _dt(1_790_000_050.9))
    # Ta sama sekunda: stary format nie mówi, czy przed, czy po (np. para
    # z odpowiedzi zmiany hasła) — nie wylogowujemy przy wdrożeniu.
    assert not token_is_revoked({"iat": 1_790_000_100}, floor)
    # Wcześniejsza sekunda — unieważniony jak dotąd.
    assert token_is_revoked({"iat": 1_790_000_099}, floor)


def test_garbage_iat_under_a_floor_is_revoked() -> None:
    from app.core.security import token_is_revoked

    floor = _dt(1_790_000_100.4)
    assert token_is_revoked({}, floor)
    assert token_is_revoked({"iat": "nie-liczba"}, floor)
    assert token_is_revoked({"iat": None}, floor)


def test_naive_floor_is_read_as_utc() -> None:
    from app.core.security import token_is_revoked

    naive = datetime(2026, 9, 28, 10, 0, 0, 400_000)
    aware = naive.replace(tzinfo=timezone.utc)
    assert token_is_revoked({"iat": aware.timestamp() - 0.2}, naive)
    assert not token_is_revoked({"iat": aware.timestamp() + 0.2}, naive)


# ── Wybijanie tokenów ───────────────────────────────────────────────────────


def test_new_tokens_carry_a_fractional_iat_that_decodes() -> None:
    from app.core.security import create_access_token, create_refresh_token

    access = _decode(create_access_token(1, "recruiter"))
    refresh = _decode(create_refresh_token(1))
    for payload in (access, refresh):
        assert isinstance(payload["iat"], float)
        # Mikrosekundy, nie więcej — iat ma się dać porównać dokładnie.
        assert round(payload["iat"], 6) == payload["iat"]
        assert payload["exp"] > payload["iat"]


def test_token_minted_just_before_the_floor_is_revoked() -> None:
    from app.core.security import create_access_token, token_is_revoked

    payload = _decode(create_access_token(1, "recruiter"))
    issued = _dt(payload["iat"])
    assert token_is_revoked(payload, issued + timedelta(microseconds=1))
    assert not token_is_revoked(payload, issued)


def test_token_minted_after_the_floor_in_the_same_second_is_valid() -> None:
    from app.core.security import create_refresh_token, token_is_revoked

    floor = datetime.now(timezone.utc)
    payload = _decode(create_refresh_token(1))
    assert not token_is_revoked(payload, floor)


# ── Ścieżki ustawiające podłogę ─────────────────────────────────────────────


class _FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


def _user(**overrides):
    from app.core.security import hash_password
    from app.models.user import UserRole

    base = dict(
        id=42,
        email="r13-auth@example.com",
        name="R13",
        role=UserRole.recruiter,
        password_hash=hash_password("stare-haslo-123"),
        force_password_change=False,
        force_password_change_at=None,
        tokens_valid_after=None,
        authorization_version=1,
        effective_section_access=None,
        get_all_roles=lambda: [UserRole.recruiter],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_change_password_revokes_the_old_token_and_keeps_the_new_pair(
    monkeypatch,
) -> None:
    from app.api import auth
    from app.core.security import create_access_token, token_is_revoked

    async def _no_sections(_db, user):
        user.effective_section_access = {}

    monkeypatch.setattr(auth, "resolve_effective_section_access", _no_sections)
    monkeypatch.setattr(auth, "send_password_changed_notification", lambda **_: None)

    stale = _decode(create_access_token(42, "recruiter"))
    user = _user()
    handler = inspect.unwrap(auth.change_password)
    result = await handler(
        request=SimpleNamespace(client=None, state=SimpleNamespace()),
        data=auth.ChangePasswordRequest(
            current_password="stare-haslo-123", new_password="nowe-haslo-456"
        ),
        current_user=user,
        db=_FakeDb(),
    )

    floor = user.tokens_valid_after
    assert isinstance(floor, datetime)
    assert token_is_revoked(stale, floor)
    assert not token_is_revoked(_decode(result.access_token), floor)
    assert not token_is_revoked(_decode(result.refresh_token), floor)


@pytest.mark.asyncio
async def test_reset_via_link_sets_an_app_clock_floor_that_revokes_same_second(
    monkeypatch,
) -> None:
    from app.api import auth
    from app.core.config import settings
    from app.core.security import create_access_token, token_is_revoked

    user = _user()

    async def _consume(_db, _token):
        return user

    monkeypatch.setattr(auth, "verify_and_consume_token", _consume)
    monkeypatch.setattr(auth, "send_password_changed_notification", lambda **_: None)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", True)

    stale = _decode(create_access_token(42, "recruiter"))
    handler = inspect.unwrap(auth.reset_password_with_token)
    await handler(
        request=SimpleNamespace(client=None),
        data=auth.ResetPasswordTokenRequest(
            token="a" * 64, new_password="nowe-haslo-456"
        ),
        db=_FakeDb(),
    )

    # Podłoga z zegara aplikacji (ten sam, którym wybijamy ``iat``), nie
    # ``func.now()`` z początku transakcji w bazie.
    floor = user.tokens_valid_after
    assert isinstance(floor, datetime)
    assert token_is_revoked(stale, floor)
    fresh = _decode(create_access_token(42, "recruiter"))
    assert not token_is_revoked(fresh, floor)


def test_decoded_fractional_iat_passes_jose_validation() -> None:
    from app.core.config import settings
    from app.core.security import ALGORITHM, decode_token

    now = datetime.now(timezone.utc).timestamp()
    token = jwt.encode(
        {"sub": "1", "type": "access", "iat": now, "exp": now + 60},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    assert decode_token(token)["iat"] == now
