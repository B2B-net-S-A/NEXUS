"""Audyt 25.09.2026, runda 3 — konkursy i metryki pulpitu (R3-11…R3-16).

Testy bez bazy (sesje-atrapy, `monkeypatch`) biegną lokalnie; testy oznaczone
`needs_db` zasiewają dane w WŁASNYM, losowym roku (rankingi są globalne dla
okna, a testowa baza nie jest czyszczona) i sprawdza je CI.
"""

from __future__ import annotations

import os
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import competitions as competitions_api
from app.models.competition_winner import CompetitionType
from app.services import competitions
from app.services.competition_rules import TieGroup  # noqa: F401
from app.services.insights_scoring_config import SCORING_DEFAULTS

needs_db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS", "1") == "1"
    or not os.environ.get("DATABASE_URL")
    or "@localhost:5432/x" in os.environ.get("DATABASE_URL", ""),
    reason="wymaga PostgreSQL",
)

VIEWER = SimpleNamespace(id=1)


class _Result:
    def __init__(self, rows: list[object]):
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> "_Result":
        return self


def _ranked(rows: list[tuple[int, int, bool]]) -> list[competitions.RankedUser]:
    return [
        competitions.RankedUser(
            user_id=uid,
            name=f"Osoba {uid}",
            metric_value=value,
            extras={"qualified": qualified},
        )
        for uid, value, qualified in rows
    ]


async def _freeze_rows(monkeypatch, ctype: CompetitionType, period: str, ranked):
    """Zamrożenie na sesji-atrapie: (wiersze podium, szczegóły zamknięcia)."""
    monkeypatch.setattr(
        competitions, "compute_live", AsyncMock(return_value=deepcopy(ranked))
    )
    monkeypatch.setattr(competitions, "_period_closure", AsyncMock(return_value=None))
    monkeypatch.setattr(
        competitions, "snapshot_monthly_race_thresholds", AsyncMock(return_value=None)
    )
    added: list = []
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result([]), _Result([])]),
        add=added.append,
        commit=AsyncMock(),
    )
    await competitions.freeze_competition(db, ctype, period)
    winners = [a for a in added if a.__class__.__name__ == "CompetitionWinner"]
    closure = next(
        a for a in added if a.__class__.__name__ == "CompetitionPeriodClosure"
    )
    return winners, closure.details


# ── R3-13: podium na żywo == podium zamrożenia ─────────────────────────────


async def test_live_league_podium_equals_freeze_with_tie_and_unqualified_leader(
    monkeypatch,
) -> None:
    """Niezakwalifikowany lider i remis na 1. miejscu — ekran = wypłata.

    Do 25.09.2026 `/current` brało `ranked[:3]` dla Ligi: niezakwalifikowany
    lider stał na 1. miejscu z kwotą 5000 zł, a remis nie był oznaczony.
    """
    ctype = CompetitionType.quarterly_champions_recruiter
    period = "Q1 2026"
    ranked = _ranked([(1, 500, False), (2, 300, True), (3, 300, True), (4, 100, True)])
    monkeypatch.setattr(
        competitions_api, "get_scoring_config", AsyncMock(return_value=SCORING_DEFAULTS)
    )
    monkeypatch.setattr(
        competitions, "compute_live", AsyncMock(return_value=deepcopy(ranked))
    )

    live = await competitions_api._compute_current(None, ctype, period)
    winners, details = await _freeze_rows(monkeypatch, ctype, period, ranked)

    podium = [
        (e["rank"], e["user_id"], e["prize_pln"], e["tied"]) for e in live["top3"]
    ]
    assert podium == [(1, 2, 0, True), (2, 3, 0, True), (3, 4, 2000, False)]
    # Wypłata: miejsca remisu puste do decyzji admina, 3. miejsce z kwotą.
    paid = [(w.rank, w.user_id, w.prize_pln) for w in winners]
    assert paid == [(e[0], e[1], e[2]) for e in podium if not e[3]]
    assert [t["positions"] for t in details["ties"]] == [
        t["positions"] for t in live["ties"]
    ]
    assert live["ties"] == [{"positions": [1, 2], "user_ids": [2, 3]}]
    # Niezakwalifikowany zostaje w rankingu, ale nie na podium.
    assert [e["user_id"] for e in live["full_ranking"]] == [1, 2, 3, 4]
    assert 1 not in {e["user_id"] for e in live["top3"]}


