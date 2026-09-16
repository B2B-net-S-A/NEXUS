"""OAuth client_credentials → „acting user" w ``get_authenticated_user``.

Kontrakt (migracja 0197, ``app/api/deps.py::_resolve_client_principal``):

* token ``type="client"`` jest rozwiązywany do usera z ``OAuthClient.acting_user_id``,
* klient wyłączony / bez usera / z nieaktywnym userem → 401 (jak zły token),
* mutacja bez żadnego scope'u ``*:write`` → 403 ``insufficient_scope``,
* odczyt wymaga dowolnego scope'u,
* nagłówek impersonacji jest dla klienta ignorowany (nie można „podglądać jako").

Testy nie dotykają bazy: ``db.execute`` jest atrapą zwracającą kolejno klienta
i usera, więc czerwienieją po cofnięciu konkretnej linii, nie po padnięciu
infrastruktury.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.deps import _resolve_client_principal


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    """Zwraca przygotowane wyniki w kolejności wywołań ``execute``."""

    def __init__(self, *results):
        self._results = list(results)
        self.calls = 0

    async def execute(self, _stmt):
        self.calls += 1
        return _Result(self._results.pop(0) if self._results else None)


def _request(method: str = "GET"):
    return SimpleNamespace(method=method, state=SimpleNamespace())


def _client(**overrides):
    base = dict(client_id="abc123", enabled=True, acting_user_id=42)
    base.update(overrides)
    return SimpleNamespace(**base)


def _user(**overrides):
    base = dict(id=42, is_active=True)
    base.update(overrides)
    return SimpleNamespace(**base)


def _payload(scope: str = "candidate:write job:write", sub: str = "abc123"):
    return {"sub": sub, "type": "client", "scope": scope}


async def test_client_token_resolves_to_acting_user_and_stamps_request():
    request = _request("POST")
    user = _user()
    db = _FakeDb(_client(), user)

    resolved = await _resolve_client_principal(request, _payload(), db)

    assert resolved is user
    assert request.state.oauth_client_id == "abc123"
    assert db.calls == 2


@pytest.mark.parametrize(
    "client, user",
    [
        (None, None),  # nieznany client_id
        (_client(enabled=False), _user()),  # kill-switch
        (_client(acting_user_id=None), None),  # klient bez usera serwisowego
        (_client(), None),  # user usunięty (FK SET NULL nie zdążył / race)
        (_client(), _user(is_active=False)),  # user zdezaktywowany
    ],
)
async def test_unusable_client_is_401_like_a_bad_token(client, user):
    db = _FakeDb(client, user)

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(_request(), _payload(), db)

    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


async def test_missing_sub_is_401_without_touching_db():
    db = _FakeDb()

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(_request(), _payload(sub=""), db)

    assert exc.value.status_code == 401
    assert db.calls == 0


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_mutation_without_write_scope_is_403(method):
    db = _FakeDb(_client(), _user())

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(
            _request(method), _payload(scope="candidate:read job:read"), db
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "insufficient_scope"
    assert exc.value.detail["method"] == method


async def test_read_with_read_only_scope_is_allowed():
    user = _user()
    db = _FakeDb(_client(), user)

    resolved = await _resolve_client_principal(
        _request("GET"), _payload(scope="candidate:read"), db
    )

    assert resolved is user


async def test_token_without_any_scope_is_403_even_for_read():
    db = _FakeDb(_client(), _user())

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(_request("GET"), _payload(scope=""), db)

    assert exc.value.status_code == 403
