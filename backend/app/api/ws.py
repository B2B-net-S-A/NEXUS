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

from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Presence DTO ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ViewerInfo:
    user_id: int
    name: str
    email: str
    role: str


ResourceType = str  # "candidate" | "job"
ResourceKey = str  # f"{resource_type}:{resource_id}"


def _make_key(resource_type: str, resource_id: int) -> ResourceKey:
    return f"{resource_type}:{resource_id}"


def _parse_key(key: ResourceKey) -> Tuple[str, int]:
    rt, rid_str = key.split(":", 1)
    return rt, int(rid_str)


def _role_to_str(role) -> str:
    return role.value if hasattr(role, "value") else str(role)


# ── Connection Manager ─────────────────────────────────────────────────────────


class ConnectionManager:
    def __init__(self) -> None:
        # Notifications: user_id → list of active WebSocket connections
        self._connections: Dict[int, List[WebSocket]] = {}

        # Presence state
        self._viewers: Dict[ResourceKey, Dict[int, Set[WebSocket]]] = {}
        self._editing: Dict[ResourceKey, Dict[int, Set[str]]] = {}
        self._since: Dict[ResourceKey, Dict[int, str]] = {}
        self._ws_subs: Dict[int, Dict[WebSocket, Set[ResourceKey]]] = {}
        self._user_info: Dict[int, ViewerInfo] = {}

    # ── Notifications (existing API) ──────────────────────────────────────────

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        if user_id not in self._connections:
            self._connections[user_id] = []
        self._connections[user_id].append(websocket)
        logger.info(
            "WS connected: user_id=%d, total=%d",
            user_id,
            len(self._connections[user_id]),
        )

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        # Clean up presence subscriptions before removing from connections
        await self._cleanup_ws(user_id, websocket)

        if user_id in self._connections:
            try:
                self._connections[user_id].remove(websocket)
            except ValueError:
                pass
            if not self._connections[user_id]:
                del self._connections[user_id]
                # Last tab gone: forget cached user info
                self._user_info.pop(user_id, None)

        logger.info("WS disconnected: user_id=%d", user_id)

    async def notify_user(self, user_id: int, event: dict) -> None:
        """Send event to all WebSocket connections of a user."""
        connections = self._connections.get(user_id, [])
        if not connections:
            return
        dead: List[WebSocket] = []
        for ws in connections:
            try:
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
                email=user.email,
                role=_role_to_str(user.role),
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
                    "email": info.email,
                    "role": info.role,
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


# ── Token auth helper ──────────────────────────────────────────────────────────


async def _authenticate_ws_token(token: str) -> Optional[User]:
    """Validate JWT token and return User, or None on failure."""
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
        if user and user.is_active:
            return user
    return None


# ── WebSocket endpoint ────────────────────────────────────────────────────────


_ALLOWED_RESOURCE_TYPES = {"candidate", "job"}


async def _handle_presence_message(
    user: User, websocket: WebSocket, msg: dict
) -> None:
    msg_type = msg.get("type")
    rt = msg.get("resource_type")
    rid = msg.get("resource_id")
    if rt not in _ALLOWED_RESOURCE_TYPES or not isinstance(rid, int):
        return

    if msg_type == "presence:subscribe":
        await manager.subscribe(user, websocket, rt, rid)
    elif msg_type == "presence:unsubscribe":
        await manager.unsubscribe(user.id, websocket, rt, rid)
    elif msg_type == "presence:editing":
        field = msg.get("field")
        active = bool(msg.get("active"))
        if isinstance(field, str) and field:
            await manager.set_editing(user.id, rt, rid, field, active)


@router.websocket("/ws/notifications")
async def ws_notifications(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """
    WebSocket endpoint for real-time notifications + presence.
    Connect with: ws://host/ws/notifications?token=<access_token>

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
    user = await _authenticate_ws_token(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(user.id, websocket)

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
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue

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
