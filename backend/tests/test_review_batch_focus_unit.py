"""Rekrutacja wybrana na dziś w porcji (zgłoszenie rekruterów 16.11.2026) — bez bazy.

Kontrakty:

- osoba, która wybrała rekrutację, bierze z niej najpierw (przed P0), ile się da;
- czego tam brakuje, dochodzi z jej pozostałych rekrutacji w zwykłej kolejności;
- z innych rekrutacji schodzi tylko nadwyżka ponad porcję, bez kart już wziętych;
- kto wybrał pierwszy, bierze pierwszy, a nikt nie traci własnych kart;
- karty, które ktoś już wziął, zostają w porcji przed wybraną;
- wybór rekrutacji, w której osoba nie pracuje, nic nie zmienia;
- wybór obowiązuje tylko w dniu, w którym go zrobiono.
"""

from datetime import datetime, timezone

from app.services.review_batch_focus import Focus, in_order, parse, preview
from app.services.review_batch_plan import plan_portions

P0, P1, P2 = 0, 1, 2
AT = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)


def _plan(caps, teams, tiers, free, owned=None, focus=(), pinned=None):
    return plan_portions(
        caps=caps,
        teams=teams,
        tiers=tiers,
        owned=owned or {},
        free=free,
        focus=focus,
        pinned=pinned,
    )


def test_chosen_job_comes_before_p0():
    want = _plan({7: 10}, {1: [7], 2: [7]}, {1: P0, 2: P1}, {1: 50, 2: 50})
    assert want == {7: {1: 10}}
    chosen = _plan(
        {7: 10}, {1: [7], 2: [7]}, {1: P0, 2: P1}, {1: 50, 2: 50}, focus=[(7, 2)]
    )
    assert chosen == {7: {2: 10}}


def test_small_chosen_job_leaves_the_rest_to_the_usual_order():
    want = _plan(
        {7: 10}, {1: [7], 2: [7]}, {1: P0, 2: P1}, {1: 50, 2: 3}, focus=[(7, 2)]
    )
    assert want == {7: {2: 3, 1: 7}}


def test_first_to_choose_takes_first():
    teams = {1: [7, 8], 2: [7, 8]}
    tiers = {1: P0, 2: P1}
    free = {1: 50, 2: 5}
    a_first = _plan({7: 4, 8: 4}, teams, tiers, free, focus=[(7, 2), (8, 2)])
    assert a_first == {7: {2: 4}, 8: {2: 1, 1: 3}}
    b_first = _plan({7: 4, 8: 4}, teams, tiers, free, focus=[(8, 2), (7, 2)])
    assert b_first == {7: {2: 1, 1: 3}, 8: {2: 4}}


def test_nobody_loses_own_cards_in_the_chosen_job():
    # 8 ma już 3 karty w rekrutacji 2, wolnych tam nie ma: 7 nic stamtąd nie bierze.
    want = _plan(
        {7: 4, 8: 4},
        {1: [7], 2: [7, 8]},
        {1: P0, 2: P1},
        {1: 50, 2: 0},
        owned={8: {2: 3}},
        focus=[(7, 2)],
    )
    assert want == {7: {1: 4}, 8: {2: 3}}


def test_own_cards_in_the_chosen_job_count_first():
    want = _plan(
        {7: 4},
        {1: [7], 2: [7]},
        {1: P0, 2: P1},
        {1: 50, 2: 50},
        owned={7: {2: 3}},
        focus=[(7, 2)],
    )
    assert want == {7: {2: 4}}


def test_taken_cards_elsewhere_keep_their_seats():
    want = _plan(
        {7: 4},
        {1: [7], 2: [7]},
        {1: P0, 2: P1},
        {1: 0, 2: 10},
        owned={7: {1: 3}},
        pinned={7: {1: 1}},
        focus=[(7, 2)],
    )
    assert want == {7: {1: 1, 2: 3}}


def test_choice_outside_own_jobs_changes_nothing():
    teams = {1: [7], 2: [8]}
    tiers = {1: P0, 2: P1}
    free = {1: 50, 2: 50}
    assert _plan({7: 4, 8: 4}, teams, tiers, free, focus=[(7, 2)]) == _plan(
        {7: 4, 8: 4}, teams, tiers, free
    )


def test_decisions_today_still_shrink_the_portion():
    assert _plan({7: 0}, {1: [7]}, {1: P1}, {1: 50}, focus=[(7, 1)]) == {7: {}}
    assert _plan({7: 3}, {1: [7]}, {1: P1}, {1: 50}, focus=[(7, 1)]) == {7: {1: 3}}


def test_preview_releases_only_the_surplus_over_the_portion():
    # Porcja 10, osoba ma 8 (6 + 2 w wybranej), z wybranej przyjdzie 5: zdejmujemy 3.
    result = preview(seats=10, take=5, held={1: 6, 2: 2}, pinned={}, job_id=2)
    assert (result.take, result.release) == (5, 3)


def test_preview_below_the_portion_releases_nothing():
    # Wybrana dała mało (2), osoba miała 4 z 10: nikt nie wraca do zespołu.
    result = preview(seats=10, take=2, held={1: 4}, pinned={}, job_id=2)
    assert (result.take, result.release) == (2, 0)


def test_preview_never_releases_taken_cards():
    result = preview(seats=4, take=4, held={1: 2}, pinned={1: 2}, job_id=2)
    assert result.release == 0
    result = preview(seats=4, take=4, held={1: 3}, pinned={1: 2}, job_id=2)
    assert result.release == 1


def test_choice_is_only_for_the_day_it_was_made():
    value = {"day": "2026-11-24", "users": {"7": {"job_id": 2, "at": AT.isoformat()}}}
    assert parse(value, "2026-11-24") == {7: Focus(user_id=7, job_id=2, at=AT)}
    assert parse(value, "2026-11-25") == {}


def test_parse_skips_broken_rows_and_reads_naive_times_as_utc():
    value = {
        "day": "2026-11-24",
        "users": {
            "7": {"job_id": 2, "at": "2026-11-24T08:00:00"},
            "x": {"job_id": 2, "at": AT.isoformat()},
            "9": {"at": AT.isoformat()},
            "10": "zepsute",
        },
    }
    assert parse(value, "2026-11-24") == {7: Focus(user_id=7, job_id=2, at=AT)}
    assert (
        parse(None, "2026-11-24") == {}
        and parse({"day": "2026-11-24"}, "2026-11-24") == {}
    )


def test_order_is_by_time_of_choice():
    later = AT.replace(hour=9)
    focus = {
        8: Focus(user_id=8, job_id=3, at=later),
        7: Focus(user_id=7, job_id=2, at=AT),
        9: Focus(user_id=9, job_id=2, at=later),
    }
    assert in_order(focus) == ((7, 2), (8, 3), (9, 2))
