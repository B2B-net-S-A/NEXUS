"""`GET /api/competitions/my-league` — Liga Mistrzów w górnym pasku (13.10.2026).

Trasa woła się bezpośrednio z podstawionym rankingiem (wzorzec
`test_audit_r4_competitions.py`), więc testy biegną bez bazy.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import competitions as competitions_api
from app.core import cache as cache_module
from app.models.competition_winner import CompetitionType
from app.models.user import User, UserRole
from app.services import competitions
from app.services.insights_scoring_config import SCORING_DEFAULTS


@pytest.fixture(autouse=True)
def _periods_are_open(monkeypatch):
    """Od 15.10.2026 okres zamknięty `/current` i `/monthly-races` pokazują
    z zamrożenia (`frozen_result`, zapytanie do bazy). Te testy sprawdzają
    ranking na żywo — na atrapie sesji albo przed zamrożeniem — więc każdy
    okres jest tu otwarty."""
    monkeypatch.setattr(competitions, "frozen_result", AsyncMock(return_value=None))


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
    # Liga DL od 25.10.2026: kolejność po hit ratio, miejsce od 3 placementów
    # i 5 zamkniętych rekrutacji. Liczby zgodne z `dl_portfolio_counts` niżej.
    rows = [
        (21, 5, 12, True),
        (22, 4, 11, True),
        (25, 3, 10, True),
        (23, 2, 8, False),
    ]
    return [
        competitions.RankedUser(
            user_id=uid,
            name=f"DL {uid}",
            metric_value=placements,
            hit_ratio=round(placements / closed * 100, 1),
            extras={"requests": closed, "qualified": qualified},
        )
        for uid, placements, closed, qualified in rows
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
    # Zamknięcia „nie liczy się” (21.10.2026): DL 22 ma jedno.
    monkeypatch.setattr(
        competitions, "dl_neutral_closed_counts", AsyncMock(return_value={22: 1})
    )
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
    # Liga DL od Q4 2026 jest bez nagród.
    assert data["prizes_pln"] == {}
    assert data["total"] == 4
    assert data["standing"]["rank"] == 2
    # Wynik i dystanse w hit ratio, nie w placementach.
    assert data["standing"]["value"] == 36.4
    assert data["standing"]["gap_to_place_above"] == 5.3
    assert data["standing"]["lead_over_next"] == 6.4
    assert data["dl"] == {
        "placements": 4,
        "closed_requests": 11,
        "closed_neutral": 1,
        "hit_ratio": 36.4,
        "hit_ratio_target": 30.0,
        "min_placements": 3,
        "min_closed_requests": 5,
        "missing_placements": 0,
        "missing_closed_requests": 0,
        "qualified": True,
    }
    assert "points_formula" not in data


async def test_delivery_lead_below_the_threshold_is_listed_without_a_place(
    league,
) -> None:
    data = await competitions_api.my_league(_user(23, UserRole.delivery_lead), None)
    # 2 placementy z 8 zamkniętych = 25%: na liście, ale bez miejsca —
    # brakuje 1 placementu do trzech; zamkniętych jest dość.
    assert data["standing"]["me"]["user_id"] == 23
    assert data["standing"]["rank"] is None
    assert data["standing"]["position_by_value"] == 4
    assert data["dl"]["hit_ratio"] == 25.0
    assert data["dl"]["missing_placements"] == 1
    assert data["dl"]["missing_closed_requests"] == 0
    assert data["dl"]["qualified"] is False


async def test_delivery_lead_without_closed_requests_has_no_hit_ratio(league) -> None:
    data = await competitions_api.my_league(_user(24, UserRole.delivery_lead), None)
    assert data["standing"]["me"] is None
    assert data["dl"]["hit_ratio"] is None
    assert data["dl"]["closed_requests"] == 0
    assert data["dl"]["missing_placements"] == 3
    assert data["dl"]["missing_closed_requests"] == 5
    assert data["dl"]["qualified"] is False


async def test_threshold_not_hit_ratio_decides_the_place(league) -> None:
    # 3 z 10 = 30%: przed 25.10.2026 próg hit ratio, dziś miejsce 3. — liga
    # nie ucina listy do dziesięciu i nie ma progu procentowego.
    data = await competitions_api.my_league(_user(25, UserRole.delivery_lead), None)
    assert data["standing"]["rank"] == 3
    assert data["standing"]["gap_to_place_above"] == 6.4
    assert data["dl"]["qualified"] is True


async def test_head_of_recruitment_with_dl_role_sees_the_dl_league(league) -> None:
    data = await competitions_api.my_league(
        _user(21, UserRole.head_of_recruitment, UserRole.delivery_lead), None
    )
    assert data["kind"] == "delivery_lead"
    assert data["standing"]["rank"] == 1
    assert data["dl"]["placements"] == 5


async def test_both_roles_without_a_dl_portfolio_play_in_the_recruiter_league(
    league,
) -> None:
    # Produkcja 15.10.2026: osoba z rolami DL i rekrutera była 2. w Lidze
    # rekruterów (470 pkt, miejsce za 3000 zł), a w portfelu DL nie miała ani
    # zamkniętej rekrutacji, ani placementu — pasek pokazywał jej
    # „Liga DL · poza ligą, brakuje 3 placementów”.
    data = await competitions_api.my_league(
        _user(13, UserRole.delivery_lead, UserRole.recruiter), None
    )
    assert data["kind"] == "recruiter"
    assert data["type"] == CompetitionType.quarterly_champions_recruiter.value
    assert data["standing"]["rank"] == 3
    assert data["standing"]["value"] == 470
    assert "dl" not in data


async def test_both_roles_with_a_dl_portfolio_stay_in_the_dl_league(league) -> None:
    data = await competitions_api.my_league(
        _user(22, UserRole.delivery_lead, UserRole.recruiter), None
    )
    assert data["kind"] == "delivery_lead"
    assert data["standing"]["rank"] == 2
    assert data["dl"]["placements"] == 4


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


async def test_freeze_clears_the_topbar_entries(league, monkeypatch) -> None:
    # Trasy zamrożenia i remisu same czyszczą wpisy paska — test woła trasę,
    # nie `cache_invalidate` (audyt 48 h: dawny test nie sprawdzał trasy).
    monkeypatch.setattr(
        competitions,
        "freeze_competition",
        AsyncMock(
            return_value=SimpleNamespace(
                saved_count=3, already_frozen=False, closure_status="frozen"
            )
        ),
    )
    monkeypatch.setattr(
        competitions, "resolve_competition_tie", AsyncMock(return_value={"ok": True})
    )
    admin = _user(1, UserRole.admin)
    recruiters = CompetitionType.quarterly_champions_recruiter.value

    async def topbar_entries() -> list[str]:
        await competitions_api.my_league(_user(14, UserRole.recruiter), None)
        await competitions_api.my_league(_user(21, UserRole.delivery_lead), None)
        return [k for k in cache_module._cache if k.startswith("competitions:")]

    assert any(k.startswith("competitions:topbar:") for k in await topbar_entries())
    assert any(k.startswith("competitions:dl-counts:") for k in cache_module._cache)
    await competitions_api.freeze(admin, None, type=recruiters, period="Q3 2026")
    assert not any(k.startswith("competitions:") for k in cache_module._cache)

    assert await topbar_entries()
    await competitions_api.resolve_tie(
        recruiters,
        "Q3 2026",
        competitions_api.ResolveTieRequest(user_ids=[11, 12]),
        admin,
        None,
    )
    assert not any(k.startswith("competitions:") for k in cache_module._cache)


async def test_topbar_does_not_take_last_quarter_from_current_after_the_turn(
    league, monkeypatch
) -> None:
    # Wpis `/current` bez okresu (60 s) policzony przed północą 30.09 niesie
    # ranking Q3. Pierwszy pasek w Q4 nie może go zapisać pod kluczem Q4 na
    # 5 minut (audyt 48 h, 13.10.2026).
    stale = {
        "period": "Q3 2026",
        "full_ranking": [],
        "ties": None,
    }
    await cache_module.cache_set(
        "competitions:current:quarterly_champions_recruiter:", stale, ttl_seconds=60
    )
    data = await competitions_api.my_league(_user(14, UserRole.recruiter), None)
    assert data["period"] == PERIOD
    assert data["standing"]["rank"] == 4
    topbar = await cache_module.cache_get(
        f"competitions:topbar:quarterly_champions_recruiter:{PERIOD}"
    )
    assert topbar["period"] == PERIOD


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
