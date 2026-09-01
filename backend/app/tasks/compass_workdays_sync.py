"""Cykliczne zaciąganie dni roboczych z COMPASSA (decyzja D5).

Pętla budzi się co ``COMPASS_WORKDAYS_SYNC_INTERVAL_SECONDS`` i odświeża
ostatnie ``COMPASS_WORKDAYS_LOOKBACK_MONTHS`` miesięcy. Okno wsteczne nie jest
ostrożnością na wyrost: w produkcji COMPASSA widnieją wnioski z adnotacją
„urlop wypisany post factum", więc miesiąc zamknięty potrafi jeszcze zmienić
liczbę dni. Sam bieżący miesiąc by ich nie dogonił.

Zapis jest idempotentny (``ON CONFLICT`` po parze user × miesiąc), więc
powtórzone przebiegi nadpisują, a nie dublują.
"""

import asyncio
import logging
from datetime import timedelta

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.services.insights_workdays import sync_workdays

logger = logging.getLogger(__name__)

# Dolny próg odstępu. Bez niego literówka w env (np. 60) zamieniłaby COMPASSA
# w cel odpytywany co minutę.
_MIN_INTERVAL_SECONDS = 900

# Ile tygodni wstecz odswiezamy. Power Calling raportuje domyslnie POPRZEDNI
# tydzien, a wnioski urlopowe bywaja akceptowane wstecznie — samo biezace
# okno by ich nie dogonilo.
_WEEKS_BACK = 6


def _first_of_month(d):
    return d.replace(day=1)


def _shift_months(d, months: int):
    total = (d.year * 12 + (d.month - 1)) + months
    return d.replace(year=total // 12, month=total % 12 + 1, day=1)


async def compass_workdays_sync_loop() -> None:
    """Pętla tła. Kończy się PRZED pierwszym odczekaniem, gdy wyłączona.

    Świadomie nie budzi się co interwał tylko po to, żeby sprawdzić tę samą
    flagę — to był wzorzec z CloudTalka, gdzie proces wstawał co 60 s wyłącznie
    po to, by natychmiast zasnąć.
    """
    if not settings.COMPASS_WORKDAYS_ENABLED:
        logger.info("compass_workdays_sync disabled — pętla nie startuje")
        return
    if not settings.COMPASS_WORKDAYS_URL or not settings.COMPASS_WORKDAYS_SECRET:
        logger.warning("compass_workdays_sync misconfigured — brak URL albo sekretu")
        return

    interval = max(
        _MIN_INTERVAL_SECONDS, int(settings.COMPASS_WORKDAYS_SYNC_INTERVAL_SECONDS)
    )
    lookback = max(1, int(settings.COMPASS_WORKDAYS_LOOKBACK_MONTHS))

    while True:
        try:
            # `business_today()`, nie `date.today()`: okna liczymy kalendarzem
            # Europe/Warsaw, a zegar kontenera chodzi w UTC.
            today = business_today()
            date_to = _first_of_month(today)
            date_from = _shift_months(date_to, -(lookback - 1))

            # Dwie granulacje, bo dwa różne raporty: wskaźniki MD liczą
            # MIESIĄC, a Power Calling TYDZIEŃ ISO. Jedno źródło, dwa okna —
            # przybliżanie tygodnia z miesięcznej średniej byłoby zgadywaniem.
            week_from = today - timedelta(weeks=_WEEKS_BACK)
            async with AsyncSessionLocal() as db:
                months = await sync_workdays(db, date_from, date_to, bucket="month")
                weeks = await sync_workdays(db, week_from, today, bucket="week")

            for label, result in (("month", months), ("week", weeks)):
                logger.info(
                    "compass_workdays_sync done bucket=%s rows=%s matched=%s "
                    "unmatched_compass=%s nexus_without_compass=%s error=%s",
                    label,
                    result.rows_written,
                    result.matched_users,
                    len(result.unmatched_compass_emails),
                    len(result.nexus_users_without_compass),
                    result.error,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla ma przeżyć awarię COMPASSA
            logger.exception("compass_workdays_sync failed: %s", exc)

        await asyncio.sleep(interval)


__all__ = ["compass_workdays_sync_loop"]
