"""Maile z publicznych tras auth idą po odpowiedzi (audyt r3, 24.11.2026).

„Nie pamiętam hasła” odpowiadał od razu adresowi spoza listy kont awaryjnych,
a adresowi z listy dopiero po połączeniu z Graphem/SMTP — czas odpowiedzi
różnicował adresy mimo tej samej treści. To samo przy ponownym wysłaniu linku
aktywacyjnego i przy rejestracji na zajęty adres. Teraz token i ślad
w ``Activity`` powstają w żądaniu, a wysyłka biegnie w ``BackgroundTasks``;
błąd wysyłki trafia do logu. Bez bazy — sesja i serwisy są podstawione.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

import app.api.auth as auth
from app.core.config import settings
from app.models.activity import Activity

ON_LIST = "awaryjny@example.com"


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass


def _user(**extra) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        email=ON_LIST,
        name="Konto Testowe",
        is_active=True,
        email_verified=False,
        **extra,
    )


def _request() -> SimpleNamespace:
    return SimpleNamespace(client=None, state=SimpleNamespace())


@pytest.fixture
def services(monkeypatch):
    """Podstawione serwisy tokenów i lookup konta."""
    sent: list[tuple[str, str]] = []
    user = _user()

    async def _find(db, email):
        return user if email.strip().lower() == ON_LIST else None

    async def _token(db, user_id, requested_ip=None):
        return "token-testowy"

    async def _noop(db):
        return 0

    def _reset(**kw):
        sent.append(("reset", kw["to_email"]))
        return True

    def _verify(**kw):
        sent.append(("verify", kw["to_email"]))
        return True

    monkeypatch.setattr(auth, "find_user_by_email", _find)
    monkeypatch.setattr(auth, "create_reset_token", _token)
    monkeypatch.setattr(auth, "create_verification_token", _token)
    monkeypatch.setattr(auth, "cleanup_expired_tokens", _noop)
    monkeypatch.setattr(auth, "cleanup_expired_verification_tokens", _noop)
    monkeypatch.setattr(auth, "send_password_reset_email", _reset)
    monkeypatch.setattr(auth, "send_email_verification_email", _verify)
    monkeypatch.setattr(auth, "hash_password", lambda pw: "hash")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://nexus.example.com")
    return SimpleNamespace(sent=sent, user=user)


def _actions(db: _FakeDB) -> list[str]:
    return [a.action for a in db.added if isinstance(a, Activity)]


@pytest.mark.asyncio
async def test_forgot_password_on_break_glass_list_mails_after_response(
    services, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_BREAK_GLASS_EMAILS", ON_LIST)
    db, tasks = _FakeDB(), BackgroundTasks()

    handler = inspect.unwrap(auth.forgot_password)
    body = await handler(
        request=_request(),
        data=SimpleNamespace(email=ON_LIST),
        background_tasks=tasks,
        db=db,
    )

    # Odpowiedź gotowa, zanim cokolwiek poszło do Graphu/SMTP.
    assert body == {"detail": auth._FORGOT_GENERIC_DETAIL}
    assert services.sent == []
    assert _actions(db) == ["password_reset_requested"]
    assert len(tasks.tasks) == 1

    await tasks()
    assert services.sent == [("reset", ON_LIST)]


@pytest.mark.asyncio
async def test_forgot_password_mail_failure_is_logged(
    services, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", True)

    def _broken(**kw):
        raise RuntimeError("smtp: connection refused")

    monkeypatch.setattr(auth, "send_password_reset_email", _broken)
    tasks = BackgroundTasks()
    handler = inspect.unwrap(auth.forgot_password)
    await handler(
        request=_request(),
        data=SimpleNamespace(email=ON_LIST),
        background_tasks=tasks,
        db=_FakeDB(),
    )

    with caplog.at_level(logging.ERROR, logger=auth.logger.name):
        await tasks()
    failures = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(failures) == 1
    assert "password_reset" in failures[0].getMessage()
    assert "user_id=42" in failures[0].getMessage()
    assert failures[0].exc_info is not None


@pytest.mark.asyncio
async def test_forgot_password_refused_send_is_logged(
    services, monkeypatch, caplog
) -> None:
    """Nadawca zwraca ``False`` (kanał wyłączony, odmowa) — też ślad w logu."""
    monkeypatch.setattr(settings, "PASSWORD_LOGIN_ENABLED", True)
    monkeypatch.setattr(auth, "send_password_reset_email", lambda **kw: False)
    tasks = BackgroundTasks()
    handler = inspect.unwrap(auth.forgot_password)
    await handler(
        request=_request(),
        data=SimpleNamespace(email=ON_LIST),
        background_tasks=tasks,
        db=_FakeDB(),
    )

    with caplog.at_level(logging.WARNING, logger=auth.logger.name):
        await tasks()
    assert any(
        r.levelno == logging.WARNING and "password_reset" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_resend_verification_mails_after_response(services) -> None:
    db, tasks = _FakeDB(), BackgroundTasks()
    handler = inspect.unwrap(auth.resend_verification)
    body = await handler(
        request=_request(),
        data=SimpleNamespace(email=ON_LIST),
        background_tasks=tasks,
        db=db,
    )

    assert body == {"detail": auth._RESEND_GENERIC_DETAIL}
    assert services.sent == []
    assert _actions(db) == ["email_verification_resent"]
    await tasks()
    assert services.sent == [("verify", ON_LIST)]


@pytest.mark.asyncio
async def test_register_duplicate_and_new_account_both_mail_after_response(
    services, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SELF_REGISTRATION_ENABLED", True)
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "example.com")
    handler = inspect.unwrap(auth.register)

    # Zajęty, niepotwierdzony adres: nowy link, ale dopiero po odpowiedzi.
    db, tasks = _FakeDB(), BackgroundTasks()
    await handler(
        request=_request(),
        data=SimpleNamespace(email=ON_LIST, password="Haslo-Testowe-123", name="X"),
        background_tasks=tasks,
        db=db,
    )
    assert services.sent == []
    assert _actions(db) == ["email_verification_resent"]
    await tasks()
    assert services.sent == [("verify", ON_LIST)]

    # Nowe konto czeka tak samo — inaczej czas odróżniałby oba przypadki.
    services.sent.clear()
    new_email = "nowe-konto@example.com"
    db, tasks = _FakeDB(), BackgroundTasks()

    async def _flush_assigns_id() -> None:
        for obj in db.added:
            if getattr(obj, "email", None) == new_email and obj.id is None:
                obj.id = 43

    db.flush = _flush_assigns_id
    await handler(
        request=_request(),
        data=SimpleNamespace(email=new_email, password="Haslo-Testowe-123", name="Y"),
        background_tasks=tasks,
        db=db,
    )
    assert services.sent == []
    assert _actions(db) == ["self_registered"]
    await tasks()
    assert services.sent == [("verify", new_email)]
