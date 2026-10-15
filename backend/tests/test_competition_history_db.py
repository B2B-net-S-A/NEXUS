"""Wyniki 2026 sprzed NEXUS-a na żywym Postgresie.

* Q4 2026 dokłada dni do 11.10 z `dr_kpi_body_leasing` — wpis z 12.10, szkic
  i osoba nieaktywna się nie liczą;
* okres zamknięty `/current` i `/monthly-races` pokazują z zamrożenia;
* `freeze_competition` zapisuje listę i źródło.

Ranking Q4 2026 jest globalny dla okna, więc asercje patrzą na własne konta
testu, nie na kolejność całej listy. Okresy zamrożone — w losowym, dalekim
roku (baza testowa nie jest czyszczona).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from app.api import competitions as competitions_api
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.competition_period_closure import CompetitionPeriodClosure
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.dr_kpi_body_leasing import DrKpiBodyLeasing
from app.models.user import User, UserRole
from app.services import competition_history as history
from app.services import competitions

WEIGHTS = {"placement": 150, "interview": 15, "recommendation": 5}


def _year() -> int:
    return 4000 + int(uuid.uuid4().hex[:6], 16) % 900


async def _user(db, *, active: bool = True) -> User:
    user = User(
        email=f"dr-history-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("x"),
        name="Osoba testowa",
        role=UserRole.recruiter,
        is_active=active,
    )
    db.add(user)
    await db.flush()
    return user


def _week(
    user_id: int, day: date, *, draft: bool = False, **counts
) -> DrKpiBodyLeasing:
    return DrKpiBodyLeasing(
        user_id=user_id,
        report_date=day,
        week_number=day.isocalendar()[1],
        is_draft=draft,
        days_worked=counts.pop("days_worked", 5),
        **counts,
    )


async def test_q4_2026_adds_dynareporter_days_before_cutover_only() -> None:
    async with AsyncSessionLocal() as db:
        player = await _user(db)
        gone = await _user(db, active=False)
        db.add_all(
            [
                _week(
                    player.id,
                    date(2026, 10, 5),
                    placements=2,
                    interviews=3,
                    recommendations=4,
                    verifications=20,
                ),
                # 12.10 liczy NEXUS — wpis DynaReportera z tego dnia nie wchodzi.
                _week(player.id, date(2026, 10, 12), placements=7),
                _week(player.id, date(2026, 9, 28), draft=True, placements=9),
                _week(gone.id, date(2026, 10, 5), placements=5),
            ]
        )
        await db.flush()

        start, end = competitions.quarter_bounds(2026, 4)
        league = await competitions._rank_recruiters_by_points(
            db, start=start, end=end, weights=WEIGHTS, min_placements=0
        )
        mine = next(r for r in league if r.user_id == player.id)
        assert mine.extras["placements"] == 2
        assert mine.extras["interviews"] == 3
        assert mine.extras["recommendations"] == 4
        assert mine.metric_value == 2 * 150 + 3 * 15 + 4 * 5
        assert gone.id not in {r.user_id for r in league}

        month_start, month_end = competitions.month_bounds(2026, 10)
        placements = await competitions._rank_recruiters_by_stage(
            db,
            stage=competitions.PipelineStage.hired,
            start=month_start,
            end=month_end,
        )
        assert next(r for r in placements if r.user_id == player.id).metric_value == 2
        await db.rollback()


async def test_period_after_cutover_ignores_dynareporter_rows() -> None:
    async with AsyncSessionLocal() as db:
        player = await _user(db)
        db.add(_week(player.id, date(2027, 1, 4), placements=3))
        await db.flush()
        start, end = competitions.quarter_bounds(2027, 1)
        league = await competitions._rank_recruiters_by_points(
            db, start=start, end=end, weights=WEIGHTS
        )
        assert player.id not in {r.user_id for r in league}
        await db.rollback()


async def test_frozen_period_is_served_from_the_freeze() -> None:
    year = _year()
    period = f"Q2 {year}"
    async with AsyncSessionLocal() as db:
        first = await _user(db)
        second = await _user(db)
        entry = lambda u, pts: {  # noqa: E731
            "user_id": u.id,
            "name": "x",
            "metric_value": pts,
            "hit_ratio": None,
            "placements": 3,
            "interviews": 0,
            "recommendations": 0,
            "verifications": 0,
            "qualified": True,
        }
        db.add(
            CompetitionPeriodClosure(
                competition_type=CompetitionType.quarterly_champions_recruiter.value,
                period=period,
                status="frozen",
                details={
                    "source": history.SOURCE_DYNAREPORTER,
                    "source_note": history.DYNAREPORTER_SOURCE_NOTE,
                    "ties": [],
                    "top": [entry(first, 900), entry(second, 500)],
                    "rows": [
                        {
                            **entry(first, 900),
                            "rank": 1,
                            "tied": False,
                            "excluded": False,
                            "prize_pln": 5000,
                        },
                        {
                            **entry(second, 500),
                            "rank": 2,
                            "tied": False,
                            "excluded": False,
                            "prize_pln": 3000,
                        },
                    ],
                },
            )
        )
        for rank, user, pts, prize in ((1, first, 900, 5000), (2, second, 500, 3000)):
            db.add(
                CompetitionWinner(
                    competition_type=CompetitionType.quarterly_champions_recruiter.value,
                    period=period,
                    user_id=user.id,
                    rank=rank,
                    metric_value=pts,
                    points=pts,
                    prize_pln=prize,
                    frozen_snapshot={},
                )
            )
        await db.flush()

        payload = await competitions_api._compute_current(
            db, CompetitionType.quarterly_champions_recruiter, period
        )
        assert payload["is_frozen"] is True
        assert payload["closure_status"] == "frozen"
        assert payload["source"] == history.SOURCE_DYNAREPORTER
        assert payload["source_note"] == history.DYNAREPORTER_SOURCE_NOTE
        assert payload["days_remaining"] is None
        assert [r["user_id"] for r in payload["top3"]] == [first.id, second.id]
        # Nazwisko z konta, nie z migawki.
        assert payload["top3"][0]["name"] == "Osoba testowa"
        assert [r["rank"] for r in payload["full_ranking"]] == [1, 2]
        await db.rollback()


async def test_resolved_tie_loser_has_no_place_and_no_prize() -> None:
    year = _year()
    period = f"Q3 {year}"
    ctype = CompetitionType.quarterly_champions_recruiter
    async with AsyncSessionLocal() as db:
        lead, loser, chosen = await _user(db), await _user(db), await _user(db)

        def row(user, rank, prize, tied):
            return {
                "user_id": user.id,
                "name": "x",
                "metric_value": 500,
                "hit_ratio": None,
                "qualified": True,
                "rank": rank,
                "tied": tied,
                "excluded": False,
                "prize_pln": prize,
            }

        db.add(
            CompetitionPeriodClosure(
                competition_type=ctype.value,
                period=period,
                status="tie_resolved",
                details={
                    "ties": [{"positions": [3], "user_ids": [loser.id, chosen.id]}],
                    "rows": [
                        row(lead, 1, 5000, False),
                        row(loser, 3, 0, True),
                        row(chosen, 3, 0, True),
                    ],
                },
            )
        )
        for rank, user, prize in ((1, lead, 5000), (3, chosen, 2000)):
            db.add(
                CompetitionWinner(
                    competition_type=ctype.value,
                    period=period,
                    user_id=user.id,
                    rank=rank,
                    metric_value=500,
                    points=500,
                    prize_pln=prize,
                    frozen_snapshot={},
                )
            )
        await db.flush()

        frozen = await competitions.frozen_result(db, ctype, period)
        by_id = {r["user_id"]: r for r in frozen.rows}
        assert (by_id[chosen.id]["rank"], by_id[chosen.id]["prize_pln"]) == (3, 2000)
        assert by_id[chosen.id]["tied"] is False
        assert (by_id[loser.id]["rank"], by_id[loser.id]["prize_pln"]) == (None, None)
        assert frozen.ties == []
        assert [r["user_id"] for r in frozen.rows][-1] == loser.id
        await db.rollback()


async def test_open_period_reports_its_source() -> None:
    year = _year()
    async with AsyncSessionLocal() as db:
        payload = await competitions_api._compute_current(
            db, CompetitionType.quarterly_champions_recruiter, f"Q1 {year}"
        )
        assert payload["is_frozen"] is False
        assert payload["closure_status"] is None
        assert payload["source"] == history.SOURCE_NEXUS
        assert payload["source_note"] is None
        await db.rollback()


async def test_freeze_stores_rows_ranking_and_source() -> None:
    year = _year()
    period = f"{year}-03"
    async with AsyncSessionLocal() as db:
        await competitions.freeze_competition(
            db, CompetitionType.monthly_placements, period
        )
    async with AsyncSessionLocal() as db:
        closure = (
            await db.execute(
                select(CompetitionPeriodClosure).where(
                    CompetitionPeriodClosure.competition_type
                    == CompetitionType.monthly_placements.value,
                    CompetitionPeriodClosure.period == period,
                )
            )
        ).scalar_one()
        assert closure.details["source"] == history.SOURCE_NEXUS
        assert closure.details["rows"] == []
        assert closure.details["ranking"] == []

        races = await competitions.compose_monthly_races(db, period)
        # Zamknięty tylko wyścig placementów — karta nie miesza stanów, więc
        # oba wyścigi idą jeszcze na żywo.
        assert races["placements"]["is_frozen"] is False
        await competitions.freeze_competition(
            db, CompetitionType.monthly_recommendations, period
        )
    async with AsyncSessionLocal() as db:
        races = await competitions.compose_monthly_races(db, period)
        assert races["placements"]["is_frozen"] is True
        assert races["placements"]["closure_status"] == "no_winner"
        assert races["recommendations"]["days_remaining"] is None
