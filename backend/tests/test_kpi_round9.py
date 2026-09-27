"""Runda 9 audytu — KPI, konkursy i raporty mailem (R9-N6-4…6, R9-X1-9)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.services import competitions
from app.services.kpi_catalog import KpiPeriod
from app.services.kpi_coach_service import is_in_quiet_hours
from app.services.kpi_engine import expected_progress_ratio
from app.tasks import competition_autofreeze

WARSAW = ZoneInfo("Europe/Warsaw")


# ── R9-N6-4: okresy konkursów sortowane chronologicznie ───────────────────


def test_period_sort_key_orders_quarters_across_years() -> None:
    periods = ["Q4 2025", "Q1 2026", "Q3 2025", "Q2 2026"]
    assert sorted(periods, key=competitions.period_sort_key, reverse=True) == [
        "Q2 2026",
        "Q1 2026",
        "Q4 2025",
        "Q3 2025",
    ]
    months = ["2025-12", "2026-01", "2025-11"]
    assert sorted(months, key=competitions.period_sort_key)[-1] == "2026-01"
    # Nieznany format na końcu (najstarszy), bez wyjątku.
    assert sorted(["zły", "Q1 2026"], key=competitions.period_sort_key)[0] == "zły"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _winner(period: str, rank: int) -> SimpleNamespace:
    return SimpleNamespace(
        period=period,
        rank=rank,
        user_id=rank,
        metric_value=1,
        points=1,
        prize_pln=0,
        created_at=datetime(2026, 1, 1),
    )


@pytest.mark.asyncio
async def test_history_limit_keeps_the_newest_quarter() -> None:
    from app.api.competitions import get_history

    rows = [
        (_winner(period, rank), f"Osoba {rank}")
        for period in ("Q1 2026", "Q3 2025", "Q4 2025")
        for rank in (1, 2, 3)
    ]

    async def fake_execute(stmt, *_a, **_k):
        # Zapytanie nie może już ucinać LIMIT-em po napisie okresu.
        assert "LIMIT" not in str(stmt).upper()
        return _Rows(rows)

    out = await get_history(
        _user=None,
        db=SimpleNamespace(execute=fake_execute),
        type="quarterly_champions_recruiter",
        limit=2,
    )
    assert [p["period"] for p in out["periods"]] == ["Q1 2026", "Q4 2025"]


@pytest.mark.asyncio
async def test_hall_of_fame_history_keeps_the_newest_quarters(monkeypatch) -> None:
    from app.services import dashboard_v2_sources

    async def no_all_time(_db, limit=5):
        return []

    monkeypatch.setattr(competitions, "hall_of_fame", no_all_time)
    rows = [
        (_winner(period, 1), "Osoba")
        for period in ("Q1 2026", "Q2 2025", "Q3 2025", "Q4 2025", "Q2 2026")
    ]

    async def fake_execute(stmt, *_a, **_k):
        assert "LIMIT" not in str(stmt).upper()
        return _Rows(rows)

    out = await dashboard_v2_sources.load_hall_of_fame(
        SimpleNamespace(execute=fake_execute)
    )
    assert [p["period"] for p in out["history"]] == [
        "Q2 2026",
        "Q1 2026",
        "Q4 2025",
        "Q3 2025",
    ]


# ── R9-N6-5: HoR z rolą admin dostaje raport CAŁEGO zespołu ───────────────


@pytest.mark.asyncio
async def test_weekly_report_for_organization_scope_is_not_empty(monkeypatch) -> None:
    from app.analytics import metrics
    from app.services import access_scope
    from app.tasks import kpi_email_reports as reports

    hor = SimpleNamespace(id=1, email="hor-admin@example.com")

    async def recipients(_db, _roles):
        return [hor]

    async def scope(_user, _db):
        return access_scope.DashboardScope(
            kind=access_scope.ScopeKind.organization, user_id=1
        )

    seen: list[object] = []

    async def team_kpis(_db, _period, *, user_ids=None, operational_roles_only=True):
        seen.append(user_ids)
        return {"rows": [], "totals": {}}

    monkeypatch.setattr(reports, "_recipients", recipients)
    monkeypatch.setattr(access_scope, "resolve_dashboard_scope", scope)
    monkeypatch.setattr(metrics, "team_kpis", team_kpis)
    monkeypatch.setattr(reports, "render_weekly", lambda team, label: ("s", "t"))

    mails = await reports._weekly_mails(
        SimpleNamespace(), datetime(2026, 9, 28, 8, 5, tzinfo=WARSAW)
    )
    assert [m.to for m in mails] == ["hor-admin@example.com"]
    # `None` = cała organizacja; pusty zbiór byłby zakresem „nikt”.
    assert seen == [None]


# ── R9-N6-6 (a): święta nie są dniami roboczymi coacha ────────────────────


def test_coach_is_silent_on_public_holiday() -> None:
    # 3 maja 2027 (poniedziałek) — Święto Konstytucji.
    assert is_in_quiet_hours(datetime(2027, 5, 3, 10, 0, tzinfo=WARSAW)) is False
    assert is_in_quiet_hours(datetime(2027, 5, 4, 10, 0, tzinfo=WARSAW)) is True


def test_daily_kpi_expects_nothing_on_a_holiday() -> None:
    now = datetime(2027, 5, 3, 16, 0, tzinfo=WARSAW)
    assert expected_progress_ratio(KpiPeriod.day, now) == 0.0


def test_weekly_kpi_counts_only_business_days() -> None:
    # Tydzień 3–7.05.2027: poniedziałek wolny → 4 dni robocze.
    # Wtorek 17:30 = 1 z 4 (nie 2 z 5).
    now = datetime(2027, 5, 4, 17, 30, tzinfo=WARSAW)
    assert expected_progress_ratio(KpiPeriod.week, now) == pytest.approx(0.25)
    # Piątek koniec dnia = 100%.
    friday = datetime(2027, 5, 7, 17, 30, tzinfo=WARSAW)
    assert expected_progress_ratio(KpiPeriod.week, friday) == pytest.approx(1.0)


# ── R9-N6-6 (b): autofreeze przegląda okresy wstecz ───────────────────────


def test_closed_periods_lookback_oldest_first() -> None:
    today = date(2026, 1, 15)
    assert competition_autofreeze._closed_months(today, 3) == [
        "2025-10",
        "2025-11",
        "2025-12",
    ]
    assert competition_autofreeze._closed_quarters(today, 2) == ["Q3 2025", "Q4 2025"]


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def rollback(self):
        return None


@pytest.mark.asyncio
async def test_autofreeze_catches_up_a_missed_month(monkeypatch) -> None:
    monkeypatch.setattr(competition_autofreeze, "AsyncSessionLocal", _Session)
    # Wrzesień zamknięty, sierpień nie (import stał na przełomie miesięcy).
    closed = {"2026-09", "Q3 2026", "Q2 2026", "2026-07"}

    async def is_frozen(_db, _ctype, period):
        return period in closed

    async def ready(_db, *, period_last_day, period_end_utc, today):
        return SimpleNamespace(ready=True, reason=None, earliest_day=today)

    frozen: list[str] = []

    async def freeze(_db, ctype, period, *, reason):
        frozen.append(f"{ctype.value}:{period}")
        return competitions.FrozenPodium([], already_frozen=False)

    from app.services import competition_rules

    monkeypatch.setattr(competition_autofreeze, "_is_period_frozen", is_frozen)
    monkeypatch.setattr(competition_rules, "freeze_readiness", ready)
    monkeypatch.setattr(competitions, "freeze_competition", freeze)

    await competition_autofreeze._run_once(date(2026, 10, 20))
    assert frozen == [
        "monthly_recommendations:2026-08",
        "monthly_placements:2026-08",
    ]


@pytest.mark.asyncio
async def test_long_overdue_period_is_logged_as_warning(monkeypatch, caplog) -> None:
    async def is_frozen(_db, _ctype, _period):
        return False

    async def not_ready(_db, *, period_last_day, period_end_utc, today):
        return SimpleNamespace(
            ready=False, reason="traffit_pending", earliest_day=period_last_day
        )

    from app.services import competition_rules

    monkeypatch.setattr(competition_autofreeze, "_is_period_frozen", is_frozen)
    monkeypatch.setattr(competition_rules, "freeze_readiness", not_ready)
    caplog.set_level("INFO", logger=competition_autofreeze.logger.name)

    results: dict[str, int] = {}
    for period in ("2026-07", "2026-08"):
        await competition_autofreeze._freeze_if_ready(
            None,
            competitions.CompetitionType.monthly_placements,
            period,
            competition_autofreeze._month_period_end(period),
            date(2026, 9, 10),
            results,
        )
    levels = {
        r.getMessage().split(" postponed")[0]: r.levelname for r in caplog.records
    }
    assert levels["auto-freeze monthly_placements for 2026-07"] == "WARNING"
    assert levels["auto-freeze monthly_placements for 2026-08"] == "INFO"


# ── R9-X1-9: debug-fire-nudge po rollbacku nie czyta wygaszonego usera ────


@pytest.mark.asyncio
async def test_debug_fire_nudge_failure_returns_clean_500(monkeypatch) -> None:
    from app.api import kpis

    class _ExpiredAfterRollback:
        def __init__(self):
            self.rolled_back = False

        @property
        def id(self):
            if self.rolled_back:
                raise RuntimeError("MissingGreenlet: expired attribute")
            return 7

    user = _ExpiredAfterRollback()

    class _Db:
        async def scalar(self, _stmt):
            return user

        async def commit(self):
            return None

        async def rollback(self):
            user.rolled_back = True

    async def boom(*_a, **_k):
        raise RuntimeError("emit failed")

    monkeypatch.setattr(kpis.settings, "DEBUG", True)
    monkeypatch.setattr(kpis, "_try_emit_nudge", boom)

    with pytest.raises(HTTPException) as exc:
        await kpis.admin_debug_fire_nudge(None, target_user_id=7, db=_Db())
    assert exc.value.status_code == 500
