"""Liga Mistrzów DL po hit ratio, bez nagród (decyzja Artura 25.10.2026).

Od Q4 2026: ranking po hit ratio, miejsce od 3 placementów i 5 zamkniętych
rekrutacji, żadnych kwot. Kwartały do Q3 2026 zostają z nagrodami, którymi je
rozliczono. Testy bez bazy: atrapa sesji i podstawione liczniki portfela.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import competitions as competitions_api
from app.core import cache as cache_module
from app.models.competition_winner import CompetitionType
from app.services import competitions

DL = CompetitionType.quarterly_champions_dl
RECRUITER = CompetitionType.quarterly_champions_recruiter


class _Result:
    def __init__(self, rows: list[object]):
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


def _db(names: dict[int, str]) -> SimpleNamespace:
    async def execute(_stmt, *_a, **_k):
        return _Result([SimpleNamespace(id=uid, name=n) for uid, n in names.items()])

    return SimpleNamespace(execute=execute)


async def _rank(monkeypatch, placements: dict, closed: dict, names: dict):
    monkeypatch.setattr(
        competitions,
        "dl_portfolio_counts",
        AsyncMock(return_value=(placements, closed)),
    )
    return await competitions._rank_dls_by_hit_ratio(
        _db(names),
        start=datetime(2026, 10, 1, tzinfo=timezone.utc),
        end=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )


# ── Ranking ────────────────────────────────────────────────────────────────


async def test_ranking_follows_hit_ratio_not_placements(monkeypatch) -> None:
    # Liczby ze stagingu 22.10.2026 (Tablica od 12.10), skrócone do czterech DL-i.
    ranked = await _rank(
        monkeypatch,
        placements={1: 3, 2: 3, 3: 2, 4: 6},
        closed={1: 12, 2: 14, 3: 4, 4: 10},
        names={1: "A", 2: "B", 3: "C", 4: "D"},
    )
    assert [(r.user_id, r.hit_ratio) for r in ranked] == [
        (4, 60.0),
        (3, 50.0),
        (1, 25.0),
        (2, 21.4),
    ]
    # `metric_value` to dalej placementy — kolumna całkowita zamrożenia.
    assert ranked[0].metric_value == 6


async def test_below_the_threshold_stays_on_the_list_with_reasons(monkeypatch) -> None:
    ranked = await _rank(
        monkeypatch,
        placements={1: 2, 2: 3},
        closed={1: 4, 2: 3, 3: 2},
        names={1: "A", 2: "B", 3: "C"},
    )
    by_id = {r.user_id: r for r in ranked}
    assert by_id[1].extras["qualified"] is False
    assert by_id[1].extras["disqualification_reasons"] == [
        "MIN_PLACEMENTS_NOT_MET",
        "MIN_CLOSED_REQUESTS_NOT_MET",
    ]
    # 3 z 3 = 100%, ale zamkniętych za mało — „2 z 2” nie wygrywa ligi.
    assert by_id[2].extras["disqualification_reasons"] == [
        "MIN_CLOSED_REQUESTS_NOT_MET"
    ]
    # Zamknięte bez placementu: na liście z 0%.
    assert by_id[3].metric_value == 0
    assert by_id[3].hit_ratio == 0.0


async def test_placements_without_closed_requests_have_no_hit_ratio(
    monkeypatch,
) -> None:
    ranked = await _rank(
        monkeypatch,
        placements={1: 2, 2: 1},
        closed={2: 5},
        names={1: "A", 2: "B"},
    )
    # Niepoliczone hit ratio to nie 0% — i stoi za każdym policzonym.
    assert [(r.user_id, r.hit_ratio) for r in ranked] == [(2, 20.0), (1, None)]


async def test_inactive_or_non_dl_people_are_not_listed(monkeypatch) -> None:
    ranked = await _rank(
        monkeypatch,
        placements={1: 4, 9: 5},
        closed={1: 5, 9: 5},
        names={1: "A"},
    )
    assert [r.user_id for r in ranked] == [1]


# ── Kolejność nagrodowa i kwoty ────────────────────────────────────────────


def _dl(uid: int, placements: int, hit_ratio, qualified: bool = True):
    return competitions.RankedUser(
        user_id=uid,
        name=f"DL {uid}",
        metric_value=placements,
        hit_ratio=hit_ratio,
        extras={"qualified": qualified},
    )


async def test_award_order_has_no_prizes_and_no_admin_ties_from_q4_2026() -> None:
    ranked = [
        _dl(1, 3, 30.0),
        _dl(2, 6, 30.0),
        _dl(3, 4, 40.0),
        _dl(4, 2, 100.0, qualified=False),
    ]
    order = await competitions.award_order(None, DL, "Q4 2026", ranked)
    # Równy procent: wyżej większy portfel; remis nie czeka na admina.
    assert [r.user_id for r in order.ordered] == [3, 2, 1]
    assert order.ties == []
    rows = competitions.award_ranked_rows(DL, ranked, order)
    assert [(r["user_id"], r["rank"], r["prize_pln"]) for r in rows] == [
        (3, 1, 0),
        (2, 2, 0),
        (1, 3, 0),
        (4, None, None),
    ]


@pytest.mark.parametrize(
    ("period", "pays"),
    [
        ("Q1 2026", True),
        ("Q3 2026", True),
        ("Q4 2026", False),
        ("Q1 2027", False),
        (None, False),
        ("2026-09", False),
    ],
)
def test_dl_prizes_end_with_q3_2026(period, pays) -> None:
    assert competitions.dl_league_pays(period) is pays
    expected = 5000 if pays else 0
    assert competitions._prize_for(DL, 1, period) == expected
    assert competitions.paid_slots(DL, period) == (3 if pays else 0)


def test_recruiter_league_keeps_its_prizes() -> None:
    assert competitions._prize_for(RECRUITER, 1, "Q4 2026") == 5000
    assert competitions._prize_for(RECRUITER, 3, "Q1 2027") == 2000
    assert competitions.paid_slots(RECRUITER, "Q4 2026") == 3


# ── `/current` ─────────────────────────────────────────────────────────────


@pytest.fixture
def live_dl(monkeypatch):
    cache_module._cache.clear()
    monkeypatch.setattr(competitions, "frozen_result", AsyncMock(return_value=None))
    monkeypatch.setattr(
        competitions,
        "compute_live",
        AsyncMock(return_value=[_dl(1, 4, 40.0), _dl(2, 2, 50.0, qualified=False)]),
    )
    yield
    cache_module._cache.clear()


async def test_current_dl_league_says_it_has_no_prizes(live_dl) -> None:
    data = await competitions_api._compute_current(None, DL, "Q4 2026")
    assert data["prize_pool_pln"] is None
    assert data["quarterly_prizes_pln"] is None
    assert "nie ma nagród" in data["requirement"]
    assert "5 zamkniętych" in data["requirement"]
    assert [(r["user_id"], r["rank"], r["prize_pln"]) for r in data["top3"]] == [
        (1, 1, 0)
    ]


async def test_current_dl_league_before_q4_2026_keeps_its_rules(live_dl) -> None:
    data = await competitions_api._compute_current(None, DL, "Q3 2026")
    assert data["prize_pool_pln"] == 10_000
    assert data["quarterly_prizes_pln"] == competitions.QUARTERLY_PRIZES_PLN
    assert "hit ratio ≥ 30%" in data["requirement"]
