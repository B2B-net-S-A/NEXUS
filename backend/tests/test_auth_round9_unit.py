"""Runda 9 audytu — uwierzytelnianie, testy bez bazy.

- R9-N9-6: porównanie sekretów ze znakiem spoza ASCII = odmowa, nie 500.
- R9-N9-10: bcrypt nie biegnie na pętli zdarzeń (AST: każde wywołanie
  ``verify_password``/``hash_password`` w handlerach idzie przez ``to_thread``).
- R9-N9-1: klient OAuth, którego konto integracji dostało rolę admina, 401.
- R9-N1-4: ``state`` SSO bez weryfikatora PKCE, związany z przeglądarką.
- R9-N13-2: ostatnia jawna decyzja admina o aktywności konta.
"""

from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import JWTError
from jose import jwt as jose_jwt

from app.core.security import secrets_equal

APP = Path(__file__).resolve().parents[1] / "app"


# ── R9-N9-6 ──────────────────────────────────────────────────────────────────


def test_secrets_equal_handles_non_ascii_without_type_error():
    assert secrets_equal("tajny-token", "tajny-token") is True
    assert secrets_equal("tajny-tokeń", "tajny-token") is False
    assert secrets_equal("żółw", "żółw") is True
    assert secrets_equal(None, "x") is False
    assert secrets_equal("x", None) is False
    # Samotny surogat z JSON-a nie da się zakodować — zły sekret, nie wyjątek.
    assert secrets_equal("\ud800", "x") is False


def test_cloudtalk_signature_with_non_ascii_header_is_rejected_not_raised():
    from app.services.cloudtalk.webhook_verify import verify_signature

    assert verify_signature(b"{}", "sha256=złe", "sekret") is False


def test_compare_digest_on_str_is_gone_from_auth_surfaces():
    for rel in (
        "api/admin_snapshot.py",
        "api/microsoft365.py",
        "services/cloudtalk/webhook_verify.py",
    ):
        tree = ast.parse((APP / rel).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "compare_digest"
            ):
                # Dozwolone wyłącznie na bajtach (``.encode(...)``).
                for arg in node.args:
                    assert (
                        isinstance(arg, ast.Call)
                        and isinstance(arg.func, ast.Attribute)
                        and arg.func.attr == "encode"
                    ) or (isinstance(arg, ast.Name) and arg.id == "presented"), (
                        rel,
                        ast.unparse(node),
                    )


@pytest.mark.asyncio
async def test_snapshot_token_with_non_ascii_is_401(monkeypatch):
    from app.api import admin_snapshot
    from app.core.config import settings

    monkeypatch.setattr(settings, "SNAPSHOT_TOKEN", "poprawny-token")
    request = SimpleNamespace(headers={})
    with pytest.raises(HTTPException) as exc:
        await admin_snapshot._snapshot_auth(
            request, x_snapshot_token="złóż-token", bearer=None, db=None
        )
    assert exc.value.status_code == 401


# ── R9-N9-10 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rel",
    ["api/auth.py", "api/admin.py", "api/oauth_token.py", "api/oauth_clients.py"],
)
def test_bcrypt_runs_in_a_thread(rel):
    tree = ast.parse((APP / rel).read_text())
    offenders = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"verify_password", "hash_password"}
    ]
    assert offenders == [], f"{rel}: bcrypt na pętli zdarzeń: {offenders}"


# ── R9-N9-1 ──────────────────────────────────────────────────────────────────


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    def __init__(self, *values):
        self._values = list(values)

    async def execute(self, _stmt):
        return _Result(self._values.pop(0))


def _acting_user(roles):
    from app.models.user import User, UserRole

    user = User(
        id=7,
        email="integracja@example.com",
        name="Integracja",
        role=UserRole(roles[0]),
        roles=list(roles),
        is_active=True,
    )
    return user


