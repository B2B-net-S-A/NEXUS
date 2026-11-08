"""Stan pętli w tle widziany z kontenera web.

Pętle biegną w kontenerze ``worker``, a ``/api/health`` i ``/api/admin/snapshot``
odpytuje ruch z webu. Sonda ``uptime-probe`` alarmuje po ``checks.background_tasks``,
więc padnięty worker ma być widoczny tak samo jak padnięta pętla.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 3.0
# Front czyta `/api/health` przy każdym wejściu; bez bufora każde szłoby do workera.
_CACHE_SECONDS = 10.0
_cache: tuple[float, dict[str, Any]] | None = None


def _unreachable(reason: str) -> dict[str, Any]:
    return {
        "checks": {
            "background_tasks": f"unhealthy: worker nie odpowiada ({reason})",
            "ai_features": "unknown",
        },
        "tasks": None,
    }


async def fetch_worker_state() -> dict[str, Any]:
    """``{"checks": …, "tasks": …}`` z workera; nigdy nie rzuca."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(settings.NEXUS_WORKER_HEALTH_URL)
        response.raise_for_status()
        state = response.json()
    except Exception as exc:  # noqa: BLE001 — sonda stanu nie może wywrócić health
        logger.warning("[health] worker: %r", exc)
        state = _unreachable(type(exc).__name__)
    _cache = (now, state)
    return state
