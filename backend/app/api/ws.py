"""
WebSocket notifications endpoint.
Maintains per-user connections and broadcasts real-time events.

Also hosts in-memory presence tracking ("currently viewing" for candidate/job pages).
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy import select

from app.api.candidate_access import user_has_candidate_read
from app.core.database import AsyncSessionLocal
from app.core.security import (
    decode_token,
    token_authorization_version_matches,
    token_is_revoked,
)
from app.models.user import User
from app.services.notification_access import user_can_receive_realtime_event
from app.services.section_permissions import resolve_effective_section_access

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Presence DTO ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ViewerInfo:
    """Minimum identity broadcast on a presence channel.

    NEXUS-P1-12: deliberately only ``user_id`` + display ``name``. A colleague's
    email and role are internal PII and must never be broadcast to everyone
    viewing a candidate/job — so they are not even cached here, which makes a
    future re-leak through the payload builder structurally impossible.
    """

    user_id: int
    name: str


ResourceType = str  # "candidate" | "job"
ResourceKey = str  # f"{resource_type}:{resource_id}"


def _make_key(resource_type: str, resource_id: int) -> ResourceKey:
    return f"{resource_type}:{resource_id}"


def _parse_key(key: ResourceKey) -> Tuple[str, int]:
    rt, rid_str = key.split(":", 1)
    return rt, int(rid_str)


# ── Connection Manager ─────────────────────────────────────────────────────────


class ConnectionManager:
    def __init__(self) -> None:
        # Notifications: user_id → list of active WebSocket connections
        self._connections: Dict[int, List[WebSocket]] = {}
        # Real browser sockets retain the access token so every outbound event
        # can re-check authorization_version before exposing fresh data. Tests
        # that exercise the manager in isolation may connect without a token.
        self._auth_tokens: Dict[WebSocket, str] = {}

        # Presence state
        self._viewers: Dict[ResourceKey, Dict[int, Set[WebSocket]]] = {}
        self._editing: Dict[ResourceKey, Dict[int, Set[str]]] = {}
        self._since: Dict[ResourceKey, Dict[int, str]] = {}
        self._ws_subs: Dict[int, Dict[WebSocket, Set[ResourceKey]]] = {}
        self._user_info: Dict[int, ViewerInfo] = {}

    # ── Notifications (existing API) ──────────────────────────────────────────

    async def connect(
        self,
        user_id: int,
        websocket: WebSocket,
        *,
        subprotocol: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> None:
        # When the client carried the JWT on the WS subprotocol, RFC 6455 requires
        # us to echo one of the offered subprotocols on accept or the browser
        # aborts the handshake. `subprotocol=None` (legacy query-param path) is the
        # plain-accept default.
        await websocket.accept(subprotocol=subprotocol)
        if user_id not in self._connections:
            self._connections[user_id] = []
        self._connections[user_id].append(websocket)
        if auth_token:
            self._auth_tokens[websocket] = auth_token
        logger.info(
            "WS connected: user_id=%d, total=%d",
            user_id,
            len(self._connections[user_id]),
        )
        # Stamp users.last_seen_at — used by email-fallback task (Feature 11).
        await _stamp_last_seen(user_id)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        # Clean up presence subscriptions before removing from connections
        await self._cleanup_ws(user_id, websocket)
        self._auth_tokens.pop(websocket, None)

        if user_id in self._connections:
            try:
                self._connections[user_id].remove(websocket)
            except ValueError:
                pass
            if not self._connections[user_id]:
                del self._connections[user_id]
                # Last tab gone: forget cached user info + stamp last_seen.
                self._user_info.pop(user_id, None)
                await _stamp_last_seen(user_id)

        logger.info("WS disconnected: user_id=%d", user_id)

    async def notify_user(self, user_id: int, event: dict) -> None:
        """Send event to all WebSocket connections of a user."""
        connections = self._connections.get(user_id, [])
        if not connections:
            return
        dead: List[WebSocket] = []
        for ws in connections:
            try:
                token = self._auth_tokens.get(ws)
                if token:
                    current_user = await _authenticate_ws_token(token)
                    if current_user is None:
                        await ws.close(code=4001, reason="Unauthorized")
                        dead.append(ws)
                        continue
                    if not user_can_receive_realtime_event(current_user, event):
                        continue
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(user_id, ws)

    async def broadcast_all(self, event: dict) -> None:
        """Send event to all connected users (e.g., for system-wide alerts)."""
        for user_id in list(self._connections.keys()):
            await self.notify_user(user_id, event)

    def get_connected_user_ids(self) -> List[int]:
        return list(self._connections.keys())

    # ── Presence API ──────────────────────────────────────────────────────────

    def _remember_user(self, user: User) -> None:
        if user.id not in self._user_info:
            self._user_info[user.id] = ViewerInfo(
                user_id=user.id,
                name=user.name,
            )

    async def subscribe(
        self,
        user: User,
        websocket: WebSocket,
        resource_type: str,
        resource_id: int,
    ) -> None:
        """Register a WebSocket as viewing a given resource.

        Idempotent: multiple subscribes from the same ws for the same key are no-ops.
        Multiple tabs of the same user count as one viewer (dedup by user_id).
        """
        key = _make_key(resource_type, resource_id)
        self._remember_user(user)

        self._viewers.setdefault(key, {}).setdefault(user.id, set()).add(websocket)
        self._ws_subs.setdefault(user.id, {}).setdefault(websocket, set()).add(key)
        self._since.setdefault(key, {}).setdefault(
            user.id, datetime.now(timezone.utc).isoformat()
        )

        await self._broadcast_update(key)

    async def unsubscribe(
        self,
        user_id: int,
        websocket: WebSocket,
        resource_type: str,
        resource_id: int,
    ) -> None:
        key = _make_key(resource_type, resource_id)
        changed = self._remove_ws_from_key(user_id, websocket, key)
        if changed:
            await self._broadcast_update(key)

    async def set_editing(
        self,
        user_id: int,
        resource_type: str,
        resource_id: int,
        field: str,
        active: bool,
    ) -> None:
        """Toggle the 'editing' flag for a field on a resource."""
        key = _make_key(resource_type, resource_id)
        if key not in self._viewers or user_id not in self._viewers[key]:
            # User isn't a viewer — ignore the edit signal
            return

        fields = self._editing.setdefault(key, {}).setdefault(user_id, set())
        before = fields.copy()
        if active:
            fields.add(field)
        else:
            fields.discard(field)
            if not fields:
                self._editing[key].pop(user_id, None)
        if fields != before:
            await self._broadcast_update(key)

    def get_viewers(self, resource_type: str, resource_id: int) -> List[dict]:
        """Return a snapshot of viewers for a resource (for HTTP fallback)."""
        key = _make_key(resource_type, resource_id)
        return self._build_viewers_payload(key)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _remove_ws_from_key(
        self, user_id: int, websocket: WebSocket, key: ResourceKey
    ) -> bool:
        """Remove a ws from a key subscription. Returns True if viewer list changed."""
        viewers_for_key = self._viewers.get(key)
        if not viewers_for_key:
            return False
        ws_set = viewers_for_key.get(user_id)
        if not ws_set or websocket not in ws_set:
            return False

        ws_set.discard(websocket)

        # Update reverse index
        user_ws_map = self._ws_subs.get(user_id, {})
        if websocket in user_ws_map:
            user_ws_map[websocket].discard(key)
            if not user_ws_map[websocket]:
                user_ws_map.pop(websocket, None)
            if not user_ws_map:
                self._ws_subs.pop(user_id, None)

        if not ws_set:
            # Last tab of this user for this key
            viewers_for_key.pop(user_id, None)
            self._editing.get(key, {}).pop(user_id, None)
            self._since.get(key, {}).pop(user_id, None)
            if not viewers_for_key:
                self._viewers.pop(key, None)
                self._editing.pop(key, None)
                self._since.pop(key, None)
            return True

        return False  # user still has another tab on this key

    async def _cleanup_ws(self, user_id: int, websocket: WebSocket) -> None:
        """Drop a ws from every resource it had subscribed to.

        Called on WebSocket disconnect. Broadcasts presence updates for each
        affected key where the viewer list actually changed.
        """
        user_ws_map = self._ws_subs.get(user_id, {})
        if websocket not in user_ws_map:
            return

        keys = list(user_ws_map[websocket])
        changed_keys: List[ResourceKey] = []
        for key in keys:
            if self._remove_ws_from_key(user_id, websocket, key):
                changed_keys.append(key)

        for key in changed_keys:
            await self._broadcast_update(key)

    def _build_viewers_payload(self, key: ResourceKey) -> List[dict]:
        viewers_for_key = self._viewers.get(key, {})
        editing_for_key = self._editing.get(key, {})
        since_for_key = self._since.get(key, {})
        payload: List[dict] = []
        for uid in viewers_for_key.keys():
            info = self._user_info.get(uid)
            if not info:
                continue
            payload.append(
                {
                    "user_id": info.user_id,
                    "name": info.name,
                    # NEXUS-P1-12 (extends P1.3): the payload carries only the
                    # minimum identity needed to render "who is viewing/editing"
                    # — user_id + display name. A colleague's email AND role are
                    # internal PII and must not be broadcast to everyone on a
                    # candidate/job channel. The frontend avatar falls back to
                    # `name`; the role tooltip line degrades to empty.
                    "editing": sorted(editing_for_key.get(uid, set())),
                    "since": since_for_key.get(uid),
                }
            )
        return payload

    async def _broadcast_update(self, key: ResourceKey) -> None:
        rt, rid = _parse_key(key)
        event = {
            "type": "presence:update",
            "resource_type": rt,
            "resource_id": rid,
            "viewers": self._build_viewers_payload(key),
        }
        viewers_for_key = self._viewers.get(key, {})
        for ws_set in viewers_for_key.values():
            for ws in list(ws_set):
                try:
                    await ws.send_json(event)
                except Exception as e:
                    logger.debug("WS send failed during presence broadcast: %s", e)


# Singleton manager — imported by other modules to call notify_user/get_viewers
manager = ConnectionManager()


async def notify_user(user_id: int, event: dict) -> None:
    """Public helper callable from any API endpoint."""
    await manager.notify_user(user_id, event)


async def _stamp_last_seen(user_id: int) -> None:
    """Update users.last_seen_at = NOW() for the email-fallback task.

    Best-effort: errors swallowed — WS lifecycle should never block on
    ancillary stat tracking.
    """
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                User.__table__.update()
                .where(User.id == user_id)
                .values(last_seen_at=datetime.now(timezone.utc))
            )
            await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.debug("last_seen_at stamp failed for user %d: %s", user_id, e)


# ── Token auth helper ──────────────────────────────────────────────────────────

# Sentinel subprotocol the client offers alongside the JWT, e.g.
# ``new WebSocket(url, ["access_token", "<jwt>"])``. The server reads the JWT
# from the paired value and echoes THIS sentinel as the negotiated subprotocol.
_WS_TOKEN_SUBPROTOCOL = "access_token"


def _extract_ws_token(
    websocket: WebSocket, query_token: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve the WS auth token, preferring the subprotocol over the query string.

    NEXUS-P1-WS-01: a JWT in the ``?token=`` query string leaks into access /
    proxy / trace logs. The client instead offers two subprotocols —
    ``[_WS_TOKEN_SUBPROTOCOL, "<jwt>"]`` — so the token rides an ``Upgrade``
    request header that is not logged as a URL. We read it from there and echo
    the sentinel as the accepted subprotocol.

    Returns ``(token, accepted_subprotocol)``. ``accepted_subprotocol`` is the
    sentinel only when the token actually came from the subprotocol (so it can be
    echoed on accept); it is ``None`` on the legacy query-param fallback, where no
    subprotocol must be echoed. The ``?token=`` path is retained as a temporary
    rollout fallback so in-flight clients on the old bundle keep working.
    """
    subprotocols = list(websocket.scope.get("subprotocols") or [])
    if _WS_TOKEN_SUBPROTOCOL in subprotocols:
        idx = subprotocols.index(_WS_TOKEN_SUBPROTOCOL)
        # The JWT is the offer immediately following the sentinel.
        if idx + 1 < len(subprotocols):
            token = subprotocols[idx + 1]
            if token:
                return token, _WS_TOKEN_SUBPROTOCOL
    return query_token, None


