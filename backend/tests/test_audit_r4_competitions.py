"""Audyt 25.09.2026, runda 4 — konkursy (R4-14, R4-16).

R4-14: jedna numeracja rankingu — ta, którą wypłaca `award_order`. Lista pod
podium, `/my-position` i ranking Ligi na pulpicie nie mogą dawać „#1” osobie
niezakwalifikowanej, gdy podium ma innego zwycięzcę.

R4-16: punktacja Ligi Mistrzów (wagi i progi placementów) jest migawką
kwartału — zmiana konfiguracji po końcu kwartału nie przestawia Ligi ani
wykluczenia lidera kwartału z wyścigów miesięcznych.

Testy bez bazy biegną lokalnie; `needs_db` sprawdza CI (własny, losowy rok).
"""

from __future__ import annotations

import os
import uuid
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import competitions as competitions_api
from app.models.competition_winner import CompetitionType
from app.services import competitions
from app.services import dashboard_v2 as dashboard_v2_service
from app.services.insights_scoring_config import SCORING_DEFAULTS

needs_db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS", "1") == "1"
    or not os.environ.get("DATABASE_URL")
    or "@localhost:5432/x" in os.environ.get("DATABASE_URL", ""),
    reason="wymaga PostgreSQL",
)

LEAGUE = CompetitionType.quarterly_champions_recruiter


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


# ── R4-14: jedna numeracja ────────────────────────────────────────────────


async def test_current_list_has_no_second_number_one_for_unqualified_leader(
    monkeypatch,
) -> None:
    ranked = _ranked([(1, 900, False), (2, 300, True), (3, 200, True), (4, 150, True)])
    monkeypatch.setattr(
        competitions, "league_scoring_config", AsyncMock(return_value=SCORING_DEFAULTS)
    )
    monkeypatch.setattr(
        competitions, "compute_live", AsyncMock(return_value=deepcopy(ranked))
    )

    live = await competitions_api._compute_current(None, LEAGUE, "Q1 2026")

    ranks = [(e["user_id"], e["rank"]) for e in live["full_ranking"]]
    assert ranks == [(2, 1), (3, 2), (4, 3), (1, None)]
    assert [e["rank"] for e in live["full_ranking"]].count(1) == 1
    # Podium i lista mówią to samo.
    assert [(e["user_id"], e["rank"]) for e in live["top3"]] == ranks[:3]
    unranked = live["full_ranking"][-1]
    assert unranked["prize_pln"] is None and unranked["qualified"] is False


async def test_my_position_of_unqualified_leader_has_no_place(monkeypatch) -> None:
    ranked = _ranked([(1, 900, False), (2, 300, True), (3, 200, True)])
    monkeypatch.setattr(
        competitions, "compute_live", AsyncMock(return_value=deepcopy(ranked))
    )

    mine = await competitions_api.my_position(
        SimpleNamespace(id=1), None, LEAGUE.value, "Q1 2026"
    )
    assert mine["rank"] is None
    assert mine["me"]["user_id"] == 1 and mine["me"]["rank"] is None

    winner = await competitions_api.my_position(
        SimpleNamespace(id=2), None, LEAGUE.value, "Q1 2026"
    )
    assert winner["rank"] == 1
    assert [(e["user_id"], e["rank"]) for e in winner["context"]] == [
        (2, 1),
        (3, 2),
        (1, None),
    ]


async def test_my_position_in_monthly_race_skips_excluded_and_hides_margin(
    monkeypatch,
) -> None:
    """Wykluczony lider kwartału nie jest „1.”, a marża/h nie wycieka."""
    ranked = _ranked([(1, 5, True), (2, 3, True), (3, 3, True)])
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
        competitions,
        "placement_margin_per_hour_by_user",
        AsyncMock(
            return_value={
                2: {"margin_per_hour_sum": 40.0, "placements": [{"x": 1}]},
                3: {"margin_per_hour_sum": 10.0, "placements": [{"x": 2}]},
            }
        ),
    )
    monkeypatch.setattr(
        competitions, "compute_live", AsyncMock(return_value=deepcopy(ranked))
    )

    excluded = await competitions_api.my_position(
        SimpleNamespace(id=1), None, "monthly_placements", "2026-08"
    )
    assert excluded["rank"] is None and excluded["me"]["excluded"] is True

    leader = await competitions_api.my_position(
        SimpleNamespace(id=2), None, "monthly_placements", "2026-08"
    )
    assert leader["rank"] == 1
    for entry in [leader["me"], *leader["context"]]:
        assert "margin_per_hour_sum" not in entry
        assert "margin_placements" not in entry


async def test_dashboard_league_podium_skips_unqualified_leader(monkeypatch) -> None:
    """Bliźniak na pulpicie (`/api/dashboard/v2/recruitment-stats`)."""
    from app.services import dashboard_v2_sources

    ranked = _ranked([(1, 900, False), (2, 300, True)])
    monkeypatch.setattr(
        competitions,
        "quarterly_champions_recruiter",
        AsyncMock(return_value=deepcopy(ranked)),
    )
    monkeypatch.setattr(
        competitions, "league_scoring_config", AsyncMock(return_value=SCORING_DEFAULTS)
    )
    league = await dashboard_v2_sources.load_quarterly_league(None)
    assert [(e["user_id"], e["rank"]) for e in league["ranked"]] == [(2, 1), (1, None)]

    entries = [
        dashboard_v2_service._competition_entry(entry, idx + 1)
        for idx, entry in enumerate(league["ranked"])
    ]
    assert entries[1].rank is None
    assert entries[0].prize_pln == competitions.QUARTERLY_PRIZES_PLN[1]
    assert entries[1].prize_pln is None


# ── R4-16: migawka punktacji Ligi per kwartał ─────────────────────────────