async def test_live_monthly_podium_excludes_quarter_leader_and_hides_margin(
    monkeypatch,
) -> None:
    """Wyścig placementów: lider kwartału wykluczony, marża/h nie wycieka."""
    ctype = CompetitionType.monthly_placements
    period = "2026-08"
    ranked = _ranked([(1, 5, True), (2, 3, True), (3, 3, True), (4, 2, True)])
    exclusion = competitions.RaceExclusion(
        frozenset({1}), "live_quarter_to_month_end", "Q3 2026"
    )
    monkeypatch.setattr(
        competitions,
        "monthly_race_excluded_user_ids",
        AsyncMock(return_value=exclusion),
    )
    # Marża niepoliczalna u obu remisujących → remis do admina.
    monkeypatch.setattr(
        competitions,
        "placement_margin_per_hour_by_user",
        AsyncMock(
            return_value={
                2: {"margin_per_hour_sum": None, "placements": [{"x": 1}]},
                3: {"margin_per_hour_sum": None, "placements": [{"x": 2}]},
            }
        ),
    )
    monkeypatch.setattr(
        competitions, "compute_live", AsyncMock(return_value=deepcopy(ranked))
    )

    live = await competitions_api._compute_current(None, ctype, period)
    winners, details = await _freeze_rows(monkeypatch, ctype, period, ranked)

    assert [(e["user_id"], e["prize_pln"], e["tied"]) for e in live["top3"]] == [
        (2, 0, True),
        (3, 0, True),
        (4, 0, False),
    ]
    assert live["excluded_user_ids"] == [1] == details["excluded_user_ids"]
    assert winners and [(w.rank, w.user_id, w.prize_pln) for w in winners] == [
        (3, 4, 0)
    ]
    for entry in live["top3"] + live["full_ranking"]:
        assert "margin_per_hour_sum" not in entry
        assert "margin_placements" not in entry


async def test_live_monthly_podium_pays_the_first_non_excluded(monkeypatch) -> None:
    ctype = CompetitionType.monthly_placements
    ranked = _ranked([(1, 5, True), (2, 4, True), (3, 2, True)])
    monkeypatch.setattr(
        competitions,
        "monthly_race_excluded_user_ids",
        AsyncMock(
            return_value=competitions.RaceExclusion(
                frozenset({1}), "frozen_quarter", "Q3 2026"
            )
        ),
    )
    monkeypatch.setattr(
        competitions, "compute_live", AsyncMock(return_value=deepcopy(ranked))
    )
    live = await competitions_api._compute_current(None, ctype, "2026-08")
    winners, _ = await _freeze_rows(monkeypatch, ctype, "2026-08", ranked)

    assert live["top3"][0]["user_id"] == 2
    assert live["top3"][0]["prize_pln"] == competitions.MONTHLY_RACE_PRIZE_PLN
    assert [(w.rank, w.user_id, w.prize_pln) for w in winners][0] == (
        1,
        2,
        competitions.MONTHLY_RACE_PRIZE_PLN,
    )


async def test_current_rejects_malformed_period_with_422() -> None:
    with pytest.raises(HTTPException) as exc:
        await competitions_api.get_current(VIEWER, None, "monthly_placements", "2026-8")
    assert exc.value.status_code == 422
    assert "RRRR-MM" in exc.value.detail


# ── R3-14: POST /freeze waliduje okres ─────────────────────────────────────


