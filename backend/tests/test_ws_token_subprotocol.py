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
from unittest.mock import AsyncMock

from jose import jwt

from app.api import ws as ws_module
from app.api.ws import (
    _WS_TOKEN_SUBPROTOCOL,
    _authenticate_ws_token,
    _extract_ws_token,
    _ws_payload_authorizes_user,
    ws_notifications,
)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import (
    ALGORITHM,
    create_access_token,
    decode_token,
    hash_password,
)
from app.models.user import User, UserRole


class _FakeWS:
    """Minimal WebSocket stand-in exposing only ``.scope`` for token extraction."""

    def __init__(self, subprotocols: list[str] | None = None) -> None:
        self.scope = {"subprotocols": list(subprotocols or [])}


class _EndpointWS(_FakeWS):
    """Small endpoint double that records an authorization close."""

    def __init__(self) -> None:
        super().__init__()
        self.closed: tuple[int, str] | None = None

    async def receive_text(self) -> str:
        return "ping"

    async def send_json(self, _payload: dict) -> None:
        return None

    async def close(self, *, code: int, reason: str) -> None:
        self.closed = (code, reason)


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


def test_ws_authorization_version_comparison_fails_closed() -> None:
    """Handshake state check accepts only the exact integer DB version."""
    user = User(
        id=991001,
        email="ws-av-unit@example.com",
        name="WS AV",
        role=UserRole.admin,
        is_active=True,
        authorization_version=7,
    )

    assert _ws_payload_authorizes_user({"av": 7}, user) is True
    assert _ws_payload_authorizes_user({"av": 6}, user) is False
    assert _ws_payload_authorizes_user({"av": "7"}, user) is False
    assert _ws_payload_authorizes_user({}, user) is False


async def test_connected_socket_is_closed_after_authorization_change(
    monkeypatch,
) -> None:
    """A live socket re-checks DB authorization before processing a frame."""
    user = User(
        id=991002,
        email="ws-live-av@example.com",
        name="WS live AV",
        role=UserRole.admin,
        is_active=True,
        authorization_version=7,
    )
    authenticate = AsyncMock(side_effect=[user, None])
    connect = AsyncMock()
    disconnect = AsyncMock()
    monkeypatch.setattr(ws_module, "_authenticate_ws_token", authenticate)
    monkeypatch.setattr(ws_module.manager, "connect", connect)
    monkeypatch.setattr(ws_module.manager, "disconnect", disconnect)
    websocket = _EndpointWS()

    await ws_notifications(websocket, token="signed-jwt")

    connect.assert_awaited_once_with(user.id, websocket, subprotocol=None)
    assert websocket.closed == (4001, "Unauthorized")
    disconnect.assert_awaited_once_with(user.id, websocket)
    assert authenticate.await_count == 2


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


async def _seed_user_with_authorization_version(label: str, version: int) -> int:
    email = f"ws-{label}-{uuid.uuid4().hex[:8]}@example.com"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password("Irrelevant_1!x"),
            name=f"WS {label}",
            role=UserRole.admin,
            is_active=True,
            authorization_version=version,
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


async def test_stale_authorization_version_is_rejected() -> None:
    """A role/status change invalidates the old WS token at handshake."""
    uid = await _seed_user_with_authorization_version("stale-av", 2)
    stale_token = create_access_token(
        uid,
        UserRole.admin.value,
        authorization_version=1,
    )

    assert await _authenticate_ws_token(stale_token) is None


async def test_current_authorization_version_authenticates() -> None:
    """The exact current integer ``av`` is accepted."""
    uid = await _seed_user_with_authorization_version("current-av", 7)
    current_token = create_access_token(
        uid,
        UserRole.admin.value,
        authorization_version=7,
    )

    authed = await _authenticate_ws_token(current_token)
    assert authed is not None
    assert authed.id == uid


async def test_token_without_authorization_version_is_rejected() -> None:
    """Pre-cutover tokens without ``av`` fail closed on the WS path."""
    uid = await _seed_user_with_authorization_version("missing-av", 1)
    payload = decode_token(create_access_token(uid, UserRole.admin.value))
    payload.pop("av")
    legacy_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)

    assert await _authenticate_ws_token(legacy_token) is None


async def test_non_integer_authorization_version_is_rejected() -> None:
    """A type-coerced claim cannot bypass the exact-version comparison."""
    uid = await _seed_user_with_authorization_version("string-av", 7)
    payload = decode_token(
        create_access_token(
            uid,
            UserRole.admin.value,
            authorization_version=7,
        )
    )
    payload["av"] = "7"
    malformed_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)

    assert await _authenticate_ws_token(malformed_token) is None
