"""Opisy celów Delivery Leada mówią o tym, co naprawdę liczy mianownik.

Runda 6 audytu: notatka pod celem placementów brzmiała „Nowe requesty
w kwartale”, a liczba pod nią to rekrutacje ZAMKNIĘTE w kwartale — mianownik
hit ratio ligi DL (`competitions.dl_portfolio_counts`).

13.10.2026 (decyzja Artura): celem Delivery Leada jest 30% hit ratio, więc cel
placementów to 30% zamkniętych rekrutacji, a nie stałe 3 z ligi.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.user import UserRole
from app.services import competitions, kpi_goals
from app.services.kpi_targets import resolve_kpi_targets_bulk, resolve_org_target

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


async def _no_neutral(db, *, start, end):
    # Zamknięcia „nie liczy się” (21.10.2026) — tu żadnych.
    return {}


async def _dl_goals(monkeypatch, *, placements: int, closed: int):
    async def fake_counts(db, *, start, end):
        return ({7: placements} if placements else {}), ({7: closed} if closed else {})

    monkeypatch.setattr(competitions, "dl_portfolio_counts", fake_counts)
    monkeypatch.setattr(competitions, "dl_neutral_closed_counts", _no_neutral)
    return await kpi_goals._delivery_lead_goals(
        None, user=SimpleNamespace(id=7), now=NOW
    )


@pytest.mark.asyncio
async def test_dl_goal_notes_describe_closed_recruitments(monkeypatch):
    result = await _dl_goals(monkeypatch, placements=1, closed=4)
    notes = {g.goal_id: g.note for g in result.goals}
    assert notes["dl_placements_quarter"] == "Rekrutacje zamknięte w kwartale: 4"
    assert "requesty" not in notes["dl_placements_quarter"].lower()


@pytest.mark.asyncio
async def test_dl_hit_ratio_without_closed_recruitments_says_so(monkeypatch):
    result = await _dl_goals(monkeypatch, placements=0, closed=0)
    note = {g.goal_id: g.note for g in result.goals}["dl_hit_ratio_quarter"]
    assert note is not None
    assert "zamknięto" in note
    assert "nowych requestów" not in note


# ── Cel placementów = 30% zamkniętych rekrutacji, w górę ────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("closed", "target"),
    [(1, 1), (3, 1), (4, 2), (5, 2), (7, 3), (10, 3), (20, 6), (100, 30)],
)
async def test_dl_placement_target_is_30_percent_of_closed_rounded_up(
    monkeypatch, closed, target
):
    result = await _dl_goals(monkeypatch, placements=0, closed=closed)
    by_id = {g.goal_id: g for g in result.goals}
    assert by_id["dl_placements_quarter"].target == target
    assert result.closed_requests == closed


@pytest.mark.asyncio
async def test_dl_placement_target_multiplies_before_dividing(monkeypatch):
    """`28.0 / 100 * 25` daje 7,000000000000001 i `ceil` zwróciłby 8."""
    monkeypatch.setattr(competitions, "HIT_RATIO_TARGET", 28.0)
    result = await _dl_goals(monkeypatch, placements=0, closed=25)
    by_id = {g.goal_id: g for g in result.goals}
    assert by_id["dl_placements_quarter"].target == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("placements", "closed", "state"),
    [
        (2, 10, "behind"),  # przykład Artura: 10 zapytań = cel 3 placementy
        (3, 10, "hit"),
        (2, 7, "behind"),  # 28,6% — jeszcze poniżej progu
        (3, 7, "hit"),
        # 68 z 227 to 29,96% — w zaokrągleniu 30,0%, ale do progu brakuje placementu.
        (68, 227, "behind"),
    ],
)
async def test_dl_both_goals_share_one_state_without_pace(
    monkeypatch, placements, closed, state
):
    result = await _dl_goals(monkeypatch, placements=placements, closed=closed)
    by_id = {g.goal_id: g for g in result.goals}
    assert by_id["dl_placements_quarter"].state == state
    assert by_id["dl_hit_ratio_quarter"].state == state
    # Cel DL nie ma tempa: rośnie z liczbą zamkniętych rekrutacji.
    assert by_id["dl_placements_quarter"].expected is None
    assert by_id["dl_hit_ratio_quarter"].expected is None


@pytest.mark.asyncio
async def test_dl_without_closed_recruitments_has_no_target_yet(monkeypatch):
    # Placement w rekrutacji, która jeszcze trwa: wynik jest, celu nie ma.
    async def fake_counts(db, *, start, end):
        return {7: 2}, {}

    monkeypatch.setattr(competitions, "dl_portfolio_counts", fake_counts)
    monkeypatch.setattr(competitions, "dl_neutral_closed_counts", _no_neutral)
    result = await kpi_goals._delivery_lead_goals(
        None, user=SimpleNamespace(id=7), now=NOW
    )
    placements = {g.goal_id: g for g in result.goals}["dl_placements_quarter"]
    assert result.closed_requests == 0
    assert placements.current == 2
    assert placements.target == 0
    assert placements.state is None
    assert placements.progress_pct is None
    assert "po zamknięciu pierwszej rekrutacji" in placements.note


@pytest.mark.asyncio
async def test_dl_goals_carry_short_titles(monkeypatch):
    result = await _dl_goals(monkeypatch, placements=2, closed=10)
    assert {g.goal_id: g.short_title_pl for g in result.goals} == {
        "dl_hit_ratio_quarter": "Hit ratio",
        "dl_placements_quarter": "Placementy",
    }


@pytest.mark.asyncio
async def test_goals_result_survives_the_cache_round_trip(monkeypatch):
    """`as_dict` / `from_dict` są pisane ręcznie — pole pominięte w jednym z nich
    znikałoby przy trafieniu w cache (120 s) i wracało przy pudle."""
    result = await _dl_goals(monkeypatch, placements=2, closed=10)
    assert kpi_goals.GoalsResult.from_dict(result.as_dict()) == result
    # Wpis z cache sprzed wdrożenia nie ma nowego klucza.
    legacy = result.as_dict()
    del legacy["closed_requests"]
    assert kpi_goals.GoalsResult.from_dict(legacy).closed_requests is None


# ── „Sam przekazał” Delivery Leada (22.10.2026) ─────────────────────────────


@pytest.mark.asyncio
async def test_own_handoffs_survive_the_cache_round_trip(monkeypatch):
    from dataclasses import replace

    result = replace(
        await _dl_goals(monkeypatch, placements=1, closed=4),
        own_handoffs={"verified": 5, "cv_sent": 3, "hired": 1},
    )
    assert kpi_goals.GoalsResult.from_dict(result.as_dict()) == result
    legacy = result.as_dict()
    del legacy["own_handoffs"]
    assert kpi_goals.GoalsResult.from_dict(legacy).own_handoffs is None


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self._rows


class _FunnelDb:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    async def execute(self, _sql, params):
        self.params = params
        return _Rows(self.rows)


@pytest.mark.asyncio
async def test_month_own_handoffs_reads_the_month_column_of_the_funnel():
    from app.services.kpi_panel import month_own_handoffs

    db = _FunnelDb(
        [
            {"stage": "verified", "d": 1, "w": 2, "mo": 5},
            {"stage": "cv_sent", "d": 0, "w": 1, "mo": 3},
            {"stage": "client_interview", "d": 0, "w": 0, "mo": 2},
        ]
    )
    counts = await month_own_handoffs(db, user=SimpleNamespace(id=7), now=NOW)
    assert counts == {"verified": 5, "cv_sent": 3, "hired": 0}
    assert db.params["uid"] == 7


# ── Cel wycofany: resolver nie pyta o niego bazy ────────────────────────────


class _NoQueries:
    async def execute(self, *_args, **_kwargs):  # pragma: no cover - nie może paść
        raise AssertionError("resolver nie może pytać bazy o cel spoza katalogu")


@pytest.mark.asyncio
async def test_withdrawn_goal_resolves_to_zero_without_touching_the_db():
    user = SimpleNamespace(id=5, get_all_roles=lambda: [UserRole.recruiter])
    db = _NoQueries()
    targets = await resolve_kpi_targets_bulk(
        db, [user], ["daily_new_candidates", "cv_added_daily"]
    )
    assert targets == {5: {"daily_new_candidates": 0, "cv_added_daily": 0}}
    assert await resolve_org_target(db, "daily_new_candidates") == 0