def _ws_payload_authorizes_user(payload: dict, user: User) -> bool:
    """Mirror the stateful HTTP session checks for a decoded WS access token."""

    return (
        user.is_active
        and not token_is_revoked(payload, user.tokens_valid_after)
        and token_authorization_version_matches(payload, user.authorization_version)
    )


async def _authenticate_ws_token(token: str) -> Optional[User]:
    """Validate JWT token and return User, or None on failure.

    WebSockets bypass FastAPI's HTTP dependencies, so the handshake must mirror
    ``get_current_user`` explicitly. In particular, a correctly signed access
    token is still stale after a role/status change when its ``av`` claim no
    longer matches ``users.authorization_version``. Tokens without ``av`` (or
    with a non-integer value) fail closed.
    """
    try:
        payload = decode_token(token)
        user_id_str = payload.get("sub")
        if not user_id_str or payload.get("type") != "access":
            return None
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and _ws_payload_authorizes_user(payload, user):
            await resolve_effective_section_access(db, user)
            return user
    return None


# ── WebSocket endpoint ────────────────────────────────────────────────────────


_ALLOWED_RESOURCE_TYPES = {"candidate", "job"}


def presence_subscribe_allowed(user: User) -> bool:
    """Authorization gate for joining a candidate/job presence channel.

    NEXUS-P1-12: the raw WebSocket path would otherwise bypass every HTTP
    authorization guard, letting any authenticated account subscribe to an
    arbitrary ``candidate:{id}`` / ``job:{id}`` channel and watch who is
    editing it.

    NEXUS candidate/job access is role-based (see ``app.api.candidate_access``):
    the internal operational roles read the whole base, while the read-only
    viewer/client ``user`` role does not. There is no per-resource ACL to
    consult, so this capability check IS the containment for presence — it
    reuses the same ``user_has_candidate_read`` capability the HTTP
    ``RecruitmentReadAccess`` / candidate-read guards enforce (union of the
    primary ``users.role`` and secondary ``users.roles`` via ``has_any_role``).
    Applied identically to candidate and job channels; fail-closed (a viewer is
    refused both subscribe and the ``presence:editing`` signal).
    """
    return user_has_candidate_read(user)


