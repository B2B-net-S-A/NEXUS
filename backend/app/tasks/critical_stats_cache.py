"""Statystyki krytycznych w pamięci procesu web.

Odświeża je dotąd pętla ``auto_full_review``, która biegnie w workerze, a bramka
wymagań w trasach czyta pamięć własnego procesu.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.services import loop_heartbeat
from app.services.auto_full_review import (
    _CRITICAL_CACHE_TTL,
    _refresh_critical_stats_cache,
)


async def critical_stats_cache_loop() -> None:
    beat = loop_heartbeat.register("critical_stats_cache", max_silence_seconds=7500)
    while True:
        beat.tick()
        await _refresh_critical_stats_cache(datetime.now(timezone.utc))
        await asyncio.sleep(_CRITICAL_CACHE_TTL.total_seconds() + 60)
