"""Definicje „Odpowiedź klienta w 7 dni” i „Pierwsze CV po otwarciu”.

Czyste funkcje: dni robocze, kohorta, rekrutacje masowe. Zapytania na bazie
sprawdza `test_client_response_metrics_db.py`.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.client_response_metrics import (
    MASS_REQUEST_MIN_CV,
    OpenedJob,
    SentCv,
    WaitingCv,
    response_window,
    responded_in_time,
    summarize_first_cv,
    summarize_responses,
    workdays_after,
)
from app.services.hr.calendar import WorkCalendar, calendar_from_days

CALENDAR = WorkCalendar()
TODAY = date(2026, 11, 8)  # niedziela


def _cv(
    sent: date,
    responded: date | None = None,
    *,
    client: int = 1,
    job: int = 10,
    job_cv: int = 1,
) -> SentCv:
    return SentCv(
        client_id=client,
        client_name=f"Klient {client}",
        job_id=job,
        sent_on=sent,
        responded_on=responded,
        job_cv_count=job_cv,
    )


def _job(
    opened: date,
    cv: date | None = None,
    *,
    moved: date | None = None,
    verified: date | None = None,
    job: int = 1,
) -> OpenedJob:
    return OpenedJob(
        job_id=job,
        opened_on=opened,
        first_moved_on=moved,
        first_verified_on=verified,
        first_cv_on=cv,
    )


def test_workdays_after_excludes_start_and_counts_end() -> None:
    assert workdays_after(CALENDAR, date(2026, 10, 12), date(2026, 10, 12)) == 0
    assert workdays_after(CALENDAR, date(2026, 10, 12), date(2026, 10, 13)) == 1
    # Piątek → poniedziałek to jeden dzień roboczy.
    assert workdays_after(CALENDAR, date(2026, 10, 16), date(2026, 10, 19)) == 1


def test_workdays_after_is_zero_when_event_precedes_start() -> None:
    assert workdays_after(CALENDAR, date(2026, 10, 13), date(2026, 10, 12)) == 0


def test_holiday_is_not_a_workday() -> None:
    # 11.11.2026 (środa) to święto: wtorek → czwartek = 1 dzień roboczy.
    assert workdays_after(CALENDAR, date(2026, 11, 10), date(2026, 11, 12)) == 1


def test_company_day_off_is_not_a_workday() -> None:
    calendar = calendar_from_days([(date(2026, 10, 14), "Dzień firmy")])
    assert workdays_after(calendar, date(2026, 10, 13), date(2026, 10, 15)) == 1


def test_response_window_ends_when_seven_workdays_have_passed() -> None:
    start, end = response_window(CALENDAR, TODAY)
    assert end == date(2026, 10, 28)
    assert workdays_after(CALENDAR, end, TODAY) == 7
    # Dzień później byłoby już tylko 6 dni na odpowiedź.
    assert workdays_after(CALENDAR, end + timedelta(days=1), TODAY) == 6
    # Przed 12.10.2026 etapów klienta nikt nie prowadził w NEXUSIE.
    assert start == date(2026, 10, 12)


def test_response_window_is_four_weeks_long_later_on() -> None:
    start, end = response_window(CALENDAR, date(2027, 2, 15))
    assert (end - start).days == 27


def test_response_on_seventh_workday_counts_and_on_eighth_does_not() -> None:
    sent = date(2026, 10, 12)
    assert responded_in_time(CALENDAR, _cv(sent, date(2026, 10, 21)))
    assert not responded_in_time(CALENDAR, _cv(sent, date(2026, 10, 22)))


def test_seven_workdays_are_longer_than_seven_calendar_days() -> None:
    # 12 dni kalendarzowych, w tym dwa weekendy i święto 11.11, to 7 roboczych.
    assert responded_in_time(CALENDAR, _cv(date(2026, 11, 6), date(2026, 11, 18)))


def test_cv_without_response_stays_in_the_denominator() -> None:
    summary = summarize_responses(
        [_cv(date(2026, 10, 12), date(2026, 10, 14)), _cv(date(2026, 10, 13))],
        [],
        CALENDAR,
        TODAY,
    )
    assert summary.cohort_cv == 2
    assert summary.responded_7d == 1
    assert summary.response_7d_pct == 50.0


def test_cv_too_fresh_for_seven_workdays_is_not_counted() -> None:
    summary = summarize_responses([_cv(date(2026, 11, 2))], [], CALENDAR, TODAY)
    assert summary.cohort_cv == 0
    assert summary.response_7d_pct is None


def test_no_cv_at_all_gives_none_not_zero() -> None:
    summary = summarize_responses([], [], CALENDAR, TODAY)
    assert summary.response_7d_pct is None
    assert summary.clients == []


def test_mass_request_leaves_the_rate_but_is_reported() -> None:
    mass = [
        _cv(date(2026, 10, 12), job=99, client=2, job_cv=MASS_REQUEST_MIN_CV)
        for _ in range(18)
    ]
    normal = [_cv(date(2026, 10, 13), date(2026, 10, 15), job=10)]
    summary = summarize_responses(mass + normal, [], CALENDAR, TODAY)
    assert summary.cohort_cv == 1
    assert summary.response_7d_pct == 100.0
    assert summary.excluded_mass_jobs == 1
    assert summary.excluded_mass_cv == 18


def test_job_just_below_mass_threshold_stays() -> None:
    rows = [_cv(date(2026, 10, 12), job=99, job_cv=MASS_REQUEST_MIN_CV - 1)]
    summary = summarize_responses(rows, [], CALENDAR, TODAY)
    assert summary.cohort_cv == 1
    assert summary.excluded_mass_jobs == 0


def test_client_table_counts_waiting_and_oldest_in_workdays() -> None:
    waiting = [
        WaitingCv(client_id=1, client_name="Klient 1", entered_on=date(2026, 10, 19)),
        WaitingCv(client_id=1, client_name="Klient 1", entered_on=date(2026, 11, 2)),
    ]
    summary = summarize_responses([], waiting, CALENDAR, TODAY)
    row = summary.clients[0]
    assert summary.cv_in_progress == 2
    assert row.cv_in_progress == 2
    assert row.oldest_waiting_workdays == workdays_after(
        CALENDAR, date(2026, 10, 19), TODAY
    )
    assert row.response_7d_pct is None


def test_client_table_puts_lowest_rate_first_and_small_samples_last() -> None:
    sent = [_cv(date(2026, 10, 12), client=1, job=1) for _ in range(5)]
    sent += [
        _cv(date(2026, 10, 12), date(2026, 10, 13), client=2, job=2) for _ in range(5)
    ]
    # Jedno CV bez odpowiedzi: 0%, ale z 1 CV nic to nie mówi.
    sent += [_cv(date(2026, 10, 12), client=3, job=3)]
    summary = summarize_responses(sent, [], CALENDAR, TODAY)
    assert [row.client_id for row in summary.clients] == [1, 2, 3]


def test_first_cv_median_counts_workdays_from_opening() -> None:
    summary = summarize_first_cv(
        [
            _job(date(2026, 10, 12), date(2026, 10, 14), job=1),
            _job(date(2026, 10, 12), date(2026, 10, 16), job=2),
            _job(date(2026, 10, 12), job=3),
        ],
        CALENDAR,
        TODAY,
    )
    assert summary.opened_jobs == 3
    assert summary.jobs_with_cv == 2
    assert summary.jobs_without_cv == 1
    assert summary.median_first_cv_workdays == 3.0


def test_first_cv_same_day_is_zero_and_weekend_opening_counts_from_monday() -> None:
    summary = summarize_first_cv(
        [_job(date(2026, 10, 17), date(2026, 10, 19))],  # sobota → poniedziałek
        CALENDAR,
        TODAY,
    )
    assert summary.median_first_cv_workdays == 1.0
    same_day = summarize_first_cv(
        [_job(date(2026, 10, 19), date(2026, 10, 19))], CALENDAR, TODAY
    )
    assert same_day.median_first_cv_workdays == 0.0


def test_first_cv_without_any_cv_has_no_median() -> None:
    summary = summarize_first_cv([_job(date(2026, 10, 12))], CALENDAR, TODAY)
    assert summary.median_first_cv_workdays is None
    assert summary.sla_pct == 0.0


def test_first_cv_sla_skips_jobs_younger_than_five_workdays() -> None:
    summary = summarize_first_cv(
        [
            _job(date(2026, 10, 12), date(2026, 10, 15), job=1),
            _job(date(2026, 10, 12), date(2026, 10, 26), job=2),
            _job(date(2026, 11, 5), job=3),  # 1 dzień roboczy temu
        ],
        CALENDAR,
        TODAY,
    )
    assert summary.sla_eligible_jobs == 2
    assert summary.sla_within_jobs == 1
    assert summary.sla_pct == 50.0


def test_first_cv_trend_has_full_weeks_only() -> None:
    summary = summarize_first_cv(
        [_job(date(2026, 11, 2), date(2026, 11, 3))], CALENDAR, date(2026, 11, 4)
    )
    # Trwający tydzień (od 02.11) nie idzie na linię.
    assert summary.weeks[-1].week_start == date(2026, 10, 26)
    assert all(week.opened_jobs == 0 for week in summary.weeks)
    # Tygodni sprzed 12.10.2026 nie ma: 12.10, 19.10, 26.10.
    assert len(summary.weeks) == 3


def test_first_cv_trend_is_eight_weeks_once_history_allows() -> None:
    summary = summarize_first_cv([], CALENDAR, date(2027, 2, 15))
    assert len(summary.weeks) == 8
    assert summary.window_from == date(2027, 2, 15) - timedelta(days=56)


def test_first_cv_window_drops_jobs_before_nexus_start() -> None:
    summary = summarize_first_cv(
        [_job(date(2026, 10, 9), date(2026, 10, 13))], CALENDAR, TODAY
    )
    assert summary.window_from == date(2026, 10, 12)
    assert summary.opened_jobs == 0