@pytest.mark.parametrize(
    ("ctype", "period"),
    [
        ("monthly_placements", "2026-8"),
        ("monthly_placements", "Q2 2026"),
        ("monthly_recommendations", "2026-13"),
        ("quarterly_champions_dl", "2026-06"),
        ("quarterly_champions_recruiter", "Q5 2026"),
        ("quarterly_champions_recruiter", "2026-Q2"),
    ],
)
async def test_freeze_rejects_malformed_period(monkeypatch, ctype, period) -> None:
    freeze = AsyncMock(side_effect=AssertionError("must not freeze"))
    monkeypatch.setattr(competitions_api.comp_service, "freeze_competition", freeze)
    with pytest.raises(HTTPException) as exc:
        await competitions_api.freeze(VIEWER, None, ctype, period)
    assert exc.value.status_code == 422
    freeze.assert_not_awaited()


@pytest.mark.parametrize(
    ("ctype", "period"),
    [
        ("monthly_placements", "2026-09"),
        ("monthly_recommendations", "2026-10"),
        ("quarterly_champions_recruiter", "Q3 2026"),
        ("quarterly_champions_dl", "Q4 2026"),
    ],
)
async def test_freeze_refuses_a_period_that_has_not_ended(
    monkeypatch, ctype, period
) -> None:
    monkeypatch.setattr(competitions_api, "business_today", lambda: date(2026, 9, 30))
    freeze = AsyncMock(side_effect=AssertionError("must not freeze"))
    monkeypatch.setattr(competitions_api.comp_service, "freeze_competition", freeze)
    with pytest.raises(HTTPException) as exc:
        await competitions_api.freeze(VIEWER, None, ctype, period)
    assert exc.value.status_code == 409
    assert "jeszcze trwa" in exc.value.detail
    freeze.assert_not_awaited()


async def test_freeze_accepts_an_ended_period(monkeypatch) -> None:
    monkeypatch.setattr(competitions_api, "business_today", lambda: date(2026, 10, 1))
    frozen = AsyncMock(
        return_value=SimpleNamespace(
            saved_count=1, already_frozen=False, closure_status="frozen"
        )
    )
    monkeypatch.setattr(competitions_api.comp_service, "freeze_competition", frozen)
    for ctype, period in (
        ("monthly_placements", "2026-09"),
        ("quarterly_champions_recruiter", "Q3 2026"),
    ):
        body = await competitions_api.freeze(VIEWER, None, ctype, period)
        assert body["ok"] is True
    assert frozen.await_count == 2


def test_period_last_day_covers_year_end() -> None:
    q = CompetitionType.quarterly_champions_dl
    m = CompetitionType.monthly_placements
    assert competitions.period_last_day(q, "Q4 2026") == date(2026, 12, 31)
    assert competitions.period_last_day(q, "Q1 2026") == date(2026, 3, 31)
    assert competitions.period_last_day(m, "2026-12") == date(2026, 12, 31)
    assert competitions.period_last_day(m, "2028-02") == date(2028, 2, 29)


# ── R3-15: cel precyzji to procent ─────────────────────────────────────────


async def test_precision_target_above_100_is_rejected() -> None:
    from app.services import kpi_target_editor as editor

    with pytest.raises(editor.KpiTargetEditError) as exc:
        await editor.set_role_default(
            None,
            role="recruiter",
            kpi_id="monthly_precision",
            target_value=150,
            actor=VIEWER,
        )
    assert "od 0 do 100" in str(exc.value)
    with pytest.raises(editor.KpiTargetEditError):
        # Alias starego panelu to ta sama precyzja.
        editor._check_value(101, "monthly_precision")
    editor._check_value(100, "monthly_precision")
    # Inne cele nie są procentami.
    editor._check_value(150, "daily_first_verifications")


# ── R3-11: poprzedni okres = ten sam odcinek ───────────────────────────────


def test_previous_window_of_month_in_progress_is_the_same_days_last_month() -> None:
    from app.services.custom_metrics.windows import resolve_window

    prev = resolve_window("this_month", date(2026, 10, 3)).previous()
    assert prev.start_date == date(2026, 9, 1)
    assert prev.end_date == date(2026, 9, 4)  # half-open: 1–3 września


