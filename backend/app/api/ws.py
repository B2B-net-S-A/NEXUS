"""
WebSocket notifications endpoint.
Maintains per-user connections and broadcasts real-time events.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Connection Manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        # user_id → list of active WebSocket connections
        self._connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self._connections:
            self._connections[user_id] = []
        self._connections[user_id].append(websocket)
        logger.info(f"WS connected: user_id={user_id}, total={len(self._connections[user_id])}")

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self._connections:
            try:
                self._connections[user_id].remove(websocket)
            except ValueError:
                pass
            if not self._connections[user_id]:
                del self._connections[user_id]
        logger.info(f"WS disconnected: user_id={user_id}")

    async def notify_user(self, user_id: int, event: dict):
        """Send event to all WebSocket connections of a user."""
        connections = self._connections.get(user_id, [])
        if not connections:
            return
        dead = []
        for ws in connections:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    async def broadcast_all(self, event: dict):
        """Send event to all connected users (e.g., for system-wide alerts)."""
        for user_id in list(self._connections.keys()):
            await self.notify_user(user_id, event)

    def get_connected_user_ids(self) -> List[int]:
        return list(self._connections.keys())


# Singleton manager — imported by other modules to call notify_user
manager = ConnectionManager()


async def notify_user(user_id: int, event: dict):
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

@router.websocket("/ws/notifications")
async def ws_notifications(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """
    WebSocket endpoint for real-time notifications.
    Connect with: ws://host/ws/notifications?token=<access_token>
    
    Events sent to client:
      {type: "notification", data: {id, title, message, link, created_at}}
      {type: "ping"}
    """
    user = await _authenticate_ws_token(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(user.id, websocket)

    try:
        # Send initial "connected" confirmation
        await websocket.send_json({
            "type": "connected",
            "data": {
                "user_id": user.id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

        # Keep-alive loop — receive pings from client, send pongs
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send server-side ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS error for user {user.id}: {e}")
    finally:
        manager.disconnect(user.id, websocket)
