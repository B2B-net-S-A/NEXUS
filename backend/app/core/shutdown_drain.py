"""Drenaż przed zamknięciem: stary kontener schodzi z routingu, zanim przestanie słuchać.

Rolling update (etap B2): Coolify zatrzymuje stary kontener ``docker stop``.
Uvicorn po SIGTERM od razu zamyka gniazdo nasłuchu, a Traefik jeszcze przez
chwilę kieruje tam ruch, więc żądanie dostawało 502. Middleware retry Traefika
nie ponawia POST/PATCH, czyli zapisów.

Z ``NEXUS_SHUTDOWN_DRAIN_SECONDS`` > 0 pierwszy SIGTERM tylko ustawia stan
„drenaż”: ``/api/health/live`` zwraca 503, Docker oznacza kontener jako
``unhealthy``, a Traefik pomija kontenery, które nie są ``healthy``
(``pkg/provider/docker/config.go``). Proces dalej obsługuje żądania i dopiero
po N sekundach oddaje sygnał uvicornowi, który kończy żądania w toku
(``UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN``). Drugi SIGTERM zamyka od razu.

Wymaga sondy Dockera częstszej niż drenaż i ``stop_grace_period`` dłuższego
niż drenaż + łagodne zamknięcie. → docs/claude/podstawy/przerwa-przy-wdrozeniu.md
"""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
from types import FrameType

logger = logging.getLogger(__name__)

_draining = threading.Event()


def is_draining() -> bool:
    return _draining.is_set()


def install_shutdown_drain(seconds: float, loop: asyncio.AbstractEventLoop) -> bool:
    """Owiń obsługę SIGTERM uvicorna. ``False`` = nic nie zmieniono.

    Wołane w lifespanie, czyli po ``Server.capture_signals`` uvicorna: wtedy
    ``signal.getsignal`` zwraca jego ``handle_exit``. Bez uvicorna (testy,
    skrypty) albo poza głównym wątkiem nie ma czego owijać.
    """
    if seconds <= 0 or threading.current_thread() is not threading.main_thread():
        return False
    previous = signal.getsignal(signal.SIGTERM)
    if not callable(previous):
        return False

    def _hand_over(sig: int) -> None:
        logger.info("shutdown drain: koniec drenażu, zamykam serwer")
        previous(sig, None)

    def _on_sigterm(sig: int, frame: FrameType | None) -> None:
        if _draining.is_set():
            previous(sig, frame)
            return
        _draining.set()
        loop.call_soon_threadsafe(_start_drain, sig)

    def _start_drain(sig: int) -> None:
        logger.info("shutdown drain: SIGTERM, %.0f s obsługi bez nowych sond", seconds)
        loop.call_later(seconds, _hand_over, sig)

    signal.signal(signal.SIGTERM, _on_sigterm)
    return True
