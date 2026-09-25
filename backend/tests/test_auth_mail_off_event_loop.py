"""Wysyłka maili z handlerów auth/admin nie blokuje pętli zdarzeń (audyt 25.09.2026).

`send_*` → `services.email.send_email` → Graph app-only (MSAL
`acquire_token_for_client` + `httpx.post`) albo `smtplib` — wszystko
synchroniczne. Wołane wprost z handlera `async` zatrzymywało CAŁY backend
(jeden uvicorn) na czas połączenia z Graphem/SMTP. Teraz idzie przez
`asyncio.to_thread`, a w adminie dopiero PO commicie — wiersz użytkownika jest
tam zablokowany `FOR UPDATE`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.api.admin as admin_api

_BACKEND = Path(__file__).resolve().parents[1]
_SENDERS = {
    "send_email_verification_email",
    "send_password_changed_notification",
    "send_password_reset_email",
    "send_email",
}


@pytest.mark.parametrize("module", ["app/api/auth.py", "app/api/admin.py"])
def test_async_handlers_never_call_mail_senders_directly(module: str) -> None:
    tree = ast.parse((_BACKEND / module).read_text(encoding="utf-8"))
    offenders: list[tuple[str, int]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _SENDERS
            ):
                offenders.append((fn.name, node.lineno))
    assert offenders == [], (
        f"{module}: synchroniczna wysyłka maila w handlerze async {offenders} — "
        "użyj `await asyncio.to_thread(...)`"
    )


class _Result:
    def __init__(self, user) -> None:
        self._user = user

    def scalar_one_or_none(self):
        return self._user


class _FakeDB:
    def __init__(self, user, events: list[str]) -> None:
        self._user = user
        self.events = events

    async def execute(self, *a, **k):
        return _Result(self._user)

    def add(self, obj) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.events.append("commit")


@pytest.mark.asyncio
async def test_admin_reset_sends_mail_after_commit_in_thread(monkeypatch) -> None:
    events: list[str] = []
    user = SimpleNamespace(
        id=7,
        email="osoba@example.com",
        name="Osoba",
        password_hash=None,
        force_password_change=False,
        force_password_change_at=None,
        tokens_valid_after=None,
    )
    admin = SimpleNamespace(id=1, email="admin@example.com", name="Admin")

    async def _to_thread(fn, *args, **kwargs):
        events.append(f"thread:{fn.__name__}")
        return True

    monkeypatch.setattr(admin_api.asyncio, "to_thread", _to_thread)
    monkeypatch.setattr(admin_api, "hash_password", lambda pw: "hash")

    def _send_password_changed_notification(**kw):
        raise AssertionError("wysyłka poza wątkiem")

    monkeypatch.setattr(
        admin_api,
        "send_password_changed_notification",
        _send_password_changed_notification,
    )

    await admin_api.reset_password(
        user_id=7,
        data=SimpleNamespace(new_password="NoweHaslo123!"),
        _admin=admin,
        db=_FakeDB(user, events),
    )

    assert events == ["commit", "thread:_send_password_changed_notification"]
