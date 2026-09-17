"""Wydarzenia całodniowe: jedna reprezentacja dla ręcznych, Outlooka i iCal.

Do 09.2026 każde źródło zapisywało urlop/OOO jako 24-godzinny blok z
``all_day=False`` (sync M365 nie pytał Grapha o ``isAllDay``, iCal gubił
różnicę między ``date`` a ``datetime``). Siatka rysowała go na cały dzień,
zwężała rozmowy, zgłaszała fałszywe kolizje i budziła przypomnienie o 01:45.

Reprezentacja jest „pływającą datą": ``start_time`` = północ UTC dnia
rozpoczęcia, ``end_time`` = północ UTC dnia PO ostatnim dniu (koniec
wyłączny, jak w iCal i Graph). Front czyta z tych wartości same daty, więc
wpis nie przesuwa się o dzień między strefami czasowymi.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.config import settings

_ONE_DAY = timedelta(days=1)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _all_day_date(value: datetime, *, is_end: bool) -> date:
    """Data kalendarzowa wpisu całodniowego z dowolnej chwili.

    Północ UTC to już pływająca data (iCal, zapis z tego modułu). Północ
    w strefie biznesowej to data lokalna (Graph zwraca całodniowe wpisy
    w czasie UTC przesunięte o offset Warszawy). Każda inna godzina: dzień
    lokalny, a dla końca — dzień po nim, bo koniec jest wyłączny.
    """
    aware = _as_aware(value)
    utc_value = aware.astimezone(timezone.utc)
    if utc_value.time() == time(0):
        return utc_value.date()
    local = aware.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    if local.time() == time(0):
        return local.date()
    return local.date() + _ONE_DAY if is_end else local.date()


def _midnight_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def normalize_all_day(
    start: datetime, end: Optional[datetime]
) -> tuple[datetime, datetime]:
    """Sprowadź przedział wpisu całodniowego do pływających dat (koniec wyłączny).

    Brak końca albo koniec nie później niż start = jeden dzień.
    """
    start_day = _all_day_date(start, is_end=False)
    end_day = _all_day_date(end, is_end=True) if end is not None else None
    if end_day is None or end_day <= start_day:
        end_day = start_day + _ONE_DAY
    return _midnight_utc(start_day), _midnight_utc(end_day)
