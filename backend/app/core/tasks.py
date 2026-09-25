"""Zadania w tle uruchamiane z handlerów (fire-and-forget) — z trzymaną referencją.

Goły ``asyncio.create_task(...)`` bez zapamiętanej referencji może zniknąć
w połowie: pętla zdarzeń trzyma do zadania tylko SŁABĄ referencję, więc GC
zbiera je, gdy nikt inny go nie trzyma — backfill albo import urywa się bez
żadnego śladu. Do tego wyjątek w takim zadaniu jest niewidoczny, bo nikt nie
czyta jego wyniku.

Wyniesione z ``app/api/microsoft365.py`` (audyt 25.09.2026), żeby każdy
endpoint startujący bieg w tle (sync Traffita, backfille kandydatów, import,
wysyłka do Autenti) używał jednego wzorca.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Silne referencje do zadań w locie; zadanie usuwa się samo po zakończeniu.
_bg_tasks: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any], label: str) -> asyncio.Task[Any]:
    """Uruchom ``coro`` w tle, trzymając referencję i logując jego porażkę."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def _done(finished: asyncio.Task[Any]) -> None:
        _bg_tasks.discard(finished)
        if finished.cancelled():
            # Redeploy Coolify ubija pętlę zdarzeń — to nie jest błąd, ale ma
            # zostawić ślad, żeby urwany bieg dało się później wyjaśnić.
            logger.warning("Background task cancelled: %s", label)
            return
        exc = finished.exception()
        if exc is not None:
            logger.error("Background task failed: %s", label, exc_info=exc)

    task.add_done_callback(_done)
    return task


__all__ = ["spawn"]
