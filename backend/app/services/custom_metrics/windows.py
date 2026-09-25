"""Okna czasowe własnej metryki: [start, end) w Europe/Warsaw + kubełki osi.

Kreator oferuje okresy „kroczące" (ostatnie 8 tygodni) i kalendarzowe (ten
miesiąc). Oba sprowadzamy do `app/analytics/periods.resolve_period`, żeby
granice miesiąca i strefa czasowa liczyły się tak samo jak w Insights.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.analytics.periods import ANALYTICS_TIMEZONE, Period, resolve_period
from app.services.insights_board_money import MONTH_LABELS_PL

_TZ = ZoneInfo(ANALYTICS_TIMEZONE)

_ROLLING_DAYS = {
    "last_7_days": 7,
    "last_30_days": 30,
    "last_8_weeks": 56,
    "last_12_weeks": 84,
    "last_90_days": 90,
    "last_12_months": 365,
}
_CALENDAR = {
    "this_month": ("month", 0),
    "last_month": ("month", -1),
    "this_quarter": ("quarter", 0),
    "this_year": ("year", 0),
}
PERIOD_LABELS_PL = {
    "last_7_days": "7 dni",
    "last_30_days": "30 dni",
    "last_8_weeks": "8 tygodni",
    "last_12_weeks": "12 tygodni",
    "last_90_days": "90 dni",
    "this_month": "ten miesiąc",
    "last_month": "poprzedni miesiąc",
    "this_quarter": "ten kwartał",
    "this_year": "ten rok",
    "last_12_months": "12 miesięcy",
}


@dataclass(frozen=True)
class Window:
    period: Period
    today: date

    @property
    def start(self) -> datetime:
        return self.period.start

    @property
    def end(self) -> datetime:
        return self.period.end

    @property
    def start_date(self) -> date:
        return self.period.start.date()

    @property
    def end_date(self) -> date:
        """Pierwszy dzień PO oknie (half-open)."""
        return self.period.end.date()

    @property
    def asof(self) -> date:
        """Dzień wyceny stanu okna: ostatni dzień okresu albo dziś, co wcześniej.

        „Marża w sierpniu" to stan z 31 sierpnia, a nie dzisiejsze MRR —
        stawka zmieniona we wrześniu nie może przepisać wyniku sierpnia.
        """
        return min(self.end_date - timedelta(days=1), self.today)

    def previous(self) -> "Window":
        """Poprzedni okres liczony TYM SAMYM odcinkiem co Insights.

        Okres w toku porównujemy z tymi samymi dniami poprzedniego okresu
        (1–3 października ↔ 1–3 września), zamknięty — z całym poprzednim.
        Do 25.09.2026 brało okno tej samej długości wstecz (1–3.10 ↔
        28–30.09), więc kafel z porównaniem pokazywał spadek, którego nie ma.
        Reguła jest jedna: `insights_team_signals.previous_matching_window`.
        """
        from app.services.insights_team_signals import previous_matching_window

        now = datetime.combine(self.today, time(12), tzinfo=_TZ)
        prev_start, prev_end = previous_matching_window(self.period, now)
        return Window(
            resolve_period(
                "custom",
                date_from=prev_start.date(),
                date_to=prev_end.date() - timedelta(days=1),
            ),
            self.today,
        )


def resolve_window(period_key: str, today: date) -> Window:
    if period_key in _ROLLING_DAYS:
        days = _ROLLING_DAYS[period_key]
        return Window(
            resolve_period(
                "custom", date_from=today - timedelta(days=days - 1), date_to=today
            ),
            today,
        )
    kind, offset = _CALENDAR[period_key]
    return Window(resolve_period(kind, offset=offset, anchor=today), today)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def time_buckets(window: Window, grain: str) -> list[tuple[str, str]]:
    """Wszystkie kubełki okna — także puste, żeby wykres nie gubił tygodni.

    Klucz = data początku kubełka (ISO), zgodna z ``date_trunc`` w SQL.
    """
    out: list[tuple[str, str]] = []
    last = window.end_date - timedelta(days=1)
    if grain == "week":
        cur = _week_start(window.start_date)
        while cur <= last:
            out.append((cur.isoformat(), f"{cur.day:02d}.{cur.month:02d}"))
            cur += timedelta(days=7)
        return out
    cur = window.start_date.replace(day=1)
    while cur <= last:
        out.append((cur.isoformat(), f"{MONTH_LABELS_PL[cur.month - 1]} {cur.year}"))
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return out


def month_end_snapshots(window: Window) -> list[tuple[str, str, date]]:
    """Dzień wyceny dla każdego miesiąca okna: ostatni dzień albo dziś."""
    out = []
    for key, label in time_buckets(window, "month"):
        first = date.fromisoformat(key)
        nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
        asof = min(nxt - timedelta(days=1), window.today)
        if asof < first:
            continue
        out.append((key, label, asof))
    return out
