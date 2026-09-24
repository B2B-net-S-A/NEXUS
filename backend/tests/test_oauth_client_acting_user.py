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


def _request(method: str = "GET", path: str = "/api/unmapped", scope=None):
    return SimpleNamespace(
        method=method,
        state=SimpleNamespace(),
        url=SimpleNamespace(path=path),
        scope=scope or {},
    )


_ALL_TEST_SCOPES = ["candidate:read", "candidate:write", "job:read", "job:write"]


def _client(**overrides):
    base = dict(
        client_id="abc123",
        enabled=True,
        acting_user_id=42,
        scopes=list(_ALL_TEST_SCOPES),
    )
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
    "oauth_client, user",
    [
        (None, None),  # nieznany client_id
        (_client(enabled=False), _user()),  # kill-switch
        (_client(acting_user_id=None), None),  # klient bez usera serwisowego
        (_client(), None),  # user usunięty (FK SET NULL nie zdążył / race)
        (_client(), _user(is_active=False)),  # user zdezaktywowany
    ],
)
async def test_unusable_client_is_401_like_a_bad_token(oauth_client, user):
    db = _FakeDb(oauth_client, user)

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


# ── Zakres zależny od trasy (audyt 22.09.2026, AUTH-01) i cofnięte scope'y ──
#
# Prawdziwe obiekty tras aplikacji, żeby test widział to, co widzi żądanie:
# od FastAPI 0.139 ``scope["route"].path`` NIE ma prefiksu z include_router,
# więc pełny szablon musi złożyć ``route_template``.


def _routes_by_template() -> dict[str, tuple[object, object]]:
    from app.main import app

    from tests._route_introspection import iter_api_routes

    return {path: (app, route) for path, route in iter_api_routes(app)}


def _routed_request(method: str, template: str, concrete_path: str):
    app, route = _routes_by_template()[template]
    return _request(method, concrete_path, scope={"route": route, "app": app})


def test_every_mapped_template_is_a_registered_route():
    from app.services.oauth_route_scopes import OAUTH_ROUTE_RESOURCES

    registered = set(_routes_by_template())
    missing = sorted(set(OAUTH_ROUTE_RESOURCES) - registered)
    assert not missing, f"Mapa tras OAuth wskazuje nieistniejące trasy: {missing}"


def test_route_template_restores_the_include_router_prefix():
    from app.services.oauth_route_scopes import route_template

    request = _routed_request(
        "GET", "/api/jobs/{job_id}/assignable-stages", "/api/jobs/7/assignable-stages"
    )
    # Sama trasa zna tylko ścieżkę bez prefiksu ``/api``.
    assert not request.scope["route"].path.startswith("/api/")
    assert route_template(request) == "/api/jobs/{job_id}/assignable-stages"


@pytest.fixture
def enforce(monkeypatch):
    from app.api import deps

    monkeypatch.setattr(deps.settings, "OAUTH_ROUTE_SCOPES_ENFORCE", True)


async def test_enforced_wrong_resource_is_403_insufficient_scope(enforce):
    db = _FakeDb(_client(), _user())
    request = _routed_request(
        "GET", "/api/jobs/{job_id}/assignable-stages", "/api/jobs/7/assignable-stages"
    )

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(request, _payload(scope="candidate:read"), db)

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "insufficient_scope"
    assert exc.value.detail["required_any"] == ["job:read"]


async def test_enforced_unmapped_route_is_403_not_exposed(enforce):
    db = _FakeDb(_client(), _user())
    request = _routed_request(
        "GET", "/api/candidates/{candidate_id}", "/api/candidates/5"
    )

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(request, _payload(), db)

    assert exc.value.status_code == 403
    assert exc.value.detail == "route_not_exposed_to_clients"


async def test_shadow_mode_allows_unmapped_route_and_logs_the_would_be_denial(
    caplog,
):
    user = _user()
    db = _FakeDb(_client(), user)
    request = _routed_request(
        "GET", "/api/candidates/{candidate_id}", "/api/candidates/5"
    )

    with caplog.at_level("WARNING", logger="app.api.deps"):
        resolved = await _resolve_client_principal(request, _payload(), db)

    assert resolved is user
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "would_deny" in m
        and "abc123" in m
        and "/api/candidates/{candidate_id}" in m
        and "route_not_exposed_to_clients" in m
        for m in messages
    ), messages


