"""Nagrody Q4 2026 podwojone, wyścig od października 2026 to premia w Płacach.

Decyzja Artura 06.11.2026: oba wyścigi miesięczne października–grudnia 2026
po 3000 zł, Liga Mistrzów rekruterów Q4 2026 10 000 / 6000 / 4000 zł. Inne
okresy bez zmian; wcześniejsze wyścigi zostają voucherem.
"""

from __future__ import annotations

import pytest

from app.models.competition_winner import CompetitionType
from app.services import competitions

PLACEMENTS = CompetitionType.monthly_placements
RECOMMENDATIONS = CompetitionType.monthly_recommendations
RECRUITER = CompetitionType.quarterly_champions_recruiter
DL = CompetitionType.quarterly_champions_dl


@pytest.mark.parametrize("period", ["2026-10", "2026-11", "2026-12"])
def test_both_races_pay_double_in_q4_2026(period: str) -> None:
    assert competitions._prize_for(PLACEMENTS, 1, period) == 3000
    assert competitions._prize_for(RECOMMENDATIONS, 1, period) == 3000
    assert competitions._prize_for(PLACEMENTS, 2, period) == 0


@pytest.mark.parametrize("period", ["2026-09", "2027-01", None])
def test_races_outside_q4_2026_keep_1500(period) -> None:
    assert competitions._prize_for(PLACEMENTS, 1, period) == 1500


def test_league_q4_2026_doubles_every_paid_place() -> None:
    assert competitions.quarterly_prizes("Q4 2026") == {1: 10_000, 2: 6000, 3: 4000}
    assert competitions.quarterly_prizes("Q1 2027") == {1: 5000, 2: 3000, 3: 2000}
    # Liga DL od Q4 2026 bez nagród — podwojenie jej nie przywraca.
    assert competitions._prize_for(DL, 1, "Q4 2026") == 0


def test_prize_name_says_payroll_from_october_2026() -> None:
    assert competitions.monthly_race_prize_name("2026-10") == "Premia 3 000 zł"
    assert competitions.monthly_race_prize_name("2027-01") == "Premia 1 500 zł"
    assert competitions.monthly_race_prize_name("2026-09").startswith("Voucher")


def test_unknown_period_has_no_multiplier() -> None:
    assert competitions.prize_multiplier("all_time") == 1
    assert competitions.prize_multiplier("2026-13x") == 1


def test_wins_sort_quarters_and_months_on_one_axis() -> None:
    periods = ["2026-10", "Q3 2026", "2026-11", "Q4 2026", "2026-08"]
    ordered = sorted(periods, key=competitions._period_end_month, reverse=True)
    # Q4 2026 kończy się w grudniu, więc stoi przed listopadem.
    assert ordered == ["Q4 2026", "2026-11", "2026-10", "Q3 2026", "2026-08"]


needs_db = pytest.mark.skipif(
    not __import__("os").environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


@needs_db
@pytest.mark.asyncio
async def test_my_wins_lists_only_own_podium_newest_first() -> None:
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.models.competition_winner import CompetitionWinner
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        users = []
        for i in range(2):
            user = User(
                email=f"wins-{i}-{marker}@example.com",
                name=f"Wygrane {i} {marker}",
                role=UserRole.recruiter,
                roles=["recruiter"],
                is_active=True,
                profile_completed=True,
            )
            db.add(user)
            users.append(user)
        await db.flush()
        me, other = users
        db.add_all(
            [
                CompetitionWinner(
                    competition_type=PLACEMENTS.value,
                    period="2098-10",
                    user_id=me.id,
                    rank=1,
                    points=4,
                    metric_value=4,
                    prize_pln=3000,
                ),
                CompetitionWinner(
                    competition_type=RECRUITER.value,
                    period="Q4 2098",
                    user_id=me.id,
                    rank=2,
                    points=900,
                    metric_value=900,
                    prize_pln=6000,
                ),
                CompetitionWinner(
                    competition_type=PLACEMENTS.value,
                    period="2098-11",
                    user_id=other.id,
                    rank=1,
                    points=5,
                    metric_value=5,
                    prize_pln=3000,
                ),
            ]
        )
        await db.commit()
        wins = await competitions.wins_for_user(db, me.id)

    assert [(w["period"], w["rank"], w["prize_pln"]) for w in wins] == [
        ("Q4 2098", 2, 6000),
        ("2098-10", 1, 3000),
    ]
    assert wins[1]["label"] == "Wyścig placementów"
