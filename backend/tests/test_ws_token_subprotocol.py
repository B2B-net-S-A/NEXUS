"""P1-WS-01 — the WS JWT rides the subprotocol, not the query string.

A JWT in ``/ws/notifications?token=<jwt>`` leaks into access / proxy / trace
logs. The client now offers ``["access_token", "<jwt>"]`` as WS subprotocols so
the token travels in an ``Upgrade`` request header instead of the URL; the
server reads it from there and echoes the ``access_token`` sentinel on accept.
The legacy ``?token=`` path is kept as a temporary rollout fallback.

These tests exercise the pure token-resolution (`_extract_ws_token`) and prove
that a token resolved from EITHER transport authenticates against the real DB
(`_authenticate_ws_token`). The full ASGI handshake is not driven here: the sync
starlette TestClient + asyncpg combination conflicts on event loops (see
test_presence_api.py), so auth is asserted directly on the asyncio loop.
"""

from __future__ import annotations

import uuid

from app.api.ws import (
    _WS_TOKEN_SUBPROTOCOL,
    _authenticate_ws_token,
    _extract_ws_token,
)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


class _FakeWS:
    """Minimal WebSocket stand-in exposing only ``.scope`` for token extraction."""

    def __init__(self, subprotocols: list[str] | None = None) -> None:
        self.scope = {"subprotocols": list(subprotocols or [])}


# ── Pure resolution ──────────────────────────────────────────────────────────


def test_extract_prefers_subprotocol() -> None:
    ws = _FakeWS([_WS_TOKEN_SUBPROTOCOL, "jwt-abc"])
    token, accepted = _extract_ws_token(ws, query_token=None)
    assert token == "jwt-abc"
    assert accepted == _WS_TOKEN_SUBPROTOCOL  # echoed back on accept


def test_extract_subprotocol_wins_over_query() -> None:
    ws = _FakeWS([_WS_TOKEN_SUBPROTOCOL, "jwt-sub"])
    token, accepted = _extract_ws_token(ws, query_token="jwt-query")
    assert token == "jwt-sub"
    assert accepted == _WS_TOKEN_SUBPROTOCOL


def test_extract_query_fallback_when_no_subprotocol() -> None:
    ws = _FakeWS([])
    token, accepted = _extract_ws_token(ws, query_token="jwt-query")
    assert token == "jwt-query"
    assert accepted is None  # nothing offered → plain accept, no echo


def test_extract_ignores_sentinel_without_paired_token() -> None:
    # Sentinel offered but no value follows → fall back to the query param.
    ws = _FakeWS([_WS_TOKEN_SUBPROTOCOL])
    token, accepted = _extract_ws_token(ws, query_token="jwt-query")
    assert token == "jwt-query"
    assert accepted is None


def test_extract_none_when_neither_present() -> None:
    ws = _FakeWS([])
    token, accepted = _extract_ws_token(ws, query_token=None)
    assert token is None
    assert accepted is None


# ── End-to-end auth of the resolved token (real DB) ──────────────────────────


async def _seed_user(label: str) -> int:
    email = f"ws-{label}-{uuid.uuid4().hex[:8]}@example.com"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password("Irrelevant_1!x"),
            name=f"WS {label}",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def test_subprotocol_token_authenticates() -> None:
    """A JWT carried on the subprotocol resolves to the real, active user."""
    uid = await _seed_user("subproto")
    token = create_access_token(uid, UserRole.admin.value)

    ws = _FakeWS([_WS_TOKEN_SUBPROTOCOL, token])
    extracted, accepted = _extract_ws_token(ws, query_token=None)
    assert accepted == _WS_TOKEN_SUBPROTOCOL

    authed = await _authenticate_ws_token(extracted)
    assert authed is not None
    assert authed.id == uid


async def test_query_param_token_still_authenticates() -> None:
    """Legacy ?token= fallback still authenticates (in-flight rollout safety)."""
    uid = await _seed_user("query")
    token = create_access_token(uid, UserRole.admin.value)

    ws = _FakeWS([])  # no subprotocol offered → query fallback path
    extracted, accepted = _extract_ws_token(ws, query_token=token)
    assert accepted is None

    authed = await _authenticate_ws_token(extracted)
    assert authed is not None
    assert authed.id == uid
