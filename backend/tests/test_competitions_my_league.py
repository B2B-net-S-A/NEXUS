"""`GET /api/competitions/my-league` — Liga Mistrzów w górnym pasku (13.10.2026).

Trasa woła się bezpośrednio z podstawionym rankingiem (wzorzec
`test_audit_r4_competitions.py`), więc testy biegną bez bazy.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.api import competitions as competitions_api
from app.core import cache as cache_module
from app.models.competition_winner import CompetitionType
from app.models.user import User, UserRole
from app.services import competitions
from app.services.insights_scoring_config import SCORING_DEFAULTS

TODAY = date(2026, 10, 13)
PERIOD = "Q4 2026"


def _recruiters() -> list[competitions.RankedUser]:
    rows = [
        (11, 640, 3, 10, 8, True),
        (12, 515, 3, 3, 4, True),
        (13, 470, 2, 9, 7, True),
        (14, 385, 2, 4, 5, True),
        (15, 340, 2, 2, 2, True),
        (16, 210, 0, 11, 9, False),
    ]
    return [
        competitions.RankedUser(
            user_id=uid,
            name=f"Osoba {uid}",
            metric_value=points,
            extras={
                "placements": placements,
                "interviews": interviews,
                "recommendations": recommendations,
                "qualified": qualified,
                "required_placements": 1,
            },
        )
        for uid, points, placements, interviews, recommendations, qualified in rows
    ]


def _dls() -> list[competitions.RankedUser]:
    return [
        competitions.RankedUser(
            user_id=21, name="DL 21", metric_value=5, hit_ratio=41.7
        ),
        competitions.RankedUser(
            user_id=22, name="DL 22", metric_value=4, hit_ratio=36.4
        ),
    ]


@pytest.fixture
def league(monkeypatch):
    cache_module._cache.clear()

    async def live(_db, type_, _period):
        if type_ == CompetitionType.quarterly_champions_dl:
            return deepcopy(_dls())
        return deepcopy(_recruiters())

    monkeypatch.setattr(competitions, "compute_live", AsyncMock(side_effect=live))
    monkeypatch.setattr(
        competitions, "league_scoring_config", AsyncMock(return_value=SCORING_DEFAULTS)
    )
    monkeypatch.setattr(competitions, "current_quarter_period", lambda *_a: PERIOD)
    monkeypatch.setattr(competitions_api, "business_today", lambda: TODAY)
    counts = AsyncMock(
        return_value=(
            {21: 5, 22: 4, 23: 2, 24: 0, 25: 3},
            {21: 12, 22: 11, 23: 8, 25: 10},
        )
    )
    monkeypatch.setattr(competitions, "dl_portfolio_counts", counts)
    yield counts
    cache_module._cache.clear()


def _user(user_id: int, role: UserRole, *extra: UserRole) -> User:
    return User(id=user_id, role=role, roles=[r.value for r in extra])


async def test_recruiter_gets_place_points_and_rules(league) -> None:
    data = await competitions_api.my_league(_user(14, UserRole.recruiter), None)

    assert data["kind"] == "recruiter"
    assert data["type"] == CompetitionType.quarterly_champions_recruiter.value
    assert data["period"] == PERIOD
    assert data["days_remaining"] == 80
    assert data["total"] == 6
    assert data["prizes_pln"] == {1: 5000, 2: 3000, 3: 2000}
    assert data["points_formula"] == {
        "placement": 150,
        "interview": 15,
        "recommendation": 5,
    }
    # Październik to pierwszy miesiąc kwartału: próg 1, potem 2 i 3.
    assert data["required_placements"] == 1
    assert data["required_placements_by_month"] == [1, 2, 3]
    standing = data["standing"]
    assert standing["rank"] == 4
    assert standing["value"] == 385
    assert standing["gap_to_podium"] == 85
    assert standing["me"]["interviews"] == 4
    assert "leaders" not in data and "dl" not in data


async def test_unqualified_recruiter_has_points_without_a_place(league) -> None:
    data = await competitions_api.my_league(_user(16, UserRole.recruiter), None)
    standing = data["standing"]
    assert standing["rank"] is None
    assert standing["value"] == 210
    assert standing["position_by_value"] == 6
    assert standing["me"]["qualified"] is False


async def test_head_of_recruitment_with_recruiter_role_plays(league) -> None:
    data = await competitions_api.my_league(
        _user(12, UserRole.head_of_recruitment, UserRole.recruiter), None
    )
    assert data["kind"] == "recruiter"
    assert data["standing"]["rank"] == 2


async def test_spectator_sees_the_leaders_only(league) -> None:
    for role in (
        UserRole.admin,
        UserRole.finance,
        UserRole.head_of_recruitment,
        UserRole.user,
    ):
        cache_module._cache.clear()
        data = await competitions_api.my_league(_user(1, role), None)
        assert data["kind"] == "spectator", role
        assert [r["user_id"] for r in data["leaders"]] == [11, 12, 13, 14, 15]
        assert "standing" not in data and "points_formula" not in data


async def test_delivery_lead_in_the_league(league) -> None:
    data = await competitions_api.my_league(_user(22, UserRole.delivery_lead), None)
    assert data["kind"] == "delivery_lead"
    assert data["type"] == CompetitionType.quarterly_champions_dl.value
    assert data["standing"]["rank"] == 2
    assert data["standing"]["value"] == 4
    assert data["standing"]["gap_to_place_above"] == 1
    assert data["dl"] == {
        "placements": 4,
        "closed_requests": 11,
        "hit_ratio": 36.4,
        "hit_ratio_target": 30.0,
        "min_placements": 3,
        "missing_placements": 0,
        "qualified": True,
    }
    assert "points_formula" not in data


async def test_delivery_lead_below_the_threshold_gets_the_way_in(league) -> None:
    data = await competitions_api.my_league(_user(23, UserRole.delivery_lead), None)
    assert data["standing"]["me"] is None
    # 2 placementy z 8 zamkniętych = 25%: brakuje 1 do trzech (i do 30%).
    assert data["dl"]["hit_ratio"] == 25.0
    assert data["dl"]["missing_placements"] == 1
    assert data["dl"]["qualified"] is False


async def test_delivery_lead_without_closed_requests_has_no_hit_ratio(league) -> None:
    data = await competitions_api.my_league(_user(24, UserRole.delivery_lead), None)
    assert data["dl"]["hit_ratio"] is None
    assert data["dl"]["closed_requests"] == 0
    assert data["dl"]["missing_placements"] == 3
    assert data["dl"]["qualified"] is False


async def test_qualified_delivery_lead_outside_the_list_is_still_in_the_league(
    league,
) -> None:
    # Ranking DL tnie listę do 10 — osoba spełniająca próg może jej nie mieć.
    data = await competitions_api.my_league(_user(25, UserRole.delivery_lead), None)
    assert data["standing"]["me"] is None
    assert data["dl"]["qualified"] is True
    assert data["dl"]["missing_placements"] == 0


async def test_head_of_recruitment_with_dl_role_sees_the_dl_league(league) -> None:
    data = await competitions_api.my_league(
        _user(21, UserRole.head_of_recruitment, UserRole.delivery_lead), None
    )
    assert data["kind"] == "delivery_lead"
    assert data["standing"]["rank"] == 1
    assert data["dl"]["placements"] == 5


async def test_topbar_reads_the_dl_counts_once_for_the_whole_company(league) -> None:
    await competitions_api.my_league(_user(21, UserRole.delivery_lead), None)
    await competitions_api.my_league(_user(23, UserRole.delivery_lead), None)
    assert league.await_count == 1


async def test_topbar_keeps_the_ranking_longer_than_current(
    league, monkeypatch
) -> None:
    await competitions_api.my_league(_user(14, UserRole.recruiter), None)
    # Wpis `/current` wygasł (60 s), wpis paska jeszcze nie (300 s).
    for key in [
        k for k in cache_module._cache if k.startswith("competitions:current:")
    ]:
        del cache_module._cache[key]
    await competitions_api.my_league(_user(15, UserRole.recruiter), None)
    assert competitions.compute_live.await_count == 1


async def test_freeze_clears_the_topbar_entries(league) -> None:
    await competitions_api.my_league(_user(14, UserRole.recruiter), None)
    assert any(k.startswith("competitions:topbar:") for k in cache_module._cache)
    await cache_module.cache_invalidate(competitions_api._CACHE_PREFIX)
    assert not any(k.startswith("competitions:") for k in cache_module._cache)


async def test_tie_on_the_podium_reaches_both_people(league, monkeypatch) -> None:
    tied = [
        competitions.RankedUser(
            user_id=uid,
            name=f"Osoba {uid}",
            metric_value=points,
            extras={"qualified": True, "placements": 2},
        )
        for uid, points in ((31, 640), (32, 470), (33, 470), (34, 300))
    ]
    monkeypatch.setattr(
        competitions, "compute_live", AsyncMock(return_value=deepcopy(tied))
    )
    second = await competitions_api.my_league(_user(32, UserRole.recruiter), None)
    third = await competitions_api.my_league(_user(33, UserRole.recruiter), None)
    assert second["standing"]["tie_for"] == 2
    assert third["standing"]["tie_for"] == 2
