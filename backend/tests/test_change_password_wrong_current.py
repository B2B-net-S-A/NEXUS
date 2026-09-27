"""R10-N15-2: złe aktualne hasło przy zmianie hasła to 400, nie 401.

Front (``lib/api.ts``) traktuje każde 401 jako wygasłą sesję: czyści
sesję i kieruje na ``/login?reason=session_expired``. Endpoint zwracał 401
przy literówce w polu „Aktualne hasło”, więc użytkownik — także ten
z wymuszoną zmianą hasła po resecie admina — był wylogowywany, zamiast
zobaczyć komunikat. Test woła handler bez bazy i limitera.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import auth
from app.core.security import hash_password


class _NoDb:
    def add(self, *_a, **_k):  # pragma: no cover - nie powinno dojść do zapisu
        raise AssertionError("złe hasło nie może niczego zapisać")

    async def commit(self):  # pragma: no cover
        raise AssertionError("złe hasło nie może niczego zapisać")


@pytest.mark.asyncio
async def test_wrong_current_password_is_400_with_polish_detail():
    handler = inspect.unwrap(auth.change_password)
    user = SimpleNamespace(id=1, password_hash=hash_password("dobre-haslo-123"))
    with pytest.raises(HTTPException) as exc:
        await handler(
            request=None,
            data=auth.ChangePasswordRequest(
                current_password="zle-haslo-xxx", new_password="nowe-haslo-456"
            ),
            current_user=user,
            db=_NoDb(),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == auth.WRONG_CURRENT_PASSWORD_DETAIL


@pytest.mark.asyncio
async def test_identical_new_password_detail_is_polish():
    handler = inspect.unwrap(auth.change_password)
    user = SimpleNamespace(id=1, password_hash=hash_password("dobre-haslo-123"))
    with pytest.raises(HTTPException) as exc:
        await handler(
            request=None,
            data=auth.ChangePasswordRequest(
                current_password="dobre-haslo-123", new_password="dobre-haslo-123"
            ),
            current_user=user,
            db=_NoDb(),
        )
    assert exc.value.status_code == 400
    assert "Nowe hasło" in exc.value.detail