async def test_shadow_mode_is_silent_when_the_route_would_be_allowed(caplog):
    db = _FakeDb(_client(), _user())
    request = _routed_request(
        "POST", "/api/jobs/{job_id}/proposals/bulk", "/api/jobs/7/proposals/bulk"
    )

    with caplog.at_level("WARNING", logger="app.api.deps"):
        await _resolve_client_principal(request, _payload(), db)

    assert not [r for r in caplog.records if "oauth route scope" in r.getMessage()]


@pytest.mark.parametrize("scope", ["candidate:write", "job:write"])
async def test_enforced_proposals_bulk_accepts_either_write_scope(enforce, scope):
    user = _user()
    db = _FakeDb(_client(), user)
    request = _routed_request(
        "POST", "/api/jobs/{job_id}/proposals/bulk", "/api/jobs/7/proposals/bulk"
    )

    assert await _resolve_client_principal(request, _payload(scope=scope), db) is user


async def test_enforced_check_duplicates_is_a_read_and_passes_with_candidate_read(
    enforce,
):
    user = _user()
    db = _FakeDb(_client(), user)
    request = _routed_request(
        "POST",
        "/api/candidates/check-duplicates",
        "/api/candidates/check-duplicates",
    )

    resolved = await _resolve_client_principal(
        request, _payload(scope="candidate:read"), db
    )

    assert resolved is user


