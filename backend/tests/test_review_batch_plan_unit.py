"""Porcja na osobę (decyzje Artura 10.11.2026) — czysta funkcja planu, bez bazy.

Kontrakty:

- porcja osoby = jej poziom minus decyzje z dziś;
- tylko rekrutacje, do których osoba jest przypisana;
- najpierw wszystkie P0, potem P1 Pilne, „Bez priorytetu”, „Przyjmujemy”;
- wspólna pula dzieli się na zmianę między przypisanych;
- własne czekające karty liczą się najpierw i nie zabierają miejsca innym.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.job import JobPriority, JobStatus
from app.services.review_batch_plan import plan_portions, tier_key, tier_of

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
P0, P1, P2, ACCEPTING = 0, 1, 2, 3


def _plan(caps, teams, tiers, free, owned=None):
    return plan_portions(
        caps=caps, teams=teams, tiers=tiers, owned=owned or {}, free=free
    )


def test_whole_portion_from_p0_while_p0_has_people():
    want = _plan({7: 10}, {1: [7], 2: [7]}, {1: P0, 2: P1}, {1: 50, 2: 50})
    assert want == {7: {1: 10}}


def test_lower_priority_fills_what_p0_cannot():
    want = _plan({7: 10}, {1: [7], 2: [7]}, {1: P0, 2: P1}, {1: 3, 2: 50})
    assert want == {7: {1: 3, 2: 7}}


def test_levels_go_p0_p1_without_priority_accepting():
    teams = {1: [7], 2: [7], 3: [7], 4: [7]}
    tiers = {1: ACCEPTING, 2: P2, 3: P1, 4: P0}
    want = _plan({7: 8}, teams, tiers, {1: 9, 2: 2, 3: 2, 4: 2})
    assert want == {7: {4: 2, 3: 2, 2: 2, 1: 2}}


def test_only_jobs_the_person_is_assigned_to():
    want = _plan({7: 10, 8: 10}, {1: [8]}, {1: P0}, {1: 50})
    assert want == {7: {}, 8: {1: 10}}


def test_shared_pool_alternates_between_assigned_people():
    want = _plan({7: 4, 8: 4}, {1: [7, 8], 2: [7, 8]}, {1: P0, 2: P1}, {1: 5, 2: 50})
    assert want[7][1] + want[8][1] == 5
    assert sorted([want[7][1], want[8][1]]) == [2, 3]
    assert want[7].get(2, 0) + want[8].get(2, 0) == 3


def test_jobs_on_the_same_level_alternate():
    want = _plan({7: 5}, {1: [7], 2: [7]}, {1: P1, 2: P1}, {1: 50, 2: 50})
    assert want == {7: {1: 3, 2: 2}}


def test_own_cards_count_first_and_leave_the_pool_to_others():
    want = _plan(
        {7: 4, 8: 4},
        {1: [7, 8]},
        {1: P1},
        {1: 4},
        owned={7: {1: 4}},
    )
    assert want == {7: {1: 4}, 8: {1: 4}}


def test_decisions_today_shrink_what_still_comes():
    # Poziom 10, 7 decyzji dziś: dochodzą jeszcze najwyżej 3.
    assert _plan({7: 3}, {1: [7]}, {1: P1}, {1: 50}) == {7: {1: 3}}
    assert _plan({7: 0}, {1: [7]}, {1: P1}, {1: 50}) == {7: {}}
    assert _plan({7: -2}, {1: [7]}, {1: P1}, {1: 50}) == {7: {}}


def test_empty_pool_gives_nothing():
    assert _plan({7: 10}, {1: [7]}, {1: P0}, {1: 0}) == {7: {}}


def _job(priority, p0_until=None):
    return SimpleNamespace(
        priority=priority, p0_until=p0_until, status=JobStatus.published
    )


def test_tier_of_matches_the_screen_levels():
    assert tier_of(_job(JobPriority.medium, NOW + timedelta(hours=3)), NOW) == P0
    assert tier_of(_job(JobPriority.urgent), NOW) == P1
    assert tier_of(_job(JobPriority.high), NOW) == P1
    assert tier_of(_job(JobPriority.medium), NOW) == P2
    assert tier_of(_job(JobPriority.low), NOW) == ACCEPTING
    assert [tier_key(t) for t in (P0, P1, P2, ACCEPTING)] == [
        "p0",
        "p1",
        "p2",
        "accepting",
    ]
