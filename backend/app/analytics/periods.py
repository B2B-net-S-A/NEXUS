"""Kanoniczne okresy analityczne (plan §4.2).

Wszystkie okresy:
- strefa ``Europe/Warsaw`` (kalendarz lokalny, nie rolling UTC),
- przedziały półotwarte ``[start, end)`` — timezone-aware,
- kalendarzowe granice dnia / tygodnia (pon.) / miesiąca / kwartału / roku,
- ``custom`` maksymalnie 366 dni.

Zero zależności od FastAPI — czysta logika, łatwa do unit-testów
(DST wiosna/jesień, rok przestępny, granice okresów).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

ANALYTICS_TIMEZONE = "Europe/Warsaw"
_TZ = ZoneInfo(ANALYTICS_TIMEZONE)

# Twardy limit długości okresu custom (plan §4.2): 366 dni — pełny rok
# przestępny, nic więcej.
MAX_CUSTOM_PERIOD_DAYS = 366


class PeriodKind(str, Enum):
    day = "day"
    week = "week"
    month = "month"
    quarter = "quarter"
    year = "year"
    custom = "custom"


class PeriodError(ValueError):
    """Nieprawidłowa definicja okresu — API mapuje na HTTP 422."""


@dataclass(frozen=True)
class Period:
    """Rozwiązany okres: [start, end) w Europe/Warsaw (aware datetimes)."""

    kind: PeriodKind
    start: datetime
    end: datetime

    @property
    def timezone(self) -> str:
        return ANALYTICS_TIMEZONE

    def as_payload(self) -> dict:
        """Sekcja ``period`` wspólnej koperty odpowiedzi (plan §4.5)."""
        return {
            "kind": self.kind.value,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "timezone": self.timezone,
        }


def _local_midnight(d: date) -> datetime:
    """Początek dnia kalendarzowego w Warszawie.

    ``ZoneInfo`` poprawnie obsługuje dni zmiany czasu (23h/25h) — północ
    zawsze istnieje w Europe/Warsaw (przejścia DST są o 2:00/3:00).
    """
    return datetime(d.year, d.month, d.day, tzinfo=_TZ)


def _today_warsaw(now: datetime | None = None) -> date:
    ref = now.astimezone(_TZ) if now else datetime.now(_TZ)
    return ref.date()


def resolve_period(
    kind: str | PeriodKind,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    now: datetime | None = None,
) -> Period:
    """Rozwiąż parametry requestu na kanoniczny ``Period``.

    - day/week/month/quarter/year → BIEŻĄCY okres kalendarzowy zawierający
      „teraz" (Warsaw); ``end`` to początek następnego okresu (może być
      w przyszłości — half-open pozwala liczyć okres w toku),
    - custom → wymaga ``date_from`` i ``date_to`` (dni kalendarzowe Warsaw,
      inclusive po stronie użytkownika → ``end`` = date_to + 1 dzień),
      maksymalnie MAX_CUSTOM_PERIOD_DAYS.

    Raises:
        PeriodError: nieznany kind, brak from/to dla custom, from > to,
            zakres dłuższy niż 366 dni.
    """
    try:
        period_kind = PeriodKind(kind)
    except ValueError:
        raise PeriodError(
            f"Nieznany rodzaj okresu: {kind!r}. Dozwolone: "
            f"{', '.join(k.value for k in PeriodKind)}"
        ) from None

    if period_kind is PeriodKind.custom:
        if date_from is None or date_to is None:
            raise PeriodError("Okres custom wymaga parametrów date_from i date_to")
        if date_from > date_to:
            raise PeriodError("date_from nie może być późniejszy niż date_to")
        span_days = (date_to - date_from).days + 1
        if span_days > MAX_CUSTOM_PERIOD_DAYS:
            raise PeriodError(
                f"Okres custom może mieć maksymalnie {MAX_CUSTOM_PERIOD_DAYS} dni "
                f"(zażądano {span_days})"
            )
        return Period(
            kind=period_kind,
            start=_local_midnight(date_from),
            end=_local_midnight(date_to + timedelta(days=1)),
        )

    today = _today_warsaw(now)

    if period_kind is PeriodKind.day:
        start_d = today
        end_d = today + timedelta(days=1)
    elif period_kind is PeriodKind.week:
        # Tydzień kalendarzowy pon.–niedz. (ISO).
        start_d = today - timedelta(days=today.weekday())
        end_d = start_d + timedelta(days=7)
    elif period_kind is PeriodKind.month:
        start_d = today.replace(day=1)
        end_d = (
            start_d.replace(year=start_d.year + 1, month=1)
            if start_d.month == 12
            else start_d.replace(month=start_d.month + 1)
        )
    elif period_kind is PeriodKind.quarter:
        q_month = 3 * ((today.month - 1) // 3) + 1
        start_d = date(today.year, q_month, 1)
        end_d = (
            date(today.year + 1, 1, 1)
            if q_month == 10
            else date(today.year, q_month + 3, 1)
        )
    elif period_kind is PeriodKind.year:
        start_d = date(today.year, 1, 1)
        end_d = date(today.year + 1, 1, 1)
    else:  # pragma: no cover — wyczerpane wyżej
        raise PeriodError(f"Unhandled period kind: {period_kind}")

    return Period(
        kind=period_kind,
        start=_local_midnight(start_d),
        end=_local_midnight(end_d),
    )