async def test_league_scoring_config_prefers_the_quarter_snapshot(monkeypatch) -> None:
    current = {**SCORING_DEFAULTS, "league_points_placement": 999}
    stored = {key: SCORING_DEFAULTS[key] for key in competitions.LEAGUE_SCORING_KEYS}
    monkeypatch.setattr(
        competitions, "get_scoring_config", AsyncMock(return_value=current)
    )
    monkeypatch.setattr(
        competitions, "stored_league_scoring", AsyncMock(return_value=stored)
    )
    config = await competitions.league_scoring_config(None, "Q3 2026")
    assert (
        config["league_points_placement"] == SCORING_DEFAULTS["league_points_placement"]
    )

    monkeypatch.setattr(
        competitions, "stored_league_scoring", AsyncMock(return_value=None)
    )
    assert (await competitions.league_scoring_config(None, "Q3 2026"))[
        "league_points_placement"
    ] == 999


async def test_quarterly_league_ranks_with_the_snapshot_weights(monkeypatch) -> None:
    snapshot = {**SCORING_DEFAULTS, "league_points_placement": 111}
    league_config = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(competitions, "league_scoring_config", league_config)
    monkeypatch.setattr(
        competitions,
        "get_scoring_config",
        AsyncMock(side_effect=AssertionError("Liga nie czyta punktacji na żywo")),
    )
    rank = AsyncMock(return_value=[])
    monkeypatch.setattr(competitions, "_rank_recruiters_by_points", rank)

    await competitions.quarterly_champions_recruiter(None, "Q3 2026")

    league_config.assert_awaited_once_with(None, "Q3 2026")
    assert rank.await_args.kwargs["weights"]["placement"] == 111


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def first(self):
        return self._value


async def test_quarter_leader_exclusion_uses_the_quarter_snapshot(monkeypatch) -> None:
    """Wykluczenie lidera z wyścigu sierpnia liczy Ligę migawką Q3."""
    snapshot = {**SCORING_DEFAULTS, "league_min_placements_month2": 7}
    league_config = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(competitions, "league_scoring_config", league_config)
    monkeypatch.setattr(
        competitions,
        "get_scoring_config",
        AsyncMock(side_effect=AssertionError("wykluczenie nie czyta na żywo")),
    )
    rank = AsyncMock(return_value=[])
    monkeypatch.setattr(competitions, "_rank_recruiters_by_points", rank)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[_Scalar(None), _Scalar(None)]))

    exclusion = await competitions.monthly_race_excluded_user_ids(db, "2026-08")

    assert exclusion.source == "no_qualified_quarter_leader"
    league_config.assert_awaited_once_with(db, "Q3 2026")
    assert rank.await_args.kwargs["min_placements"] == 7


async def test_autofreeze_snapshots_the_current_quarter_scoring(monkeypatch) -> None:
    from app.tasks import competition_autofreeze

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        commit = AsyncMock()

    monkeypatch.setattr(competition_autofreeze, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(
        competitions, "snapshot_monthly_race_thresholds", AsyncMock(return_value=None)
    )
    league = AsyncMock(return_value=None)
    monkeypatch.setattr(competitions, "snapshot_league_scoring_config", league)

    await competition_autofreeze.snapshot_current_month_thresholds(date(2026, 8, 14))

    assert league.await_args.args[1] == "Q3 2026"


async def test_freezing_a_month_snapshots_its_quarter_scoring(monkeypatch) -> None:
    ranked = _ranked([(2, 3, True)])
    monkeypatch.setattr(
        competitions, "compute_live", AsyncMock(return_value=deepcopy(ranked))
    )
    monkeypatch.setattr(competitions, "_period_closure", AsyncMock(return_value=None))
    monkeypatch.setattr(
        competitions, "snapshot_monthly_race_thresholds", AsyncMock(return_value=None)
    )
    league = AsyncMock(return_value=None)
    monkeypatch.setattr(competitions, "snapshot_league_scoring_config", league)
    monkeypatch.setattr(
        competitions,
        "monthly_race_excluded_user_ids",
        AsyncMock(
            return_value=competitions.RaceExclusion(frozenset(), "test", "Q3 2026")
        ),
    )

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return []

    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(), _Result()]),
        add=lambda _row: None,
        commit=AsyncMock(),
    )
    await competitions.freeze_competition(
        db, CompetitionType.monthly_placements, "2026-08"
    )
    assert league.await_args.args[1] == "Q3 2026"


def _year() -> int:
    return 3000 + int(uuid.uuid4().hex[:6], 16) % 900


@needs_db
async def test_league_snapshot_is_first_write_wins(monkeypatch) -> None:
    from app.core.database import AsyncSessionLocal

    quarter = f"Q3 {_year()}"
    config = {**SCORING_DEFAULTS, "league_points_placement": 150}
    monkeypatch.setattr(
        competitions, "get_scoring_config", AsyncMock(side_effect=lambda _db: config)
    )
    async with AsyncSessionLocal() as db:
        first = await competitions.snapshot_league_scoring_config(db, quarter)
        await db.commit()
        assert first["league_points_placement"] == 150

        # Admin zmienia wagi PO migawce — kwartał liczy się dalej starą wagą.
        config = {**SCORING_DEFAULTS, "league_points_placement": 500}
        again = await competitions.snapshot_league_scoring_config(db, quarter)
        await db.commit()
        assert again["league_points_placement"] == 150
        assert (await competitions.league_scoring_config(db, quarter))[
            "league_points_placement"
        ] == 150
        # Kwartał bez migawki = punktacja bieżąca.
        other = f"Q4 {quarter.split()[1]}"
        assert (await competitions.league_scoring_config(db, other))[
            "league_points_placement"
        ] == 500
