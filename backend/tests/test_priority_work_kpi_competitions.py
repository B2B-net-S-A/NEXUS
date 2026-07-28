"""Priority Work attribution, KPI and competition semantics."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.models.competition_winner import CompetitionType
from app.models.skill import Skill as _Skill  # noqa: F401
from app.services import competitions
from app.services.kpi_panel import PANEL_KPI_DEFAULTS, VERIFIER_ANCHORED_CTE


class _Result:
    def __init__(self, rows: list[object]):
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> "_Result":
        return self


def _row(
    *,
    user_id: int,
    stage: str,
    count: int,
    name: str = "Recruiter",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        name=name,
        role="recruiter",
        stage=stage,
        cnt=count,
    )


async def test_champions_points_use_cv_sent_and_client_interview_only() -> None:
    rows = [
        _row(user_id=1, stage="hired", count=5),
        _row(user_id=1, stage="client_interview", count=8),
        _row(user_id=1, stage="cv_sent", count=22),
        _row(user_id=1, stage="verified", count=40),
        # An internal interview is deliberately not a client-interview point.
        _row(user_id=1, stage="interview", count=999),
        _row(user_id=2, stage="hired", count=2, name="Below threshold"),
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(rows)))
    ranked = await competitions._rank_recruiters_by_points(
        db,
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end=datetime(2026, 10, 1, tzinfo=timezone.utc),
        min_placements=3,
    )
    assert len(ranked) == 1
    assert ranked[0].metric_value == 980
    assert ranked[0].extras == {
        "role": "recruiter",
        "placements": 5,
        "interviews": 8,
        "recommendations": 22,
        "verifications": 40,
    }


async def test_hall_of_fame_uses_verifier_anchored_placements() -> None:
    rows = [SimpleNamespace(id=7, name="Verifier", cnt=12)]
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(rows)))

    ranked = await competitions.hall_of_fame(db, limit=5)

    statement, params = db.execute.await_args.args
    sql = str(statement)
    assert "FROM credited c" in sql
    assert "c.stage = 'hired'" in sql
    assert "CandidateStage.moved_by" not in sql
    assert params == {"limit": 5}
    assert ranked[0].user_id == 7
    assert ranked[0].metric_value == 12


async def test_monthly_recommendation_qualification_is_four_per_day_and_75_percent(
    monkeypatch,
) -> None:
    rows = [
        SimpleNamespace(
            id=1,
            name="Qualified",
            role="recruiter",
            verifications=40,
            recommendations=30,
        ),
        SimpleNamespace(
            id=2,
            name="Too few verifications",
            role="recruiter",
            verifications=39,
            recommendations=30,
        ),
        SimpleNamespace(
            id=3,
            name="Low precision",
            role="recruiter",
            verifications=40,
            recommendations=29,
        ),
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(rows)))
    monkeypatch.setattr(
        competitions,
        "business_days_elapsed_in_month",
        lambda _year, _month: 10,
    )
    ranked = await competitions.monthly_most_recommendations(db, "2026-07")
    assert [item.user_id for item in ranked] == [1]
    assert ranked[0].extras["qualified"] is True
    assert ranked[0].extras["required_verifications"] == 40
    assert ranked[0].extras["precision_pct"] == 75.0

    statement, params = db.execute.await_args.args
    sql = str(statement).lower()
    assert "c.stage = 'cv_sent'" in sql
    assert "c.stage = 'verified'" in sql
    assert "c.stage = 'interview'" not in sql
    assert "u.roles ?| array['sourcer', 'tac', 'recruiter']" in sql
    assert ":required_verifications" in sql
    assert ":min_precision_pct" in sql
    assert params["required_verifications"] == 40
    assert params["min_precision_pct"] == 75.0


async def test_monthly_recommendation_filters_eligibility_before_limit_ten(
    monkeypatch,
) -> None:
    rows = [
        SimpleNamespace(
            id=11,
            name="Qualified after exclusions",
            role="recruiter",
            verifications=40,
            recommendations=30,
        )
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(rows)))
    monkeypatch.setattr(
        competitions,
        "business_days_elapsed_in_month",
        lambda _year, _month: 10,
    )

    ranked = await competitions.monthly_most_recommendations(db, "2026-07")

    assert [item.user_id for item in ranked] == [11]
    sql = " ".join(str(db.execute.await_args.args[0]).lower().split())
    having_at = sql.rindex(" having ")
    order_at = sql.rindex(" order by recommendations")
    limit_at = sql.rindex(" limit 10")
    assert having_at < order_at < limit_at
    assert (
        "count(*) filter (where c.stage = 'verified') >= :required_verifications"
    ) in sql
    assert (
        "100.0 * count(*) filter (where c.stage = 'cv_sent') "
        ">= :min_precision_pct * count(*) filter (where c.stage = 'verified')"
    ) in sql


def test_business_day_counter_handles_weekends_and_future_months() -> None:
    assert (
        competitions.business_days_elapsed_in_month(
            2026,
            7,
            today=date(2026, 7, 5),
        )
        == 3
    )
    assert (
        competitions.business_days_elapsed_in_month(
            2026,
            8,
            today=date(2026, 7, 28),
        )
        == 0
    )


def test_only_qualified_recruiters_can_receive_monthly_award() -> None:
    ranked = [
        competitions.RankedUser(
            user_id=1,
            name="High but disqualified",
            metric_value=100,
            extras={"qualified": False},
        ),
        competitions.RankedUser(
            user_id=2,
            name="Eligible",
            metric_value=80,
            extras={"qualified": True},
        ),
    ]
    assert [row.user_id for row in competitions.qualified_for_award(ranked)] == [2]


async def test_freeze_filters_disqualified_before_persisting_podium(
    monkeypatch,
) -> None:
    ranked = [
        competitions.RankedUser(
            user_id=1,
            name="Disqualified",
            metric_value=100,
            extras={"qualified": False},
        ),
        competitions.RankedUser(
            user_id=2,
            name="Eligible A",
            metric_value=90,
            extras={"qualified": True},
        ),
        competitions.RankedUser(
            user_id=3,
            name="Eligible B",
            metric_value=80,
            extras={"qualified": True},
        ),
    ]
    monkeypatch.setattr(
        competitions,
        "compute_live",
        AsyncMock(return_value=ranked),
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result([]), _Result([])]),
        add=lambda _row: None,
        commit=AsyncMock(),
    )
    winners = await competitions.freeze_competition(
        db,
        CompetitionType.monthly_recommendations,
        "2026-07",
    )
    assert [winner.user_id for winner in winners] == [2, 3]
    assert winners[0].frozen_snapshot["top"][0]["user_id"] == 2
    db.commit.assert_awaited_once()


async def test_frozen_podium_is_write_once_and_never_recomputed(monkeypatch) -> None:
    existing = [
        SimpleNamespace(rank=1, user_id=7),
        SimpleNamespace(rank=2, user_id=8),
    ]
    compute = AsyncMock(side_effect=AssertionError("must not recompute history"))
    monkeypatch.setattr(competitions, "compute_live", compute)
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result([]), _Result(existing)]),
        commit=AsyncMock(),
    )

    result = await competitions.freeze_competition(
        db,
        CompetitionType.monthly_placements,
        "2026-06",
    )

    assert result == existing
    compute.assert_not_awaited()
    db.commit.assert_awaited_once()


def test_kpi_defaults_preserve_four_per_day_and_75_percent() -> None:
    for role in ("sourcer", "tac", "recruiter"):
        enum_role = next(
            item
            for item in PANEL_KPI_DEFAULTS["verifications_daily"]
            if item.value == role
        )
        assert PANEL_KPI_DEFAULTS["verifications_daily"][enum_role] == 4
        assert PANEL_KPI_DEFAULTS["precision_monthly"][enum_role] == 75


def test_canonical_cte_is_attempt_aware_and_disables_new_process_fallback() -> None:
    normalized = " ".join(VERIFIER_ANCHORED_CTE.split())
    assert "LEAD(rp.opened_at) OVER" in normalized
    assert "PARTITION BY rp.candidate_id, rp.job_id" in normalized
    assert "PARTITION BY cp.id, cs.stage" in normalized
    assert "cp.next_opened_at IS NULL OR cs.moved_at < cp.next_opened_at" in normalized
    assert "cs.verification_status::text = 'active'" in normalized
    assert "COALESCE(cs.approved_at, cs.moved_at)" in normalized
    assert "cp.kpi_eligible IS TRUE" in normalized
    assert "cp.credit_user_id IS NOT NULL" in normalized
    assert "mf.reached_at >= verified.reached_at" in normalized
    assert "afm.first_reached_at < fc.first_opened_at" in normalized
    assert "COALESCE(a.verifier, mf.first_mover)" in normalized
    assert (
        "SELECT * FROM classified_credited UNION ALL SELECT * FROM legacy_credited"
        in normalized
    )
