"""Terminy wejścia i odejścia — dni robocze firmy, 18:00, dzień po ostatnim dniu.

Czyste funkcje, bez bazy. Przykład z makiety: start w poniedziałek 2.11.2026,
zadanie recepcji „2 dni robocze przed startem” wypada w czwartek 29.10.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.hr.calendar import WorkCalendar
from app.services.hr.lifecycle_dates import (
    deactivate_on_for,
    deactivation_due,
    handover_due,
    shift_working_days,
)

WARSAW = ZoneInfo("Europe/Warsaw")
PLAIN = WorkCalendar()


@pytest.mark.parametrize(
    ("anchor", "offset", "expected"),
    [
        # Makieta: pon 2.11 − 2 dni robocze = czw 29.10 (pt 30.10 to pierwszy).
        (date(2026, 11, 2), -2, date(2026, 10, 29)),
        # 11.11 (Święto Niepodległości) wypada — wt 10.11 + 1 = czw 12.11.
        (date(2026, 11, 10), 1, date(2026, 11, 12)),
        # Przez weekend: pt 30.10 + 1 = pon 2.11 (1.11 to też niedziela).
        (date(2026, 10, 30), 1, date(2026, 11, 2)),
        # Przez Boże Narodzenie: śr 23.12 + 1 = pon 28.12.
        (date(2026, 12, 23), 1, date(2026, 12, 28)),
        # Przesunięcie zero to sama data wybrana przez Kadry, nawet w sobotę.
        (date(2026, 10, 31), 0, date(2026, 10, 31)),
        # Miesiąc po starcie: 21 dni roboczych od pon 2.11 (bez 11.11).
        (date(2026, 11, 2), 21, date(2026, 12, 2)),
    ],
)
def test_task_deadline_counts_company_working_days(anchor, offset, expected) -> None:
    assert shift_working_days(PLAIN, anchor, offset) == expected


def test_company_day_off_is_skipped_like_a_holiday() -> None:
    calendar = WorkCalendar(company_days_off={date(2026, 10, 29): "Dzień firmy"})
    assert shift_working_days(calendar, date(2026, 11, 2), -2) == date(2026, 10, 28)


def test_account_closes_the_calendar_day_after_the_last_working_day() -> None:
    assert deactivate_on_for(date(2026, 11, 30)) == date(2026, 12, 1)
    # Ostatni dzień w piątek → wyłączenie w sobotę, nie w poniedziałek.
    assert deactivate_on_for(date(2026, 11, 27)) == date(2026, 11, 28)
    assert not deactivation_due(date(2026, 12, 1), date(2026, 11, 30))
    assert deactivation_due(date(2026, 12, 1), date(2026, 12, 1))


def test_handover_waits_for_18_00_warsaw_time_of_the_last_day() -> None:
    last_day = date(2026, 11, 30)
    assert not handover_due(last_day, datetime(2026, 11, 30, 17, 59, tzinfo=WARSAW))
    assert handover_due(last_day, datetime(2026, 11, 30, 18, 0, tzinfo=WARSAW))
    # 17:00 UTC w listopadzie to 18:00 w Warszawie — liczy się czas firmy.
    assert handover_due(last_day, datetime(2026, 11, 30, 17, 0, tzinfo=timezone.utc))
    assert not handover_due(
        last_day, datetime(2026, 11, 30, 16, 59, tzinfo=timezone.utc)
    )
    # Dzień wcześniej wieczorem — jeszcze nie.
    assert not handover_due(last_day, datetime(2026, 11, 29, 23, 0, tzinfo=WARSAW))