@pytest.mark.asyncio
async def test_oauth_client_acting_as_admin_is_refused():
    from app.api.deps import _resolve_client_principal

    client = SimpleNamespace(
        client_id="cli-1", enabled=True, acting_user_id=7, scopes=["candidate:write"]
    )
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/candidates"),
        state=SimpleNamespace(),
    )
    db = _FakeDb(client, _acting_user(["recruiter", "admin"]))
    with pytest.raises(HTTPException) as exc:
        await _resolve_client_principal(
            request, {"sub": "cli-1", "scope": "candidate:write"}, db
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_jjit_mint_refuses_admin_acting_user(monkeypatch):
    from app.services.integrations.jjit import nexus_client

    client = SimpleNamespace(
        name="jjit",
        client_id="cli-jjit",
        enabled=True,
        acting_user_id=7,
        scopes=["candidate:write"],
    )
    user = _acting_user(["admin"])

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def scalar(self, _stmt):
            return client

        async def get(self, _model, _pk):
            return user

    monkeypatch.setattr(nexus_client, "AsyncSessionLocal", lambda: _Session())

    async def _pick(_db):
        return client

    monkeypatch.setattr(nexus_client, "_pick_oauth_client", _pick)
    with pytest.raises(nexus_client.NexusClientError, match="admina"):
        await nexus_client.mint_client_token()

    user.roles = ["recruiter"]
    from app.models.user import UserRole

    user.role = UserRole.recruiter
    assert await nexus_client.mint_client_token()


# ── R9-N1-4 ──────────────────────────────────────────────────────────────────


def test_login_state_carries_no_pkce_verifier_and_binds_browser():
    from app.api import auth_microsoft as ms

    binding = ms._browser_binding("sekret-karty")
    state = ms._sign_login_state(binding)
    claims = jose_jwt.get_unverified_claims(state)
    assert "pkce" not in claims
    parsed = ms._verify_login_state(state)
    assert parsed.browser_binding == binding
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", parsed.pkce_verifier)
    assert parsed.pkce_verifier not in state
    # Ten sam state → ten sam weryfikator (serwer odtwarza go przy callbacku).
    assert ms._verify_login_state(state).pkce_verifier == parsed.pkce_verifier


def test_legacy_state_with_plain_pkce_is_rejected():
    from app.api import auth_microsoft as ms

    now = datetime.now(timezone.utc)
    legacy = jose_jwt.encode(
        {
            "pkce": "v" * 64,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "purpose": "sso_login",
        },
        ms._state_signing_key(),
        algorithm="HS256",
    )
    with pytest.raises(JWTError):
        ms._verify_login_state(legacy)


def test_exchange_key_depends_on_browser_nonce():
    from app.api import auth_microsoft as ms

    a = ms._bound_exchange_code("kod", ms._browser_binding("karta-a"))
    b = ms._bound_exchange_code("kod", ms._browser_binding("karta-b"))
    assert a != b
    assert len(a) == 64


# ── R9-N13-2 ─────────────────────────────────────────────────────────────────


class _ScalarDb:
    def __init__(self, value):
        self._value = value

    async def scalar(self, _stmt):
        return self._value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("activity", "expected"),
    [
        (None, None),
        (SimpleNamespace(action="user_deactivated", details={}), False),
        (SimpleNamespace(action="active_changed", details={"to": False}), False),
        (SimpleNamespace(action="active_changed", details={"to": True}), True),
        (SimpleNamespace(action="active_changed", details=None), None),
    ],
)
async def test_latest_admin_active_decision(activity, expected):
    from app.services.admin_active_decision import latest_admin_active_decision

    assert await latest_admin_active_decision(_ScalarDb(activity), 1) is expected


# ── R9-N1-1 ──────────────────────────────────────────────────────────────────


def test_normalize_email_and_lookup_is_case_insensitive():
    from sqlalchemy.dialects import postgresql

    from app.services.user_email import normalize_email, user_by_email_statement

    assert (
        normalize_email("  Jan.Kowalski@B2BNetwork.pl ") == "jan.kowalski@b2bnetwork.pl"
    )
    sql = str(
        user_by_email_statement("Jan@X.pl", for_update=True).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "lower(users.email)" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.parametrize("rel", ["api/auth.py", "api/auth_microsoft.py"])
def test_no_exact_email_comparison_left_in_login_paths(rel):
    source = (APP / rel).read_text()
    assert "User.email ==" not in source, rel
