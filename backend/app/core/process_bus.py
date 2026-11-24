"""Zdarzenia między procesami (web, drugi web, worker) przez LISTEN/NOTIFY Postgresa.

Gniazda przeglądarek są w web, a powiadomienia powstają też w pętlach i w drugim
procesie web. Bus niesie tylko sygnały, które można zgubić: rekord powiadomienia
jest już w bazie, a przy zerwanym połączeniu przepada najwyżej dymek na żywo.

Postgres doręcza NOTIFY także nadawcy. Temat z ``others_only=True`` pomija
wiadomości z własnego procesu (``PROCESS_TOKEN``): nadawca zrobił już swoją część
lokalnie. → docs/claude/podstawy/kilka-procesow-web.md
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.tasks import spawn
from app.services import loop_heartbeat

logger = logging.getLogger(__name__)

CHANNEL = "nexus_process_bus"
# Postgres odrzuca NOTIFY od 8000 bajtów.
MAX_PAYLOAD_BYTES = 7900
# Większa wiadomość (np. ramka czatu z długą wiadomością) idzie w kawałkach
# w jednej transakcji: NOTIFY z jednej transakcji dochodzą w kolejności wysłania.
# 5600 B w base64 to 7468 znaków, z kopertą kawałka poniżej MAX_PAYLOAD_BYTES.
_CHUNK_RAW_BYTES = 5600
MAX_MESSAGE_BYTES = 512_000
_PARTIAL_TTL_SECONDS = 60.0
_RECONNECT_SECONDS = 2.0
_PING_SECONDS = 30.0

# Identyfikator procesu, nie PID: web i worker to osobne kontenery i PID się powtarza.
PROCESS_TOKEN = uuid.uuid4().hex[:12]

Handler = Callable[[dict[str, Any]], Awaitable[None]]
_handlers: dict[str, Handler] = {}
_others_only: set[str] = set()
# Niepełne wiadomości w kawałkach: id → (czas pierwszego kawałka, liczba, kawałki).
_partials: dict[str, tuple[float, int, dict[int, bytes]]] = {}


def subscribe(topic: str, handler: Handler, *, others_only: bool = False) -> None:
    _handlers[topic] = handler
    if others_only:
        _others_only.add(topic)
    else:
        _others_only.discard(topic)


async def publish(topic: str, data: dict[str, Any]) -> bool:
    """``False`` = nie wysłano (za duże albo brak bazy); nigdy nie rzuca."""
    payload = json.dumps(
        {"t": topic, "d": data, "o": PROCESS_TOKEN}, ensure_ascii=False, default=str
    )
    parts = notify_payloads(payload)
    if parts is None:
        logger.warning("process_bus: %s za duże (%d B)", topic, len(payload.encode()))
        return False
    try:
        async with engine.begin() as conn:
            for part in parts:
                await conn.execute(
                    text("SELECT pg_notify(:channel, :payload)"),
                    {"channel": CHANNEL, "payload": part},
                )
        return True
    except Exception as exc:  # noqa: BLE001 — sygnał do zgubienia nie psuje nadawcy
        logger.warning("process_bus: publish %s: %s", topic, type(exc).__name__)
        return False


def notify_payloads(payload: str) -> list[str] | None:
    """Treści NOTIFY dla jednej wiadomości; ``None`` = większa niż ``MAX_MESSAGE_BYTES``."""
    raw = payload.encode()
    if len(raw) <= MAX_PAYLOAD_BYTES:
        return [payload]
    if len(raw) > MAX_MESSAGE_BYTES:
        return None
    chunk_id = uuid.uuid4().hex[:12]
    pieces = [
        raw[start : start + _CHUNK_RAW_BYTES]
        for start in range(0, len(raw), _CHUNK_RAW_BYTES)
    ]
    return [
        json.dumps(
            {
                "c": chunk_id,
                "i": index,
                "n": len(pieces),
                "p": base64.b64encode(piece).decode(),
            }
        )
        for index, piece in enumerate(pieces)
    ]


def _collect_chunk(part: dict[str, Any]) -> str | None:
    """Dołóż kawałek; pełna wiadomość, gdy przyszedł ostatni brakujący."""
    now = time.monotonic()
    for key in [
        k for k, (at, _, _) in _partials.items() if now - at > _PARTIAL_TTL_SECONDS
    ]:
        del _partials[key]
    _at, total, pieces = _partials.setdefault(part["c"], (now, int(part["n"]), {}))
    pieces[int(part["i"])] = base64.b64decode(part["p"])
    if len(pieces) < total:
        return None
    del _partials[part["c"]]
    return b"".join(pieces[index] for index in range(total)).decode()


def publish_soon(topic: str, data: dict[str, Any]) -> None:
    """``publish`` w tle, także z kodu synchronicznego (zdarzenia SQLAlchemy).

    Jeden proces (rola ``all``: testy, skrypty) albo brak pętli zdarzeń = nic.
    """
    if settings.NEXUS_PROCESS_ROLE == "all":
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    spawn(publish(topic, data), "process_bus")


async def dispatch(raw: str) -> None:
    message = json.loads(raw)
    if "c" in message:
        whole = _collect_chunk(message)
        if whole is None:
            return
        message = json.loads(whole)
    if message["t"] in _others_only and message.get("o") == PROCESS_TOKEN:
        return
    handler = _handlers.get(message["t"])
    if handler is not None:
        await handler(message["d"])


def _on_notify(_conn: Any, _pid: int, _channel: str, payload: str) -> None:
    spawn(dispatch(payload), "process_bus")


async def process_bus_loop() -> None:
    """Pętla tła: osobne połączenie, bo LISTEN nie przeżywa powrotu do puli."""
    if settings.NEXUS_PROCESS_ROLE == "all":
        return
    beat = loop_heartbeat.register("process_bus", max_silence_seconds=180)
    dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    while True:
        beat.tick()
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
                beat.tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla ponawia po każdej awarii
            logger.warning("process_bus: połączenie: %s", type(exc).__name__)
            await asyncio.sleep(_RECONNECT_SECONDS)
        finally:
            if conn is not None:
                conn.terminate()
