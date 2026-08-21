"""
Timezone-aware scheduling helpers for Phase 13 notification triggers.

Stdlib (`zoneinfo`, `datetime`) + `holidays` dla polskiego kalendarza świąt.

Wszystkie funkcje są bezstanowe, deterministyczne dla danego `now`, więc łatwe
do testowania z `freezegun`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import holidays


DEFAULT_TZ = "Europe/Warsaw"


def local_now(tz: str = DEFAULT_TZ) -> datetime:
    """Timezone-aware "now" in the given zone. UTC on storage, local for gates."""
    return datetime.now(ZoneInfo(tz))


def business_today(tz: str = DEFAULT_TZ) -> date:
    """Dzisiejsza data według kalendarza, w którym pracuje firma.

    ``date.today()`` czyta zegar KONTENERA, a ten chodzi w UTC. Między północą
    UTC a północą warszawską (1 h latem, 2 h zimą) obie odpowiedzi się różnią —
    więc raport „dzisiejszy", alert deadline'owy i licznik miesięczny odpalone
    o 00:30 w Warszawie datują się wczorajszym dniem. Objaw jest cichy: liczba
    jest prawidłowa, tylko opisuje inny dzień.
    """
    return local_now(tz).date()


@dataclass(frozen=True)
class PeriodBounds:
    """Granice lokalnego okresu kalendarzowego przeliczone do UTC.

    Półotwarte: ``start_utc <= x < end_utc``. Domknięty koniec wymagałby
    „ostatniego mikrosekundy" i przy porównaniu z ``timestamptz`` gubi zdarzenia
    zapisane w tej mikrosekundzie.
    """

    start_utc: datetime
    end_utc: datetime


def _local_month_start(year: int, month: int, zone: ZoneInfo) -> datetime:
    return datetime.combine(date(year, month, 1), time.min, tzinfo=zone)


def local_month_bounds(day: date, tz: str = DEFAULT_TZ) -> PeriodBounds:
    """Miesiąc kalendarzowy, w którym leży ``day``, jako półotwarty zakres UTC.

    Po co, skoro można porównać kolumnę do ``date``: ``date.today()`` zestawione
    z kolumną ``timestamptz`` kompiluje się do ``$1::DATE`` i granica wypada
    o północy UTC sesji, nie o północy warszawskiej. Zdarzenia z pierwszych
    godzin pierwszego dnia miesiąca lądują wtedy w miesiącu poprzednim —
    i dwie powierzchnie liczące to samo (podium konkursu vs panel KPI tego
    samego rekrutera) podają różne liczby.
    """
    zone = ZoneInfo(tz)
    start = _local_month_start(day.year, day.month, zone)
    nxt = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    end = _local_month_start(nxt[0], nxt[1], zone)
    return PeriodBounds(
        start_utc=start.astimezone(timezone.utc),
        end_utc=end.astimezone(timezone.utc),
    )


def local_quarter_bounds(day: date, tz: str = DEFAULT_TZ) -> PeriodBounds:
    """Kwartał kalendarzowy, w którym leży ``day``, jako półotwarty zakres UTC."""
    zone = ZoneInfo(tz)
    first_month = 3 * ((day.month - 1) // 3) + 1
    start = _local_month_start(day.year, first_month, zone)
    end_year, end_month = (
        (day.year + 1, 1) if first_month == 10 else (day.year, first_month + 3)
    )
    end = _local_month_start(end_year, end_month, zone)
    return PeriodBounds(
        start_utc=start.astimezone(timezone.utc),
        end_utc=end.astimezone(timezone.utc),
    )


@dataclass(frozen=True)
class DayBounds:
    """UTC-aware start/end of a single local-calendar day in the given zone.

    Start = 00:00:00 local, end = 23:59:59.999999 local, both converted to UTC.
    Używane do filtrowania rekordów „z dzisiaj" (np. Call.created_at).
    """

    start_utc: datetime
    end_utc: datetime


def local_day_bounds(now: datetime, tz: str = DEFAULT_TZ) -> DayBounds:
    """Granice lokalnego dnia kalendarzowego przeliczone do UTC.

    Bezpieczne na DST: używamy `ZoneInfo`, który zwraca poprawny offset dla danego
    punktu w czasie (nie ma potrzeby ręcznej korekty o 1h).
    """
    zone = ZoneInfo(tz)
    local = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    today = local.date()
    start_local = datetime.combine(today, time.min, tzinfo=zone)
    end_local = datetime.combine(today, time.max, tzinfo=zone)
    return DayBounds(
        start_utc=start_local.astimezone(timezone.utc),
        end_utc=end_local.astimezone(timezone.utc),
    )


@lru_cache(maxsize=32)
def _polish_holidays(year: int) -> frozenset[date]:
    """Dni ustawowo wolne od pracy w RP dla danego roku.

    `frozenset` za `lru_cache` zamiast jednego modułowego `holidays.Poland()`:
    `HolidayBase` to podklasa `dict`, która dopopulowuje brakujące lata leniwie
    przy `in`, więc współdzielona instancja mogłaby się ścigać między wątkami
    threadpoola FastAPI. Tu populacja dzieje się raz per rok, a odczyt jest
    niemutowalny.
    """
    return frozenset(holidays.Poland(years=year).keys())


def is_business_day(moment: datetime, tz: str = DEFAULT_TZ) -> bool:
    """Dzień roboczy = Pon–Pt **i** nie polskie święto ustawowe.

    Święta są zawsze polskie (kalendarz firmowy) — `tz` decyduje wyłącznie o tym,
    na którą datę kalendarzową wypada `moment`, nie o tym, czyje święta liczymy.

    Ruchome święta (Poniedziałek Wielkanocny, Boże Ciało) i Wigilia — wolna
    ustawowo od 2025 — pochodzą z biblioteki `holidays`, żeby nie utrzymywać
    własnej tablicy dat. W 2026 daje to 8 świąt wypadających w dni tygodnia.
    """
    zone = ZoneInfo(tz)
    local = moment.astimezone(zone) if moment.tzinfo else moment.replace(tzinfo=zone)
    if local.weekday() >= 5:
        return False
    return local.date() not in _polish_holidays(local.year)


def is_within_window(
    now: datetime,
    *,
    hour: int,
    minute: int,
    window_minutes: int = 5,
    tz: str = DEFAULT_TZ,
) -> bool:
    """Czy `now` mieści się w oknie `[target - window, target + window]` lokalnie?

    Triggery z ostrym czasem (KPI 11:45, Client feedback 16:30) odpalamy tylko
    wtedy, gdy pętla trafia w okno. Reszta iteracji tego triggera jest pomijana.
    """
    zone = ZoneInfo(tz)
    local = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = abs((local - target).total_seconds())
    return delta <= window_minutes * 60


def seconds_until_local_time(
    now: datetime,
    hour: int,
    minute: int,
    tz: str = DEFAULT_TZ,
) -> float:
    """Ile sekund zostało do następnego wystąpienia `hour:minute` lokalnie.

    Jeśli cel minął już dziś → zwraca czas do jutra o tej samej porze.
    """
    zone = ZoneInfo(tz)
    local = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target = target + timedelta(days=1)
    return (target - local).total_seconds()


__all__ = [
    "DEFAULT_TZ",
    "DayBounds",
    "is_business_day",
    "is_within_window",
    "local_day_bounds",
    "local_now",
    "seconds_until_local_time",
]
