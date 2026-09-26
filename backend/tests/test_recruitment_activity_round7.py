"""Runda 7 audytu (R7-N9-1, R7-N9-2, R7-N9-3): kafel „Aktywność rekrutacyjna”.

- Wynik zespołu liczy każdego z kredytem w oknie, także osoby nieaktywne
  i spoza ról KPI — lustro `kpi_team.compute_team_panel`.
- „Interview” = wyłącznie rozmowy u klienta (`client_interview`), decyzja
  właściciela 26.09.2026.
- Przegląd (pełne `VERIFIER_ANCHORED_CTE`) jest wspólny i trzymany w cache.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

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


@pytest.mark.asyncio
async def test_team_total_keeps_inactive_and_non_kpi_credit() -> None:
    head = _user(UserRole.head_of_recruitment, 1)
    recruiter = _user(UserRole.recruiter, 11)
    db = AsyncMock()
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
    # Średnia: 11, 21 i 31 (każdy z kredytem w oknie porównania).
    assert comparisons["placement"].people == 3
    assert comparisons["placement"].team_average == round(9 / (3 * 3), 1)


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
    db.execute.side_effect = [_result([head]), _result([])]
    db.scalar.return_value = 0

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

    count_sql, params = db.scalar.await_args.args
    assert "credit_user IS NOT NULL" in str(count_sql)
    assert "user_ids" not in params


@pytest.mark.asyncio
async def test_my_panel_interview_is_client_interview(monkeypatch) -> None:
    from datetime import datetime

    from app.services import kpi_panel

    async def _targets(_db, users, _ids):
        return {
            user.id: {
                "monthly_precision": 75,
                "daily_new_candidates": 0,
                "daily_first_verifications": 4,
                "monthly_placements": 1,
            }
            for user in users
        }

    monkeypatch.setattr(kpi_panel, "resolve_kpi_targets_bulk", _targets)
    recruiter = _user(UserRole.recruiter, 11)
    db = AsyncMock()
    db.execute.side_effect = [
        _result(
            [
                {"stage": "interview", "d": 5, "w": 5, "mo": 5, "r30": 0},
                {"stage": "client_interview", "d": 1, "w": 1, "mo": 2, "r30": 0},
            ]
        )
    ]

    panel = await kpi_panel.compute_my_panel(
        db, user=recruiter, now=datetime(2026, 9, 20, 12, tzinfo=kpi_panel.WARSAW)
    )

    assert panel.interview_month == 2


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
