"""Zdarzenia między procesem web a workerem przez LISTEN/NOTIFY Postgresa.

Gniazda przeglądarek są w web, a powiadomienia powstają też w pętlach. Bus niesie
tylko sygnały, które można zgubić: rekord powiadomienia jest już w bazie, a przy
zerwanym połączeniu przepada najwyżej dymek na żywo.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.tasks import spawn

logger = logging.getLogger(__name__)

CHANNEL = "nexus_process_bus"
# Postgres odrzuca NOTIFY od 8000 bajtów.
MAX_PAYLOAD_BYTES = 7900
_RECONNECT_SECONDS = 2.0
_PING_SECONDS = 30.0

Handler = Callable[[dict[str, Any]], Awaitable[None]]
_handlers: dict[str, Handler] = {}


def subscribe(topic: str, handler: Handler) -> None:
    _handlers[topic] = handler


async def publish(topic: str, data: dict[str, Any]) -> bool:
    """``False`` = nie wysłano (za duże albo brak bazy); nigdy nie rzuca."""
    payload = json.dumps({"t": topic, "d": data}, ensure_ascii=False, default=str)
    if len(payload.encode()) > MAX_PAYLOAD_BYTES:
        logger.warning("process_bus: %s za duże (%d B)", topic, len(payload.encode()))
        return False
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {"channel": CHANNEL, "payload": payload},
            )
        return True
    except Exception as exc:  # noqa: BLE001 — sygnał do zgubienia nie psuje nadawcy
        logger.warning("process_bus: publish %s: %s", topic, type(exc).__name__)
        return False


async def dispatch(raw: str) -> None:
    message = json.loads(raw)
    handler = _handlers.get(message["t"])
    if handler is not None:
        await handler(message["d"])


def _on_notify(_conn: Any, _pid: int, _channel: str, payload: str) -> None:
    spawn(dispatch(payload), "process_bus")


async def process_bus_loop() -> None:
    """Pętla tła: osobne połączenie, bo LISTEN nie przeżywa powrotu do puli."""
    if settings.NEXUS_PROCESS_ROLE == "all":
        return
    dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    while True:
        conn = None
        try:
            conn = await asyncpg.connect(
                dsn,
                timeout=5.0,
                server_settings={"application_name": "nexus-process-bus"},
            )
            await conn.add_listener(CHANNEL, _on_notify)
            while True:
                await asyncio.sleep(_PING_SECONDS)
                await conn.fetchval("SELECT 1")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla ponawia po każdej awarii
            logger.warning("process_bus: połączenie: %s", type(exc).__name__)
            await asyncio.sleep(_RECONNECT_SECONDS)
        finally:
            if conn is not None:
                conn.terminate()
