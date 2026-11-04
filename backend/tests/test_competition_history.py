"""Wyniki 2026 sprzed NEXUS-a — reguły DynaReportera i granica 12.10.2026.

Czyste funkcje (bez bazy): okna źródła, liga, wykluczenie lidera, wyścigi,
rozliczenie okresu z ogłoszonym podium i parsowanie wejścia skryptu.
Dane fikcyjne — repo jest publiczne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.services import competition_history as history
from app.services.competition_history import DrCounts
from scripts import settle_competitions_from_dynareporter as script

WEIGHTS = {"placement": 150, "interview": 15, "recommendation": 5}
NAMES = {1: "Osoba A", 2: "Osoba B", 3: "Osoba C", 4: "Osoba D"}


def _utc(y: int, m: int, d: int, h: int = 0) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)


# ── Granica źródła ───────────────────────────────────────────────────────


def test_cutover_is_warsaw_midnight_of_12_october_2026() -> None:
    assert history.cutover_utc() == _utc(2026, 10, 11, 22)


@pytest.mark.parametrize(
    ("start", "end", "source"),
    [
        (_utc(2026, 6, 30, 22), _utc(2026, 9, 30, 22), history.SOURCE_DYNAREPORTER),
        (_utc(2026, 9, 30, 22), _utc(2026, 12, 31, 23), history.SOURCE_MIXED),
        (_utc(2026, 12, 31, 23), _utc(2027, 3, 31, 22), history.SOURCE_NEXUS),
    ],
)
def test_window_source(start, end, source) -> None:
    assert history.window_source(start, end) == source


def test_mixed_window_splits_on_cutover_without_overlap() -> None:
    start, end = _utc(2026, 9, 30, 22), _utc(2026, 10, 31, 23)
    dr = history.dr_window(start, end)
    live = history.live_window(start, end)
    assert dr == (start, history.cutover_utc())
    assert live == (history.cutover_utc(), end)


def test_window_wholly_after_cutover_has_no_dr_part() -> None:
    assert history.dr_window(_utc(2027, 1, 1), _utc(2027, 2, 1)) is None
    assert history.live_window(_utc(2026, 7, 1), _utc(2026, 8, 1)) is None


# ── Liga i wykluczenie lidera ────────────────────────────────────────────


def _q3(**people: DrCounts) -> dict:
    """Wszystkie liczniki w lipcu — liga sumuje kwartał."""
    return {"2026-07": {int(k[1:]): v for k, v in people.items()}}


def test_league_points_and_threshold_keep_unqualified_on_the_list() -> None:
    monthly = _q3(
        u1=DrCounts(placements=3, interviews=2, recommendations=10),
        u2=DrCounts(placements=2, interviews=40, recommendations=60),
    )
    ranked = history.dr_league(
        monthly, history.quarter_months(2026, 3), weights=WEIGHTS, names=NAMES
    )
    by_id = {e.user_id: e for e in ranked}
    assert by_id[1].metric_value == 3 * 150 + 2 * 15 + 10 * 5
    assert by_id[1].extras["qualified"] is True
    # Więcej punktów, ale za mało placementów: na liście, bez kwalifikacji.
    assert ranked[0].user_id == 2
    assert by_id[2].extras["qualified"] is False
    assert by_id[2].extras["disqualification_reasons"] == ["MIN_PLACEMENTS_NOT_MET"]


def test_quarter_leader_is_excluded_only_in_the_last_month_of_quarter() -> None:
    monthly = {
        "2026-07": {1: DrCounts(placements=5), 2: DrCounts(placements=3)},
        "2026-09": {1: DrCounts(placements=1)},
    }
    assert (
        history.dr_excluded_quarter_leaders(monthly, "2026-07", weights=WEIGHTS)
        == set()
    )
    assert (
        history.dr_excluded_quarter_leaders(monthly, "2026-08", weights=WEIGHTS)
        == set()
    )
    assert history.dr_excluded_quarter_leaders(monthly, "2026-09", weights=WEIGHTS) == {
        1
    }


def test_quarter_leaders_tied_on_points_are_all_excluded() -> None:
    monthly = {"2026-07": {1: DrCounts(placements=3), 2: DrCounts(placements=3)}}
    assert history.dr_excluded_quarter_leaders(monthly, "2026-09", weights=WEIGHTS) == {
        1,
        2,
    }


# ── Wyścigi ──────────────────────────────────────────────────────────────


def test_recommendation_race_counts_verifications_per_worked_day() -> None:
    counts = {
        # 40 weryfikacji w 10 przepracowanych dniach = 4/dzień — kwalifikuje,
        # choć miesiąc miał ~21 dni roboczych (reguła NEXUS-a by odrzuciła).
        1: DrCounts(verifications=40, recommendations=35, days_worked=10),
        2: DrCounts(verifications=39, recommendations=39, days_worked=10),
    }
    ranked = history.dr_recommendation_race(counts, "2026-07", names=NAMES)
    by_id = {e.user_id: e for e in ranked}
    assert by_id[1].extras["qualified"] is True
    assert by_id[1].extras["workdays_source"] == "dynareporter"
    assert by_id[1].extras["per_day"] == 4.0
    assert by_id[2].extras["disqualification_reasons"] == ["MIN_VERIFICATIONS_NOT_MET"]


def test_precision_requirement_starts_in_april_2026() -> None:
    low_precision = {1: DrCounts(verifications=40, recommendations=20, days_worked=10)}
    march = history.dr_recommendation_race(low_precision, "2026-03", names=NAMES)
    april = history.dr_recommendation_race(low_precision, "2026-04", names=NAMES)
    assert march[0].extras["qualified"] is True
    assert april[0].extras["disqualification_reasons"] == ["MIN_PRECISION_NOT_MET"]


def test_recommendation_race_skips_people_without_recommendations() -> None:
    counts = {1: DrCounts(verifications=50, days_worked=10)}
    assert history.dr_recommendation_race(counts, "2026-07", names=NAMES) == []


def test_placement_race_has_no_threshold_and_orders_by_count() -> None:
    counts = {1: DrCounts(placements=1), 2: DrCounts(placements=4), 3: DrCounts()}
    ranked = history.dr_placement_race(counts, names=NAMES)
    assert [e.user_id for e in ranked] == [2, 1]


# ── Rozliczenie okresu ───────────────────────────────────────────────────


def test_unresolved_placement_tie_waits_for_admin() -> None:
    monthly = {"2026-08": {1: DrCounts(placements=4), 2: DrCounts(placements=4)}}
    s = history.settle_dr_period(
        "monthly_placements", "2026-08", monthly, names=NAMES, weights=WEIGHTS
    )
    assert s.status == "tie_pending"
    assert s.winners == []
    assert sorted(s.details["ties"][0]["user_ids"]) == [1, 2]
    assert s.details["source"] == history.SOURCE_DYNAREPORTER
    assert s.details["source_note"] == history.DYNAREPORTER_SOURCE_NOTE


def test_announced_podium_resolves_the_tie_like_the_admin_did() -> None:
    # Maj, nie czerwiec: w ostatnim miesiącu kwartału lider ligi odpada z wyścigu.
    monthly = {"2026-05": {1: DrCounts(placements=3), 2: DrCounts(placements=3)}}
    s = history.settle_dr_period(
        "monthly_placements",
        "2026-05",
        monthly,
        names=NAMES,
        weights=WEIGHTS,
        official=[2],
        official_settled=True,
    )
    assert s.status == "frozen"
    assert s.official_mismatch is None
    assert s.winners[0] == {
        "rank": 1,
        "user_id": 2,
        "metric_value": 3,
        "prize_pln": 1500,
    }
    assert s.details["source_note"] == history.DYNAREPORTER_OFFICIAL_NOTE


def test_announced_podium_contradicting_the_data_is_flagged() -> None:
    monthly = {"2026-05": {1: DrCounts(placements=5), 2: DrCounts(placements=3)}}
    s = history.settle_dr_period(
        "monthly_placements",
        "2026-05",
        monthly,
        names=NAMES,
        weights=WEIGHTS,
        official=[2],
    )
    assert s.official_mismatch is not None


def test_partial_announced_podium_leaves_the_rest_of_the_tie_to_the_admin() -> None:
    """Ogłoszone 1. i 2. miejsce; 3. miejsce z tego samego remisu — admin, nie id."""
    monthly = {
        "2026-07": {
            1: DrCounts(placements=3, recommendations=60),
            2: DrCounts(placements=3, recommendations=30),
            3: DrCounts(placements=3, recommendations=30),
            4: DrCounts(placements=3, recommendations=30),
        }
    }
    s = history.settle_dr_period(
        "quarterly_champions_recruiter",
        "Q3 2026",
        monthly,
        names=NAMES,
        weights=WEIGHTS,
        official=[1, 3],
        official_settled=True,
    )
    assert s.official_mismatch is None
    assert s.status == "tie_pending"
    assert [(w["rank"], w["user_id"]) for w in s.winners] == [(1, 1), (2, 3)]
    assert s.details["ties"][0]["positions"] == [3]
    assert sorted(s.details["ties"][0]["user_ids"]) == [2, 4]
    assert sorted(e["user_id"] for e in s.details["ties"][0]["entries"]) == [2, 4]


def test_settled_period_without_winner_is_checked_against_the_data() -> None:
    monthly = {"2026-05": {1: DrCounts(placements=2)}}
    s = history.settle_dr_period(
        "monthly_placements",
        "2026-05",
        monthly,
        names=NAMES,
        weights=WEIGHTS,
        official=[],
        official_settled=True,
    )
    assert s.official_mismatch is not None


def test_recommendation_race_without_qualified_people_has_no_winner() -> None:
    monthly = {
        "2026-05": {1: DrCounts(verifications=10, recommendations=9, days_worked=20)}
    }
    s = history.settle_dr_period(
        "monthly_recommendations", "2026-05", monthly, names=NAMES, weights=WEIGHTS
    )
    assert s.status == "no_winner"
    assert s.winners == []
    # Lista zostaje — ekran pokaże, kto ile miał i dlaczego bez nagrody.
    assert [entry["user_id"] for entry in s.details["ranking"]] == [1]


def test_excluded_leader_stays_on_the_list_without_the_prize() -> None:
    monthly = {
        "2026-07": {1: DrCounts(placements=6), 2: DrCounts(placements=3)},
        "2026-09": {1: DrCounts(placements=2), 2: DrCounts(placements=1)},
    }
    s = history.settle_dr_period(
        "monthly_placements", "2026-09", monthly, names=NAMES, weights=WEIGHTS
    )
    assert s.details["excluded_user_ids"] == [1]
    assert s.winners[0]["user_id"] == 2
    ranking = {entry["user_id"]: entry for entry in s.details["ranking"]}
    assert ranking[1]["excluded"] is True


# ── Wejście skryptu ──────────────────────────────────────────────────────


def _payload(**overrides) -> dict:
    base = {
        "mapping": {"10": 1, "20": 2},
        "kpi": [
            {
                "user_id": 10,
                "report_date": "2026-07-06",
                "placements": 1,
                "days_worked": 5,
            },
            {"user_id": 10, "report_date": "2026-10-12", "placements": 9},
            {
                "user_id": 20,
                "report_date": "2026-07-06",
                "is_draft": True,
                "placements": 9,
            },
        ],
        "official": [
            {
                "competition_type": "quarterly",
                "period": "Q2 2026",
                "rank": 1,
                "user_id": 20,
            },
            {
                "competition_type": "monthly_placements",
                "period": "2026-06",
                "rank": 1,
                "user_id": 10,
            },
        ],
        "weights": WEIGHTS,
    }
    base.update(overrides)
    return base


def test_parse_maps_accounts_and_skips_drafts_and_days_after_cutover() -> None:
    parsed = script.parse_payload(_payload())
    assert [(r["user_id"], r["report_date"]) for r in parsed["rows"]] == [
        (1, date(2026, 7, 6))
    ]
    assert parsed["official"][(script.LEAGUE, "Q2 2026")] == [2]
    assert parsed["settled_through"] == {"quarterly": "Q2 2026", "monthly": "2026-06"}
    assert parsed["skipped"] == {"drafts": 1, "after_cutover": 1}


def test_parse_refuses_rows_of_people_without_an_account() -> None:
    payload = _payload(mapping={"10": 1})
    payload["kpi"].append({"user_id": 30, "report_date": "2026-07-06"})
    with pytest.raises(script.InputError, match="30"):
        script.parse_payload(payload)


def test_parse_refuses_two_people_on_one_account() -> None:
    with pytest.raises(script.InputError):
        script.parse_payload(_payload(mapping={"10": 1, "20": 1}))


def test_settlement_periods_end_before_cutover() -> None:
    periods = script.settlement_periods()
    assert (script.LEAGUE, "Q3 2026") in periods
    assert (script.LEAGUE, "Q4 2026") not in periods
    assert ("monthly_placements", "2026-09") in periods
    assert ("monthly_placements", "2026-10") not in periods
    assert len(periods) == 3 + 2 * 9
