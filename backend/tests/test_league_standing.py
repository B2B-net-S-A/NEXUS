"""Pozycja w Lidze Mistrzów do przycisku w górnym pasku (13.10.2026).

Czyste funkcje na wierszach `award_ranked_rows` — bez bazy, biegną lokalnie.
"""

from app.models.user import User, UserRole
from app.services.league_standing import league_kind, league_leaders, league_standing


def _row(user_id: int, value: int, rank: int | None, *, tied: bool = False) -> dict:
    return {
        "user_id": user_id,
        "name": f"Osoba {user_id}",
        "metric_value": value,
        "rank": rank,
        "tied": tied,
        "prize_pln": {1: 5000, 2: 3000, 3: 2000}.get(rank) if rank else None,
        "qualified": rank is not None,
    }


# Kwartał z makiety: sześć osób z miejscem i jedna bez (próg niespełniony).
ROWS = [
    _row(1, 640, 1),
    _row(2, 515, 2),
    _row(3, 470, 3),
    _row(4, 385, 4),
    _row(5, 340, 5),
    _row(6, 290, 6),
    _row(7, 210, None),
]


def test_fourth_place_counts_the_gap_to_the_podium() -> None:
    standing = league_standing(ROWS, 4)
    assert standing["rank"] == 4
    assert standing["value"] == 385
    assert standing["gap_to_podium"] == 85
    assert standing["gap_to_place_above"] == 85
    assert standing["lead_over_next"] == 45
    assert [n["user_id"] for n in standing["neighbours"]] == [2, 3, 4, 5, 6]


def test_sixth_place_still_gets_the_gap_to_the_podium() -> None:
    # `/my-position` oddaje ±2 sąsiadów, więc od 6. miejsca 3. miejsca nie widać.
    standing = league_standing(ROWS, 6)
    assert standing["gap_to_podium"] == 180
    assert standing["gap_to_place_above"] == 50


def test_leader_has_a_lead_and_no_gap() -> None:
    standing = league_standing(ROWS, 1)
    assert standing["rank"] == 1
    assert standing["gap_to_place_above"] is None
    assert standing["lead_over_next"] == 125
    assert standing["gap_to_podium"] is None
    assert [n["user_id"] for n in standing["neighbours"]] == [1, 2, 3]


def test_podium_place_has_no_gap_to_the_podium() -> None:
    standing = league_standing(ROWS, 2)
    assert standing["gap_to_place_above"] == 125
    assert standing["lead_over_next"] == 45
    assert standing["gap_to_podium"] is None


def test_unqualified_person_has_no_place_but_a_position_by_points() -> None:
    standing = league_standing(ROWS, 7)
    assert standing["rank"] is None
    assert standing["me"]["qualified"] is False
    assert standing["position_by_value"] == 7
    assert standing["gap_to_podium"] == 260
    assert standing["lead_over_next"] is None
    assert standing["gap_to_place_above"] is None


def test_unqualified_above_the_podium_score_has_no_negative_gap() -> None:
    rows = [_row(2, 300, 1), _row(3, 200, 2), _row(4, 150, 3), _row(1, 900, None)]
    standing = league_standing(rows, 1)
    assert standing["position_by_value"] == 1
    assert standing["gap_to_podium"] == 0


def test_person_without_points_counts_from_zero() -> None:
    standing = league_standing(ROWS, 99)
    assert standing["me"] is None
    assert standing["rank"] is None
    assert standing["value"] == 0
    assert standing["gap_to_podium"] == 470
    assert standing["neighbours"] == []
    assert standing["position_by_value"] is None


def test_incomplete_podium_has_no_gap() -> None:
    rows = [_row(1, 300, 1), _row(2, 200, 2), _row(3, 120, None)]
    assert league_standing(rows, 3)["gap_to_podium"] is None


def test_tie_flag_reaches_the_neighbours() -> None:
    rows = [_row(1, 640, 1), _row(2, 470, 2), _row(3, 470, 3, tied=True)]
    neighbours = league_standing(rows, 3)["neighbours"]
    assert neighbours[-1]["tied"] is True
    assert set(neighbours[-1]) == {
        "rank",
        "user_id",
        "name",
        "metric_value",
        "hit_ratio",
        "prize_pln",
        "tied",
    }


def _dl_row(user_id: int, placements: int, hit_ratio, rank: int | None) -> dict:
    return {
        "user_id": user_id,
        "name": f"DL {user_id}",
        "metric_value": placements,
        "hit_ratio": hit_ratio,
        "rank": rank,
        "tied": False,
        "prize_pln": 0 if rank else None,
    }


