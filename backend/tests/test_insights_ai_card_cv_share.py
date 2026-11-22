"""Definicja kafelka „CV do klienta z karty AI” (decyzja Artura 22.11.2026).

Czyste funkcje: tygodnie firmy, licznik i mianownik. Zapytanie i trasę na bazie
sprawdza ``test_insights_ai_card_cv_share_db.py``.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.insights_ai_card_cv_share import (
    TARGET_PCT,
    WEEKS_SHOWN,
    CvSend,
    summarize_ai_card_cv_share,
    window_start,
)

WARSAW = ZoneInfo("Europe/Warsaw")
TODAY = date(2026, 11, 20)  # piątek; bieżący tydzień od 16.11


def _send(day: date, source: str | None, hour: int = 12) -> CvSend:
    return CvSend(
        sent_at=datetime.combine(day, time(hour), tzinfo=WARSAW), entry_source=source
    )


def test_window_is_current_week_and_four_before() -> None:
    assert window_start(TODAY) == date(2026, 10, 19)
    summary = summarize_ai_card_cv_share([], TODAY)
    assert [w.week_start for w in summary.weeks] == [
        date(2026, 10, 19),
        date(2026, 10, 26),
        date(2026, 11, 2),
        date(2026, 11, 9),
        date(2026, 11, 16),
    ]
    assert len(summary.weeks) == WEEKS_SHOWN
    assert summary.weeks[-1].in_progress is True
    assert not any(w.in_progress for w in summary.weeks[:-1])
    assert summary.weeks[0].week_end == date(2026, 10, 25)
    assert summary.target_pct == TARGET_PCT == 100


def test_empty_weeks_have_no_percentage_not_zero() -> None:
    summary = summarize_ai_card_cv_share([], TODAY)
    for week in summary.weeks:
        assert week.cv_sent == 0
        assert week.from_ai_card == 0
        # Brak wysyłek to „—”, nie 0% — inaczej wygląda jak porażka.
        assert week.share_pct is None


def test_counts_only_system_entry_as_ai_card() -> None:
    week = date(2026, 11, 9)
    sends = [
        _send(week, "system"),
        _send(week + timedelta(days=1), "system"),
        _send(week + timedelta(days=2), "added_manual"),
        _send(week + timedelta(days=3), "auto_match"),
        # Para bez procesu otwartego przed wysyłką.
        _send(week + timedelta(days=4), None),
    ]
    summary = summarize_ai_card_cv_share(sends, TODAY)
    row = next(w for w in summary.weeks if w.week_start == week)
    assert (row.cv_sent, row.from_ai_card, row.share_pct) == (5, 2, 40.0)


def test_week_boundary_is_warsaw_midnight_not_utc() -> None:
    # Niedziela 15.11, 23:30 w Warszawie = 22:30 UTC tego samego dnia;
    # poniedziałek 16.11, 00:30 w Warszawie = niedziela 23:30 UTC.
    sunday_late = CvSend(
        sent_at=datetime(2026, 11, 15, 22, 30, tzinfo=timezone.utc),
        entry_source="system",
    )
    monday_early = CvSend(
        sent_at=datetime(2026, 11, 15, 23, 30, tzinfo=timezone.utc),
        entry_source="system",
    )
    summary = summarize_ai_card_cv_share([sunday_late, monday_early], TODAY)
    by_start = {w.week_start: w for w in summary.weeks}
    assert by_start[date(2026, 11, 9)].cv_sent == 1
    assert by_start[date(2026, 11, 16)].cv_sent == 1


def test_sends_outside_window_are_ignored() -> None:
    sends = [
        _send(date(2026, 10, 18), "system"),  # niedziela przed oknem
        _send(date(2026, 11, 21), "system"),  # po „dziś”
        _send(date(2026, 10, 19), "system", hour=0),
    ]
    summary = summarize_ai_card_cv_share(sends, TODAY)
    assert sum(w.cv_sent for w in summary.weeks) == 1
    assert summary.weeks[0].share_pct == 100.0


def test_share_is_rounded_to_one_decimal() -> None:
    week = date(2026, 11, 16)
    sends = [_send(week, "system")] + [_send(week, "added_manual")] * 2
    summary = summarize_ai_card_cv_share(sends, TODAY)
    assert summary.weeks[-1].share_pct == 33.3