def test_previous_window_of_closed_month_is_the_whole_previous_month() -> None:
    from app.services.custom_metrics.windows import resolve_window

    prev = resolve_window("last_month", date(2026, 10, 3)).previous()
    assert prev.start_date == date(2026, 8, 1)
    assert prev.end_date == date(2026, 9, 1)


def test_previous_window_of_31st_never_reaches_into_the_current_month() -> None:
    from app.services.custom_metrics.windows import resolve_window

    prev = resolve_window("this_month", date(2026, 3, 31)).previous()
    assert prev.start_date == date(2026, 2, 1)
    assert prev.end_date == date(2026, 3, 1)


def test_previous_rolling_window_stays_the_same_length_back() -> None:
    from app.services.custom_metrics.windows import resolve_window

    window = resolve_window("last_30_days", date(2026, 10, 3))
    prev = window.previous()
    assert prev.end_date == window.start_date
    assert (prev.end_date - prev.start_date) == (window.end_date - window.start_date)


def test_previous_window_of_quarter_in_progress_matches_elapsed_days() -> None:
    from app.services.custom_metrics.windows import resolve_window

    prev = resolve_window("this_quarter", date(2026, 11, 10)).previous()
    assert prev.start_date == date(2026, 7, 1)
    # 1.10–10.11 = 41 dni → 1.07–10.08.
    assert prev.end_date == date(2026, 8, 11)


# ── R3-12: kwoty okresu liczone na jego koniec ─────────────────────────────


async def test_finance_metric_for_last_month_is_valued_on_its_last_day(
    monkeypatch,
) -> None:
    """„Marża w sierpniu" ≠ dzisiejsze MRR, gdy stawka zmieniła się we wrześniu."""
    from app.services.custom_metrics import engine
    from app.services.custom_metrics.definition import MetricDefinition
    from app.services.custom_metrics.windows import resolve_window

    contract = SimpleNamespace(
        client_id=7,
        start_date=date(2026, 1, 1),
        end_date=None,
        resolved_rate_client_currency="PLN",
        resolved_rate_candidate_currency="PLN",
    )
    asked: list[date] = []

    def fake_fold(items, on, _rates):
        asked.append(on)
        # Stawka podniesiona 1 września: sierpień 1000, wrzesień 1500.
        margin = 1500 if on >= date(2026, 9, 1) else 1000
        return SimpleNamespace(complete=True, margin=margin * len(list(items)))

    async def fake_rates(_db, wanted):
        return {day: {} for day in wanted}

    monkeypatch.setattr(engine, "fold_money", fake_fold)
    monkeypatch.setattr(engine, "rates_to_pln_by_date", fake_rates)
    monkeypatch.setattr(engine, "money", lambda v: float(v))
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result([contract])))

    today = date(2026, 9, 25)
    for group_by in ("none", "client"):
        if group_by == "client":
            monkeypatch.setattr(
                engine, "_labels", AsyncMock(return_value={7: "Klient"})
            )
        definition = MetricDefinition(
            source="finance", measure="margin", period="last_month", group_by=group_by
        )
        asked.clear()
        value, series, notes, _ = await engine._run_finance(
            db, definition, resolve_window("last_month", today), None
        )
        assert value == 1000.0
        assert set(asked) == {date(2026, 8, 31)}
        assert any("31.08.2026" in n for n in notes)
        if group_by == "client":
            assert series[0]["value"] == 1000.0

    # Okres w toku liczy się na dziś, bez dopisku o dacie.
    definition = MetricDefinition(
        source="finance", measure="margin", period="this_month"
    )
    asked.clear()
    value, _, notes, _ = await engine._run_finance(
        db, definition, resolve_window("this_month", today), None
    )
    assert value == 1500.0 and set(asked) == {today}
    assert not any("według stanu" in n for n in notes)


# ── R3-16: liga DL — rola DL także dodatkowa ───────────────────────────────