async def _handle_presence_message(user: User, websocket: WebSocket, msg: dict) -> None:
    msg_type = msg.get("type")
    rt = msg.get("resource_type")
    rid = msg.get("resource_id")
    if rt not in _ALLOWED_RESOURCE_TYPES or not isinstance(rid, int):
        return

    # Presence is an internal collaboration signal. A read-only viewer
    # (UserRole.user) must not be able to see — or announce themselves in — the
    # viewer list of an arbitrary candidate/job. Unsubscribe stays open so a
    # role change can always tear a stale subscription down.
    if msg_type == "presence:subscribe":
        if not presence_subscribe_allowed(user):
            return
        await manager.subscribe(user, websocket, rt, rid)
    elif msg_type == "presence:unsubscribe":
        await manager.unsubscribe(user.id, websocket, rt, rid)
    elif msg_type == "presence:editing":
        if not presence_subscribe_allowed(user):
            return
        field = msg.get("field")
        active = bool(msg.get("active"))
        if isinstance(field, str) and field:
            await manager.set_editing(user.id, rt, rid, field, active)


@router.websocket("/ws/notifications")
async def ws_notifications(
    websocket: WebSocket,
    token: Optional[str] = Query(
        None,
        description=(
            "JWT access token (legacy fallback; prefer the WS subprotocol "
            "['access_token', <jwt>] which keeps the token out of URLs/logs)"
        ),
    ),
):
    """
    WebSocket endpoint for real-time notifications + presence.

    Auth: connect with subprotocols ``["access_token", "<jwt>"]`` (preferred —
    keeps the token off the URL) or, as a temporary rollout fallback, with
    ``ws://host/ws/notifications?token=<access_token>``.

    Events sent to client:
      {type: "notification", data: {id, title, message, link, created_at}}
      {type: "presence:update", resource_type, resource_id, viewers: [...]}
      {type: "ping"}

    Events accepted from client:
      "ping" (plain text, legacy keep-alive)
      {type: "presence:subscribe", resource_type, resource_id}
      {type: "presence:unsubscribe", resource_type, resource_id}
      {type: "presence:editing", resource_type, resource_id, field, active}
    """
    raw_token, accepted_subprotocol = _extract_ws_token(websocket, token)
    if not raw_token:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    user = await _authenticate_ws_token(raw_token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(
        user.id,
        websocket,
        subprotocol=accepted_subprotocol,
        auth_token=raw_token,
    )

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "data": {
                    "user_id": user.id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }
        )

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # The connection manager is process-local, so an admin changing a
                # role in another worker cannot safely "push" a disconnect into
                # this worker. Re-check the signed token against authoritative DB
                # state on every keep-alive interval instead. This also expires
                # existing sockets after an authorization-version bump rather
                # than protecting only new handshakes.
                refreshed_user = await _authenticate_ws_token(raw_token)
                if refreshed_user is None:
                    await websocket.close(code=4001, reason="Unauthorized")
                    break
                user = refreshed_user
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue

            # Re-authorize before acting on any client frame. A role/status
            # change that landed while receive_text() was pending must not leave
            # a stale socket able to subscribe to presence channels.
            refreshed_user = await _authenticate_ws_token(raw_token)
            if refreshed_user is None:
                await websocket.close(code=4001, reason="Unauthorized")
                break
            user = refreshed_user

            if data == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            # JSON frames: notifications control or presence
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                logger.debug("WS: ignoring non-JSON frame")
                continue

            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type")
            if isinstance(msg_type, str) and msg_type.startswith("presence:"):
                await _handle_presence_message(user, websocket, msg)
            # Other message types are ignored for now.

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WS error for user %d: %s", user.id, e)
    finally:
        await manager.disconnect(user.id, websocket)
