"""Runda 7 audytu (R7-N9-1, R7-N9-2, R7-N9-3): kafel „Aktywność rekrutacyjna”.

- Wynik zespołu liczy każdego z kredytem w oknie, także osoby nieaktywne
  i spoza ról KPI — lustro `kpi_team.compute_team_panel`.
- „Interview” = wyłącznie rozmowy u klienta (`client_interview`), decyzja
  właściciela 26.09.2026.
- Przegląd (pełne `VERIFIER_ANCHORED_CTE`) jest wspólny i trzymany w cache.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core import cache as cache_module
from app.models.user import User, UserRole
from app.services import recruitment_activity as activity_service


def _user(role: UserRole, user_id: int) -> User:
    return User(
        id=user_id,
        email=f"activity-{user_id}@example.com",
        name=f"Osoba {user_id}",
        role=role,
        roles=[role.value],
        is_active=True,
        profile_completed=True,
    )


def _row(uid: int, stage: str, *, day: int = 0, month: int = 0, bench: int = 0):
    return {
        "credit_user": uid,
        "stage": stage,
        "day_count": day,
        "month_count": month,
        "benchmark_count": bench,
    }


def _empty_summary() -> dict:
    return {
        "total": 0,
        "people": 0,
        "moved_by_credited": 0,
        **{f"state_{name}": 0 for name in activity_service.DETAIL_STATES},
        "history_total": 0,
    }


def _result(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    result.scalars.return_value.all.return_value = rows
    return result


@pytest.fixture(autouse=True)
def _clean_cache():
    cache_module._cache.clear()
    yield
    cache_module._cache.clear()


@pytest.fixture(autouse=True)
def _empty_credited_snapshot(monkeypatch):
    """`db` jest tu atrapą z kolejką odpowiedzi — migawka `credited`
    (`credited_snapshot`, 27.10.2026) nie może zjadać z niej wyników."""
    from app.services import credited_snapshot

    async def _rows(_db):
        return ()

    monkeypatch.setattr(credited_snapshot, "credited_rows", _rows)


@pytest.mark.asyncio
async def test_team_total_keeps_inactive_and_non_kpi_credit() -> None:
    head = _user(UserRole.head_of_recruitment, 1)
    recruiter = _user(UserRole.recruiter, 11)
    db = AsyncMock()
    # Konta spoza list KPI z kredytem: 21 (nieaktywny rekruter) i 31 (admin).
    # R8-V2-3: zapytanie o zakres ról zwraca tylko admina.
    outside = MagicMock()
    outside.all.return_value = [(31,)]
    db.execute.side_effect = [
        # Aktywne konta — osoba 21 (nieaktywna) i 31 (admin) nie są na liście.
        _result([head, recruiter]),
        _result(
            [
                _row(11, "hired", month=2, bench=3),
                _row(21, "hired", month=3, bench=6),
                _row(31, "verified", month=4, bench=9),
            ]
        ),
        outside,
    ]

    result = await activity_service.build_recruitment_activity_summary(
        db,
        head,
        selected_day=date(2026, 8, 20),
        selected_month=date(2026, 8, 1),
        team_scope=True,
        today=date(2026, 9, 26),
    )

    by_metric = {metric.metric: metric for metric in result.metrics}
    assert by_metric["placement"].month == 5
    assert by_metric["verification"].month == 4
    comparisons = {item.metric: item for item in result.comparisons}
    # Średnia: 11 i 21 (każdy z kredytem w oknie porównania), bez konta
    # administracyjnego 31 (R8-V2-3). Suma miesiąca nadal liczy admina.
    assert comparisons["placement"].people == 2
    assert comparisons["placement"].team_average == round(9 / (2 * 3), 1)
    assert comparisons["verification"].team_average == 0.0


@pytest.mark.asyncio
async def test_interview_metric_counts_only_client_interviews() -> None:
    recruiter = _user(UserRole.recruiter, 11)
    no_rows = MagicMock()
    no_rows.all.return_value = []
    db = AsyncMock()
    db.execute.side_effect = [
        _result([recruiter]),
        _result(
            [
                _row(11, "interview", day=4, month=4),
                _row(11, "client_interview", day=1, month=2),
            ]
        ),
        no_rows,
        no_rows,
    ]

    result = await activity_service.build_recruitment_activity_summary(
        db,
        recruiter,
        selected_day=date(2026, 9, 2),
        selected_month=date(2026, 9, 1),
        today=date(2026, 9, 2),
    )

    by_metric = {metric.metric: metric for metric in result.metrics}
    assert by_metric["interview"].day == 1
    assert by_metric["interview"].month == 2
    sql = str(activity_service._OVERVIEW_SQL)
    tail = sql[sql.rindex("FROM credited") :]
    assert "'client_interview'" in tail
    assert "'interview'" not in tail
    assert activity_service._METRIC_STAGE["interview"] == "client_interview"


@pytest.mark.asyncio
async def test_overview_is_computed_once_for_two_viewers() -> None:
    first = _user(UserRole.recruiter, 11)
    second = _user(UserRole.recruiter, 12)
    overview = [_row(11, "verified", month=5), _row(12, "verified", month=7)]
    no_rows = MagicMock()
    no_rows.all.return_value = []

    db_first = AsyncMock()
    db_first.execute.side_effect = [
        _result([first, second]),
        _result(overview),
        no_rows,
        no_rows,
    ]
    db_second = AsyncMock()
    # Drugi oglądający: tylko lista osób i cel — bez ponownego przeglądu.
    db_second.execute.side_effect = [_result([first, second]), no_rows, no_rows]

    kwargs = {
        "selected_day": date(2026, 9, 2),
        "selected_month": date(2026, 9, 1),
        "today": date(2026, 9, 2),
    }
    first_result = await activity_service.build_recruitment_activity_summary(
        db_first, first, **kwargs
    )
    second_result = await activity_service.build_recruitment_activity_summary(
        db_second, second, **kwargs
    )

    assert {m.metric: m.month for m in first_result.metrics}["verification"] == 5
    assert {m.metric: m.month for m in second_result.metrics}["verification"] == 7
    assert db_second.execute.await_count == 3


@pytest.mark.asyncio
async def test_team_drilldown_is_not_limited_to_active_kpi_accounts() -> None:
    head = _user(UserRole.head_of_recruitment, 1)
    db = AsyncMock()
    summary = MagicMock()
    summary.mappings.return_value.one.return_value = _empty_summary()
    db.execute.side_effect = [_result([head]), summary]

    await activity_service.list_recruitment_activity_details(
        db,
        head,
        metric="placement",
        window="month",
        selected_day=date(2026, 8, 20),
        selected_month=date(2026, 8, 1),
        subject_user_id=None,
        team_scope=True,
        page=1,
        page_size=25,
    )

    summary_sql, params = db.execute.await_args.args
    assert "credit_user IS NOT NULL" in str(summary_sql)
    assert "user_ids" not in params


@pytest.mark.asyncio
async def test_my_panel_interview_is_client_interview(monkeypatch) -> None:
    from datetime import datetime

    from app.services import kpi_panel

    async def _targets(_db, users, _ids):
        return {
            user.id: {
                "monthly_precision": 75,
                "daily_first_verifications": 4,
                "monthly_placements": 1,
            }
            for user in users
        }

    monkeypatch.setattr(kpi_panel, "resolve_kpi_targets_bulk", _targets)
    recruiter = _user(UserRole.recruiter, 11)
    # „CV do bazy” liczy się rekruterowi zawsze (13.10.2026: sama liczba, bez
    # celu) — drugie zapytanie panelu, czytane przez `.mappings().one()`.
    cv_to_base = MagicMock()
    cv_to_base.mappings.return_value.one.return_value = {"d": 1, "w": 2, "mo": 3}
    db = AsyncMock()
    db.execute.side_effect = [
        _result(
            [
                {"stage": "interview", "d": 5, "w": 5, "mo": 5, "r30": 0},
                {"stage": "client_interview", "d": 1, "w": 1, "mo": 2, "r30": 0},
            ]
        ),
        cv_to_base,
    ]

    panel = await kpi_panel.compute_my_panel(
        db, user=recruiter, now=datetime(2026, 9, 20, 12, tzinfo=kpi_panel.WARSAW)
    )

    assert panel.interview_month == 2
    assert (panel.cv_to_base.day, panel.cv_to_base.week, panel.cv_to_base.month) == (
        1,
        2,
        3,
    )
    assert not hasattr(panel, "target_cv_added_daily")


@pytest.mark.asyncio
async def test_team_panel_interview_is_client_interview(monkeypatch) -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.services import kpi_team
    from app.services.kpi_catalog import KpiPeriod

    funnel = _result(
        [
            {"uid": 11, "stage": "interview", "period_cnt": 7, "r30_cnt": 0},
            {"uid": 11, "stage": "client_interview", "period_cnt": 3, "r30_cnt": 0},
        ]
    )
    cv = _result([])
    op_users = MagicMock()
    op_users.all.return_value = [
        SimpleNamespace(id=11, name="Osoba 11", role=UserRole.recruiter)
    ]
    db = AsyncMock()
    db.execute.side_effect = [funnel, cv, op_users]

    async def _org_target(_db, _kpi_id):
        return 75

    monkeypatch.setattr(kpi_team, "resolve_org_target", _org_target)

    result = await kpi_team.compute_team_panel(
        db,
        period=KpiPeriod.month,
        now=datetime(2026, 9, 20, 12, tzinfo=kpi_team.WARSAW),
    )

    assert result.totals.interview == 3
    assert result.rows[0].interview == 3


@pytest.mark.asyncio
async def test_admin_bulk_placements_do_not_inflate_the_team_average() -> None:
    """R8-V2-3: konto administracyjne z 10 domkniętymi placementami i dwóch
    rekruterów po 1 — średnia zespołu to 1 placement na 3 miesiące."""
    head = _user(UserRole.head_of_recruitment, 1)
    first = _user(UserRole.recruiter, 11)
    second = _user(UserRole.recruiter, 12)
    outside = MagicMock()
    outside.all.return_value = [(31,)]
    db = AsyncMock()
    db.execute.side_effect = [
        _result([head, first, second]),
        _result(
            [
                _row(11, "hired", bench=1),
                _row(12, "hired", bench=1),
                _row(31, "hired", month=10, bench=10),
            ]
        ),
        outside,
    ]

    result = await activity_service.build_recruitment_activity_summary(
        db,
        head,
        selected_day=date(2026, 8, 20),
        selected_month=date(2026, 8, 1),
        team_scope=True,
        today=date(2026, 9, 26),
    )

    comparisons = {item.metric: item for item in result.comparisons}
    assert comparisons["placement"].people == 2
    assert comparisons["placement"].team_average == round(2 / (2 * 3), 1)
    by_metric = {metric.metric: metric for metric in result.metrics}
    assert by_metric["placement"].month == 10


# ── Lista „Kto się liczy” (17.10.2026) ──────────────────────────────────────


def _summary(**overrides: int) -> MagicMock:
    summary = MagicMock()
    summary.mappings.return_value.one.return_value = {**_empty_summary(), **overrides}
    return summary


def _detail_row(**overrides) -> dict:
    row = {
        "candidate_id": 501,
        "candidate_name": "Anna Przykładowa",
        "job_id": 77,
        "job_title": "Java Developer (ZOB-1)",
        "job_working_title": "Senior Java Developer",
        "job_client_reference": "ZOB-1",
        "client_name": "Bank Przykładowy",
        "credit_user": 11,
        "credit_user_name": "Osoba 11",
        "credit_user_role": "recruiter",
        "reached_at": datetime(2026, 10, 15, 14, 5, tzinfo=timezone.utc),
        "mover_id": 21,
        "mover_name": "Osoba 21",
        "mover_role": "delivery_lead",
        "state": "waiting",
        "latest_stage": "cv_sent",
        "latest_at": datetime(2026, 10, 15, 14, 5, tzinfo=timezone.utc),
        "reason_name": None,
        "candidate_jobs": 2,
    }
    row.update(overrides)
    return row


async def _details(db, user, **kwargs):
    params = {
        "metric": "recommendation",
        "window": "week",
        "selected_day": date(2026, 10, 15),
        "selected_month": date(2026, 10, 1),
        "subject_user_id": None,
        "team_scope": False,
        "page": 1,
        "page_size": 25,
    }
    params.update(kwargs)
    return await activity_service.list_recruitment_activity_details(db, user, **params)


@pytest.mark.parametrize(
    ("window", "kwargs", "expected"),
    [
        # Środa → tydzień od poniedziałku, jak cel „Rekomendacje w tygodniu”.
        ("week", {}, (date(2026, 10, 12), date(2026, 10, 19))),
        ("day", {}, (date(2026, 10, 15), date(2026, 10, 16))),
        ("month", {}, (date(2026, 10, 1), date(2026, 11, 1))),
        (
            "range",
            {"date_from": date(2026, 10, 1), "date_to": date(2026, 10, 31)},
            (date(2026, 10, 1), date(2026, 11, 1)),
        ),
    ],
)
def test_detail_window_bounds(window, kwargs, expected) -> None:
    bounds = activity_service._detail_window(
        window,
        selected_day=date(2026, 10, 15),
        selected_month=date(2026, 10, 1),
        date_from=kwargs.get("date_from"),
        date_to=kwargs.get("date_to"),
    )
    assert bounds == expected


@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [
        (None, date(2026, 10, 31)),
        (date(2026, 10, 31), date(2026, 10, 1)),
        (date(2025, 1, 1), date(2026, 1, 2)),
    ],
)
def test_detail_range_rejects_missing_reversed_and_too_long(date_from, date_to) -> None:
    with pytest.raises(HTTPException) as exc:
        activity_service._detail_window(
            "range",
            selected_day=date(2026, 10, 15),
            selected_month=date(2026, 10, 1),
            date_from=date_from,
            date_to=date_to,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_recruiter_cannot_open_unattributed_rows() -> None:
    recruiter = _user(UserRole.recruiter, 11)
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await _details(db, recruiter, unattributed=True)
    assert exc.value.status_code == 403
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unattributed_scope_reads_rows_without_credit_user() -> None:
    head = _user(UserRole.head_of_recruitment, 1)
    db = AsyncMock()
    db.execute.side_effect = [_summary()]

    result = await _details(db, head, unattributed=True)

    summary_sql, params = db.execute.await_args.args
    assert "credited.credit_user IS NULL" in str(summary_sql)
    assert "user_ids" not in params
    assert result.scope == "unattributed"
    assert result.subject is None


@pytest.mark.asyncio
async def test_unattributed_scope_cannot_be_combined_with_a_person() -> None:
    head = _user(UserRole.head_of_recruitment, 1)
    with pytest.raises(HTTPException) as exc:
        await _details(AsyncMock(), head, unattributed=True, subject_user_id=11)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_leader_opens_a_person_outside_the_recruiter_list() -> None:
    """Zespół → Ludzie ma wiersze osób nieaktywnych i spoza ról KPI."""
    head = _user(UserRole.head_of_recruitment, 1)
    former = _user(UserRole.delivery_lead, 44)
    former.is_active = False
    db = AsyncMock()
    db.execute.side_effect = [_result([head]), _summary()]
    db.get.return_value = former

    result = await _details(db, head, subject_user_id=44)

    _, params = db.execute.await_args.args
    assert params["user_ids"] == [44]
    assert result.scope == "person"
    assert result.subject is not None and result.subject.id == 44


@pytest.mark.asyncio
async def test_recruiter_still_cannot_open_another_person() -> None:
    recruiter = _user(UserRole.recruiter, 11)
    db = AsyncMock()
    db.execute.side_effect = [_result([recruiter])]
    with pytest.raises(HTTPException) as exc:
        await _details(db, recruiter, subject_user_id=12)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_state_filter_pages_one_state_and_keeps_period_counts() -> None:
    recruiter = _user(UserRole.recruiter, 11)
    db = AsyncMock()
    page = MagicMock()
    page.mappings.return_value.all.return_value = [
        _detail_row(
            state="rejected_by_client", latest_stage="rejected", reason_name="Stawka"
        )
    ]
    db.execute.side_effect = [
        _result([recruiter]),
        _summary(
            total=23,
            people=21,
            moved_by_credited=7,
            state_waiting=11,
            state_rejected_by_client=5,
            state_at_client=7,
        ),
        page,
    ]

    result = await _details(db, recruiter, state="rejected_by_client")

    page_sql, page_params = db.execute.await_args.args
    assert page_params["state"] == "rejected_by_client"
    assert "CAST(:state AS text)" in str(page_sql)
    assert result.total == 5
    assert result.period_total == 23
    assert result.people == 21
    assert result.moved_by_credited == 7
    assert result.states == {"waiting": 11, "at_client": 7, "rejected_by_client": 5}
    assert result.period_start == date(2026, 10, 12)
    assert result.period_end == date(2026, 10, 18)
    assert result.items[0].state_reason == "Stawka"


@pytest.mark.asyncio
async def test_detail_row_names_the_job_like_its_header_and_who_clicked() -> None:
    recruiter = _user(UserRole.recruiter, 11)
    db = AsyncMock()
    page = MagicMock()
    page.mappings.return_value.all.return_value = [_detail_row()]
    db.execute.side_effect = [
        _result([recruiter]),
        _summary(total=1, people=1, state_waiting=1),
        page,
    ]

    result = await _details(db, recruiter)

    item = result.items[0]
    assert item.job.working_title == "Senior Java Developer"
    assert item.job.client_reference == "ZOB-1"
    assert item.job.href == "/jobs/77?candidate=501"
    assert item.moved_by is not None and item.moved_by.id == 21
    assert item.credited_user is not None and item.credited_user.id == 11
    assert item.candidate_jobs == 2
    assert item.state == "waiting"


@pytest.mark.asyncio
async def test_empty_period_skips_the_page_query() -> None:
    recruiter = _user(UserRole.recruiter, 11)
    db = AsyncMock()
    db.execute.side_effect = [_result([recruiter]), _summary()]

    result = await _details(db, recruiter)

    assert db.execute.await_count == 2
    assert result.total == 0 and result.items == []


def test_detail_states_match_the_response_contract() -> None:
    from typing import get_args

    from app.schemas.recruitment_activity import RecruitmentActivityState

    assert set(activity_service.DETAIL_STATES) == set(
        get_args(RecruitmentActivityState)
    )
    sql = str(activity_service._DETAIL_SQL["person"])
    # Odrzucenie przez klienta = ta sama reguła co `known_people_signal`.
    assert "latest.ended_by = 'client'" in sql
    assert "'cv_sent', 'client_interview'" in sql


@pytest.mark.asyncio
async def test_account_without_team_rights_gets_no_team_rows_by_default() -> None:
    """Rola „Automatyzacje” (0446) nie ma imiennych KPI zespołu.

    Bez `scope` i bez osoby lista spadała do zakresu zespołu, choć jawne
    `scope=team` dawało tej samej roli 403 (przegląd bezpieczeństwa 17.10.2026).
    """
    automation = _user(UserRole.automation, 61)
    db = AsyncMock()
    db.execute.side_effect = [_result([automation])]
    with pytest.raises(HTTPException) as exc:
        await _details(db, automation)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_account_without_team_rights_still_opens_its_own_rows() -> None:
    automation = _user(UserRole.automation, 61)
    db = AsyncMock()
    db.execute.side_effect = [_result([automation]), _summary()]

    result = await _details(db, automation, subject_user_id=61)

    _, params = db.execute.await_args.args
    assert params["user_ids"] == [61]
    assert result.scope == "person"


def test_week_at_the_end_of_the_calendar_is_a_422_not_a_500() -> None:
    with pytest.raises(HTTPException) as exc:
        activity_service._detail_window(
            "week",
            selected_day=date(9999, 12, 31),
            selected_month=date(9999, 12, 1),
            date_from=None,
            date_to=None,
        )
    assert exc.value.status_code == 422
