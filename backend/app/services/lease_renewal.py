"""Odnawianie dzierżawy zadania w tle, odporne na przejściowy błąd bazy.

Runda 7 (R7-N6-2): pętle odnowień generacji CV, kontroli treści CV i mapy
wymagań kończyły się pierwszym wyjątkiem z bazy (reset połączenia, timeout
puli). Wykonawca uznawał wtedy zadanie za utracone, wynik opłaconego wywołania
modelu przepadał, a rekruter płacił drugi raz. Dzierżawa trwa kilka minut, więc
jeden nieudany zapis niczego nie przesądza: ponawiamy do chwili, w której
dzierżawa na pewno wygasła. Kończy WYŁĄCZNIE jawne ``False`` (dzierżawę przejął
ktoś inny) albo upływ czasu dzierżawy od ostatniego udanego odnowienia.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

RENEW_INTERVAL_SECONDS = 30


async def renew_lease(
    heartbeat: Callable[[], Awaitable[bool]],
    *,
    lease_seconds: float,
    label: str,
    interval: float = RENEW_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Odnawiaj co ``interval`` s; rzuca ``RuntimeError`` przy utracie dzierżawy."""
    # Pesymistycznie: zegar liczymy od CHWILI WYWOŁANIA odnowienia (serwer
    # przesuwa wygaśnięcie o `lease_seconds` od swojego „teraz”, które jest
    # późniejsze).
    expires_at = clock() + lease_seconds
    while True:
        await asyncio.sleep(interval)
        attempted_at = clock()
        try:
            alive = await heartbeat()
        except Exception as exc:  # noqa: BLE001 — przejściowy błąd bazy
            if clock() >= expires_at:
                raise RuntimeError(f"{label} lease expired") from exc
            logger.warning(
                "[lease] %s renewal failed, retrying: %s", label, type(exc).__name__
            )
            continue
        if not alive:
            raise RuntimeError(f"{label} lease lost")
        expires_at = attempted_at + lease_seconds
