"""Historia DynaReportera (decyzja Artura 18.10.2026) — bez bazy.

* `scripts.load_dynareporter_history.parse_payload`: mapa kont, granica
  12.10.2026, sumowanie wpisów DL dwóch kont jednej osoby, odmowa przy koncie
  bez odpowiednika w NEXUS-ie;
* Liga DL z wpisów DL (`competition_history.settle_dr_period`): placementy,
  próg 3, remis na płatnym miejscu do admina, bez progu hit ratio.
"""

from __future__ import annotations

import pytest

from app.services import competition_history as history
from scripts.load_dynareporter_history import InputError, parse_payload
from scripts.settle_dl_league_from_dynareporter import settlement_periods


def _payload(**overrides):
    base = {
        "user_map": {"15": 86, "276": 86, "10": 118},
        "clients": [{"id": 13, "name": "Nordea", "is_active": True}],
        "placements": [
            {"user_id": 10, "client_id": 13, "placement_date": "2026-03-02"},
            # 12.10 liczy NEXUS — wiersz z tego dnia nie wchodzi.
            {"user_id": 10, "client_id": 13, "placement_date": "2026-10-12"},
        ],
        "board": [
            {
                "report_month": "2025-06-01",
                "placements": 18,
                "departures": 17,
                "active_consultants": 369,
                "hit_ratio": 0,
            },
            {
                "report_month": "2026-10-01",
                "placements": 0,
                "departures": 0,
                "active_consultants": 0,
                "hit_ratio": 0,
            },
        ],
        "board_clients": [
            {"report_month": "2025-06-01", "client_name": "XPERI", "placement_count": 4}
        ],
        "dl_kpi": [
            {
                "user_id": 15,
                "report_month": "2026-07-01",
                "requests": 1,
                "placements": 2,
                "vacancies": 1,
                "open_requests": 0,
                "open_vacancies": 0,
            },
            {
                "user_id": 276,
                "report_month": "2026-07-01",
                "requests": 0,
                "placements": 1,
                "vacancies": 0,
                "open_requests": 0,
                "open_vacancies": 0,
            },
        ],
        "dl_assignments": [
            {"delivery_lead_user_id": 15, "client_id": 13, "is_head": False},
            {"delivery_lead_user_id": 276, "client_id": 13, "is_head": True},
        ],
    }
    base.update(overrides)
    return base


def test_parse_keeps_only_days_before_the_cutover() -> None:
    parsed = parse_payload(_payload())
    assert [p["placement_date"].isoformat() for p in parsed["placements"]] == [
        "2026-03-02"
    ]
    assert parsed["placements"][0]["user_id"] == 118
    # Raport Rady z października (miesiąc cutoveru) nie wchodzi.
    assert [b["report_month"].isoformat() for b in parsed["board"]] == ["2025-06-01"]


def test_parse_sums_two_dr_accounts_of_one_person() -> None:
    parsed = parse_payload(_payload())
    assert parsed["dl_kpi"] == [
        {
            "user_id": 86,
            "report_month": history.date(2026, 7, 1),
            "requests": 1,
            "placements": 3,
            "vacancies": 1,
            "open_requests": 0,
            "open_vacancies": 0,
        }
    ]
    # Jedno przypisanie na (DL, klient), „head” jeśli którekolwiek było.
    assert parsed["dl_assignments"] == [
        {"delivery_lead_user_id": 86, "client_id": 13, "is_head": True}
    ]


def test_parse_refuses_accounts_without_a_nexus_twin() -> None:
    with pytest.raises(InputError, match="bez konta NEXUS-a"):
        parse_payload(_payload(user_map={"10": 118}))


def test_parse_refuses_unknown_client() -> None:
    bad = _payload()
    bad["placements"][0]["client_id"] = 99
    with pytest.raises(InputError, match="nieznanego klienta"):
        parse_payload(bad)


def _dl_monthly(**by_month):
    return {
        month: {uid: history.DrCounts(placements=n) for uid, n in people.items()}
        for month, people in by_month.items()
    }


def test_dl_league_ranks_placements_without_hit_ratio_threshold() -> None:
    monthly = _dl_monthly(
        **{
            "2026-01": {27: 4, 14: 2, 30: 2},
            "2026-02": {27: 9, 14: 4, 30: 1, 81: 1},
            "2026-03": {27: 8, 14: 6, 30: 3, 81: 1},
        }
    )
    s = history.settle_dr_period(
        "quarterly_champions_dl", "Q1 2026", monthly, names={}, weights={}
    )
    assert s.status == "frozen"
    assert [(w["rank"], w["user_id"], w["metric_value"]) for w in s.winners] == [
        (1, 27, 21),
        (2, 14, 12),
        (3, 30, 6),
    ]
    # Poniżej progu 3 placementów — na liście, bez miejsca nagrodowego.
    ranking = {e["user_id"]: e["qualified"] for e in s.details["ranking"]}
    assert ranking[81] is False


def test_dl_league_tie_on_a_paid_place_goes_to_the_admin() -> None:
    monthly = _dl_monthly(**{"2026-07": {14: 9, 30: 9, 27: 7}})
    s = history.settle_dr_period(
        "quarterly_champions_dl", "Q3 2026", monthly, names={}, weights={}
    )
    assert s.status == "tie_pending"
    assert sorted(s.details["ties"][0]["user_ids"]) == [14, 30]


def test_dl_league_settles_the_three_closed_quarters() -> None:
    assert settlement_periods() == ["Q1 2026", "Q2 2026", "Q3 2026"]