async def test_dl_league_user_query_accepts_secondary_delivery_lead_role(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        competitions,
        "dl_portfolio_counts",
        AsyncMock(return_value=({5: 4}, {5: 4})),
    )
    seen: list[str] = []

    async def fake_execute(stmt, *_a, **_k):
        seen.append(str(stmt.compile(compile_kwargs={"literal_binds": False})))
        return _Result([SimpleNamespace(id=5, name="DL dodatkowy")])

    db = SimpleNamespace(execute=fake_execute)
    ranked = await competitions._rank_dls_by_placements(
        db,
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    assert [r.user_id for r in ranked] == [5]
    assert "users.roles" in seen[0]


# ── Testy na bazie (CI) ────────────────────────────────────────────────────


def _year() -> int:
    return 3000 + int(uuid.uuid4().hex[:6], 16) % 900


@needs_db
async def test_changing_the_precision_target_after_the_snapshot_keeps_the_winner(
    monkeypatch,
) -> None:
    """Migawka progów okresu: zmiana celu precyzji nie przestawia zwycięzcy."""
    from app.core.database import AsyncSessionLocal
    from tests.test_competition_freeze_rules import _at, _job, _pair, _user

    from app.models.recruitment_pipeline import PipelineStage

    targets = {"daily_first_verifications": 4, "monthly_precision": 75}

    async def fake_org_target(_db, kpi_id, **_kw):
        return targets[kpi_id]

    monkeypatch.setattr(competitions, "resolve_org_target", fake_org_target)

    year = _year()
    period = f"{year}-02"
    async with AsyncSessionLocal() as db:
        many = await _user(db, "Dużo rekomendacji")
        precise = await _user(db, "Wysoka precyzja")
        job = await _job(db)
        # 19 z 25 = 76% precyzji, 19 rekomendacji.
        for i in range(25):
            stages = (PipelineStage.cv_sent,) if i < 19 else ()
            await _pair(
                db, user=many, job=job, at=_at(year, 2, 2 + i % 20), stages=stages
            )
        # 5 z 5 = 100% precyzji, 5 rekomendacji.
        for i in range(5):
            await _pair(
                db,
                user=precise,
                job=job,
                at=_at(year, 2, 3 + i),
                stages=(PipelineStage.cv_sent,),
            )
        await db.commit()

        snap = await competitions.snapshot_monthly_race_thresholds(db, period)
        await db.commit()
        assert snap.precision_pct == 75.0

        # HoR podnosi cel precyzji PO migawce — okres liczy się dalej progiem 75.
        targets["monthly_precision"] = 80
        again = await competitions.snapshot_monthly_race_thresholds(db, period)
        await db.commit()
        assert again.precision_pct == 75.0
        assert (
            await competitions.monthly_race_thresholds(db, period)
        ).precision_pct == 75.0
        # Okres bez migawki = progi bieżące.
        assert (
            await competitions.monthly_race_thresholds(db, f"{year}-03")
        ).precision_pct == 80.0

        podium = await competitions.freeze_competition(
            db, CompetitionType.monthly_recommendations, period
        )
        assert [(w.rank, w.user_id) for w in podium][0] == (1, many.id)


@needs_db
async def test_dl_league_counts_a_person_with_delivery_lead_as_secondary_role() -> None:
    from app.core.database import AsyncSessionLocal
    from tests.test_competition_freeze_rules import _at, _job, _pair, _user

    from app.models.recruitment_pipeline import PipelineStage
    from app.models.user import UserRole

    year = _year()
    async with AsyncSessionLocal() as db:
        dl = await _user(db, "DL jako rola dodatkowa", role=UserRole.recruiter)
        dl.roles = [UserRole.recruiter.value, UserRole.delivery_lead.value]
        recruiter = await _user(db, "Rekruter")
        jobs = [
            await _job(db, dl_id=dl.id, closed_at=_at(year, 2, 20)) for _ in range(4)
        ]
        for job in jobs[:3]:
            await _pair(
                db,
                user=recruiter,
                job=job,
                at=_at(year, 2, 5),
                stages=(PipelineStage.cv_sent, PipelineStage.hired),
            )
        await db.commit()

        ranked = await competitions.quarterly_champions_dl(db, f"Q1 {year}")
        assert dl.id in {r.user_id for r in ranked}
