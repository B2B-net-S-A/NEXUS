"""Wywołanie webhooka rutyny Grok Bota: jedna treść, jej rozmiar i kod odpowiedzi.

Od 24.11.2026 webhook niesie samą kopertę biegu (``schema_version`` 2:
``run_id``, ``request_url``, ``token``, ``expires_at``), a bot pobiera pełne
zlecenie GET-em na ``request_url`` z nagłówkiem ``X-Run-Token``. Powód: przy
paczkach 25–40 firm treść webhooka z całym zleceniem docierała do bota ucięta
(bieg 693 urwany w połowie polecenia), a bez ``report_format`` bot nic nie
odsyłał.

``GROK_BOT_WEBHOOK_V1`` to zapas na czas zmiany polecenia rutyny: rutyny
wymienione po przecinku dostają dawną treść z całym zleceniem (``schema_version``
1). Nazwy: boty Sprzedaży z ``services/sales/bots.py`` (``research``, ``leads``,
``company``, ``contacts``, ``cognism``, ``lists``) i rutyny radaru przepisów
(``law_collect``, ``law_analyze``).

Treść serializujemy sami (tak samo jak ``httpx`` przy ``json=``), żeby zalogować
dokładny rozmiar wysłanych bajtów i kod odpowiedzi: po tym widać, czy cięcie było
po stronie NEXUSA, czy rutyny. Logi są publiczne: same liczby.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

V1 = 1
V2 = 2
TIMEOUT_SECONDS = 20.0
LAW_COLLECT = "law_collect"
LAW_ANALYZE = "law_analyze"


def v1_routines() -> frozenset[str]:
    raw = str(settings.GROK_BOT_WEBHOOK_V1 or "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def schema_for(routine: str) -> int:
    """Wersja treści webhooka dla rutyny: 2, chyba że rutyna czeka na v1."""

    return V1 if routine in v1_routines() else V2


def envelope(
    run_id: int, request_url: str, token: str, expires_at: Optional[datetime]
) -> dict[str, Any]:
    """Treść webhooka v2: tylko to, czego bot potrzebuje, żeby pobrać zlecenie."""

    return {
        "schema_version": V2,
        "run_id": run_id,
        "request_url": request_url,
        "token": token,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def encode(body: dict[str, Any]) -> bytes:
    """Te same bajty co ``httpx`` 0.28 przy ``json=``: UTF-8, bez spacji."""

    return json.dumps(
        body, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True)
class Outcome:
    sent_bytes: int
    status_code: Optional[int] = None
    #: ``None``: rutyna przyjęła wywołanie albo nie wiadomo (timeout).
    error: Optional[str] = None
    timed_out: bool = False


async def post(
    url: str,
    key: str,
    body: dict[str, Any],
    *,
    client: Optional[httpx.AsyncClient] = None,
    channel: str,
    run_id: int,
    kind: str,
    routine: str,
) -> Outcome:
    """Wyślij treść, zaloguj rozmiar i kod odpowiedzi; wyjątki HTTP zamienia na wynik."""

    payload = encode(body)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    status_code: Optional[int] = None
    error: Optional[str] = None
    timed_out = False
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as own:
                response = await own.post(url, content=payload, headers=headers)
        else:
            response = await client.post(url, content=payload, headers=headers)
        status_code = response.status_code
        response.raise_for_status()
    except httpx.TimeoutException:
        timed_out = True
    except httpx.HTTPStatusError as exc:
        error = f"webhook HTTP {exc.response.status_code}"
    except httpx.HTTPError as exc:
        error = f"webhook {type(exc).__name__}"[:255]
    outcome = Outcome(len(payload), status_code, error, timed_out)
    result = (
        "timeout" if timed_out else str(status_code) if status_code else error or "-"
    )
    logger.info(
        "bot_webhook channel=%s run=%s kind=%s routine=%s schema=%s bytes=%d response=%s",
        channel,
        run_id,
        kind,
        routine,
        body.get("schema_version"),
        outcome.sent_bytes,
        result,
        extra={
            "event_kind": "bot_webhook",
            "channel": channel,
            "run_id": run_id,
            "kind": kind,
            "routine": routine,
            "schema_version": body.get("schema_version"),
            "sent_bytes": outcome.sent_bytes,
            "response_status": status_code,
            "timed_out": timed_out,
        },
    )
    return outcome