# Liga DL od 25.10.2026: kolejność po hit ratio, `metric_value` = placementy.
DL_ROWS = [
    _dl_row(21, 5, 41.7, 1),
    _dl_row(22, 4, 36.4, 2),
    _dl_row(25, 7, 30.0, 3),
    _dl_row(26, 3, 27.3, 4),
    _dl_row(23, 2, 50.0, None),
    _dl_row(24, 0, None, None),
]


def test_dl_league_distances_are_in_hit_ratio_points() -> None:
    second = league_standing(DL_ROWS, 22, value_key="hit_ratio")
    assert second["value"] == 36.4
    assert second["gap_to_place_above"] == 5.3
    assert second["lead_over_next"] == 6.4
    # Więcej placementów, ale niższe hit ratio — dystans liczy procent.
    fourth = league_standing(DL_ROWS, 26, value_key="hit_ratio")
    assert fourth["gap_to_podium"] == 2.7


def test_dl_without_a_place_is_compared_by_hit_ratio() -> None:
    # 2 z 4 to 50%, ale bez 3 placementów nie ma miejsca: podium ma problem
    # z warunkiem, nie z procentem — dystans 0, pozycja po samym procencie 1.
    standing = league_standing(DL_ROWS, 23, value_key="hit_ratio")
    assert standing["rank"] is None
    assert standing["gap_to_podium"] == 0
    assert standing["position_by_value"] == 1
    # Bez zamkniętych rekrutacji hit ratio nie istnieje — liczy się jak 0.
    none = league_standing(DL_ROWS, 24, value_key="hit_ratio")
    assert none["value"] == 0
    assert none["gap_to_podium"] == 30.0


def test_leaders_skip_people_without_a_place() -> None:
    # Niezakwalifikowany z najwyższym wynikiem nie jest „prowadzącym”.
    rows = [*ROWS[:6], _row(9, 900, None)]
    leaders = league_leaders(rows)
    assert [r["user_id"] for r in leaders] == [1, 2, 3, 4, 5]
    assert league_leaders(rows, limit=1)[0]["name"] == "Osoba 1"


def _user(role: UserRole, *extra: UserRole) -> User:
    return User(role=role, roles=[r.value for r in extra])


def test_league_kind_follows_the_league_roles() -> None:
    assert league_kind(_user(UserRole.recruiter)) == "recruiter"
    assert league_kind(_user(UserRole.delivery_lead)) == "delivery_lead"
    # HoR/TCM z rolą rekrutera grają w lidze rekruterów.
    assert (
        league_kind(_user(UserRole.head_of_recruitment, UserRole.recruiter))
        == "recruiter"
    )
    # HoR z rolą DL jest w lidze DL, choć zakres pulpitu daje mu „zespół”.
    assert league_kind(_user(UserRole.head_of_recruitment, UserRole.delivery_lead)) == (
        "delivery_lead"
    )
    # Obie role: jedna liga na osobę — DL.
    assert (
        league_kind(_user(UserRole.delivery_lead, UserRole.recruiter))
        == "delivery_lead"
    )
    for role in (
        UserRole.admin,
        UserRole.finance,
        UserRole.head_of_recruitment,
        UserRole.talent_community_manager,
        UserRole.user,
    ):
        assert league_kind(_user(role)) == "spectator", role


def test_tie_for_comes_from_the_tie_group_not_the_row_flag() -> None:
    # Remis 1. i 2. miejsca: osoba z 2. miejsca walczy o 1.
    rows = [_row(1, 640, 1, tied=True), _row(2, 640, 2, tied=True), _row(3, 470, 3)]
    ties = [{"positions": [1, 2], "user_ids": [1, 2]}]
    assert league_standing(rows, 2, ties)["tie_for"] == 1
    assert league_standing(rows, 3, ties)["tie_for"] is None
    # Remis 3. i 4.: pozycje remisu kończą się na podium, flagę ma tylko 3.,
    # ale 4. miejsce też walczy o 3.
    rows = [*ROWS[:2], _row(3, 470, 3, tied=True), _row(4, 470, 4)]
    ties = [{"positions": [3], "user_ids": [3, 4]}]
    assert league_standing(rows, 4, ties)["tie_for"] == 3
    assert league_standing(rows, 4)["tie_for"] is None