async def test_enforced_write_route_rejects_a_read_only_token(enforce):
    db = _FakeDb(_client(), _user())
    request = _routed_request(
        "POST", "/api/candidates/from-cv", "/api/candidates/from-cv"
    )

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(
            request, _payload(scope="candidate:read job:read"), db
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "insufficient_scope"


async def test_read_only_post_outside_the_map_is_403_even_in_shadow_mode():
    """FIX-01: #1700 przepuścił eksport z samym ``candidate:read``."""
    db = _FakeDb(_client(), _user())
    request = _routed_request(
        "POST", "/api/candidates/export", "/api/candidates/export"
    )

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(request, _payload(scope="candidate:read"), db)

    assert exc.value.status_code == 403
    assert exc.value.detail == "route_not_exposed_to_clients"


async def test_mapped_read_only_post_still_passes_in_shadow_mode():
    user = _user()
    db = _FakeDb(_client(), user)
    request = _routed_request(
        "POST",
        "/api/candidates/check-duplicates",
        "/api/candidates/check-duplicates",
    )

    resolved = await _resolve_client_principal(
        request, _payload(scope="candidate:read"), db
    )

    assert resolved is user


@pytest.mark.parametrize(
    ("method", "template", "concrete"),
    [
        ("POST", "/api/candidates/{candidate_id}/cv", "/api/candidates/5/cv"),
        ("POST", "/api/candidates/{candidate_id}/sources", "/api/candidates/5/sources"),
        (
            "GET",
            "/api/candidates/{candidate_id}/recommendations",
            "/api/candidates/5/recommendations",
        ),
    ],
)
async def test_enforced_jjit_routes_pass_with_candidate_write(
    enforce, method, template, concrete
):
    """FIX-02: importer JJIT nie może stanąć po włączeniu egzekwowania."""
    user = _user()
    db = _FakeDb(_client(), user)
    request = _routed_request(method, template, concrete)

    resolved = await _resolve_client_principal(
        request, _payload(scope="candidate:write"), db
    )

    assert resolved is user


async def test_scope_revoked_on_the_client_stops_an_already_issued_token():
    """AUTH-02: token z ``candidate:write`` po odebraniu scope'u klientowi."""

    db = _FakeDb(_client(scopes=["candidate:read"]), _user())

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(
            _request("POST"), _payload(scope="candidate:write job:write"), db
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "insufficient_scope"
    assert exc.value.detail["granted"] == []


async def test_client_with_all_scopes_removed_cannot_even_read():
    db = _FakeDb(_client(scopes=[]), _user())

    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(_request("GET"), _payload(), db)

    assert exc.value.status_code == 403


# ── ``require_scope`` (ATLAS, ścieżka B) ────────────────────────────────────


def _client_token(scopes: list[str], client_id: str = "abc123"):
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api.oauth_token import _create_client_token

    token = _create_client_token(SimpleNamespace(client_id=client_id), scopes)
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_require_scope_passes_for_an_enabled_client_with_the_scope():
    from app.api.oauth_token import require_scope
    from app.models.oauth_client import OAuthScope

    dep = require_scope(OAuthScope.candidate_read)
    principal = await dep(
        creds=_client_token(["candidate:read"]),
        db=_FakeDb(_client(scopes=["candidate:read"])),
    )

    assert principal.client_id == "abc123"
    assert principal.scopes == ["candidate:read"]


@pytest.mark.parametrize("oauth_client", [None, _client(enabled=False)])
async def test_require_scope_rejects_unknown_or_disabled_client_with_401(oauth_client):
    from app.api.oauth_token import require_scope
    from app.models.oauth_client import OAuthScope

    dep = require_scope(OAuthScope.candidate_read)
    with pytest.raises(HTTPException) as exc:
        await dep(creds=_client_token(["candidate:read"]), db=_FakeDb(oauth_client))

    assert exc.value.status_code == 401


async def test_require_scope_intersects_the_token_with_current_client_scopes():
    from app.api.oauth_token import require_scope
    from app.models.oauth_client import OAuthScope

    dep = require_scope(OAuthScope.candidate_read)
    with pytest.raises(HTTPException) as exc:
        await dep(
            creds=_client_token(["candidate:read"]),
            db=_FakeDb(_client(scopes=["job:read"])),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["missing"] == ["candidate:read"]


# ── Wymuszona zmiana hasła (AUTH-03) i konto bez hasła (AUTH-04) ────────────


def test_fpc_token_state_blocks_domain_access():
    from app.api.deps import ensure_password_change_not_required

    request = _request()
    request.state.password_change_required = True

    with pytest.raises(HTTPException) as exc:
        ensure_password_change_not_required(request)

    assert exc.value.status_code == 403
    assert exc.value.detail == "password_change_required"


def test_regular_token_state_passes_the_password_change_gate():
    from app.api.deps import ensure_password_change_not_required

    ensure_password_change_not_required(_request())  # brak flagi = przechodzi


@pytest.mark.parametrize("hashed", [None, "", "!imported-from-traffit-no-login!"])
def test_verify_password_without_a_bcrypt_hash_is_false(hashed):
    from app.core.security import has_usable_password, verify_password

    assert verify_password("cokolwiek", hashed) is False
    assert has_usable_password(hashed) is False


def test_has_usable_password_for_a_real_hash():
    from app.core.security import (
        has_usable_password,
        hash_password,
        verify_password,
    )

    hashed = hash_password("Haslo123!")
    assert has_usable_password(hashed) is True
    assert verify_password("Haslo123!", hashed) is True


# ── Klient nie działa jako administrator (audyt bezpieczeństwa 24.09.2026) ──


class _ScalarDb:
    def __init__(self, value):
        self._value = value

    async def scalar(self, _stmt):
        return self._value


@pytest.mark.asyncio
async def test_acting_user_cannot_be_an_admin():
    from app.api.oauth_clients import _validate_acting_user
    from app.models.user import UserRole

    admin = SimpleNamespace(
        is_active=True, has_role=lambda role: role == UserRole.admin
    )
    with pytest.raises(HTTPException) as exc:
        await _validate_acting_user(_ScalarDb(admin), 7)
    assert exc.value.status_code == 422
    assert "administrator" in exc.value.detail


@pytest.mark.asyncio
async def test_operational_acting_user_is_accepted():
    from app.api.oauth_clients import _validate_acting_user

    recruiter = SimpleNamespace(is_active=True, has_role=lambda role: False)
    await _validate_acting_user(_ScalarDb(recruiter), 7)
