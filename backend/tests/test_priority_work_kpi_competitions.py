"""Priority Work attribution, KPI and competition semantics."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competition_winner import CompetitionType
from app.models.job import Job
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.skill import Skill as _Skill  # noqa: F401
from app.models.user import User, UserRole
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


def _race_row(
    *,
    user_id: int,
    name: str,
    verifications: int,
    recommendations: int,
    qualified: bool,
) -> SimpleNamespace:
    """Wiersz tak, jak zwraca go `race_ranked` (z kolumną `qualified` z SQL)."""
    return SimpleNamespace(
        id=user_id,
        name=name,
        role="recruiter",
        verifications=verifications,
        recommendations=recommendations,
        qualified=qualified,
    )


async def test_monthly_recommendation_qualification_is_four_per_day_and_75_percent(
    monkeypatch,
) -> None:
    rows = [
        _race_row(
            user_id=1,
            name="Qualified",
            verifications=40,
            recommendations=30,
            qualified=True,
        ),
        _race_row(
            user_id=2,
            name="Too few verifications",
            verifications=39,
            recommendations=30,
            qualified=False,
        ),
        _race_row(
            user_id=3,
            name="Low precision",
            verifications=40,
            recommendations=29,
            qualified=False,
        ),
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(rows)))
    monkeypatch.setattr(
        competitions,
        "business_days_elapsed_in_month",
        lambda _year, _month: 10,
    )
    ranked = await competitions.monthly_most_recommendations(db, "2026-07")
    # Ranking pokazuje wszystkich; nagrodę zawęża dopiero qualified_for_award.
    assert [item.user_id for item in ranked] == [1, 2, 3]
    assert [item.user_id for item in competitions.qualified_for_award(ranked)] == [1]
    assert ranked[0].extras["qualified"] is True
    assert ranked[0].extras["required_verifications"] == 40
    assert ranked[0].extras["precision_pct"] == 75.0
    assert ranked[1].extras["qualified"] is False
    assert ranked[1].extras["disqualification_reasons"] == ["MIN_VERIFICATIONS_NOT_MET"]
    assert ranked[2].extras["qualified"] is False
    assert ranked[2].extras["disqualification_reasons"] == ["MIN_PRECISION_NOT_MET"]

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


async def test_monthly_recommendation_ranking_keeps_unqualified_entrants(
    monkeypatch,
) -> None:
    """Mid-month nikt nie dobił progu — widget ma pokazać ranking, nie pustkę."""
    rows = [
        _race_row(
            user_id=5,
            name="Leader so far",
            verifications=12,
            recommendations=11,
            qualified=False,
        ),
        _race_row(
            user_id=6,
            name="Runner up",
            verifications=9,
            recommendations=7,
            qualified=False,
        ),
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(rows)))
    monkeypatch.setattr(
        competitions,
        "business_days_elapsed_in_month",
        lambda _year, _month: 10,
    )

    ranked = await competitions.monthly_most_recommendations(db, "2026-07")

    assert [item.user_id for item in ranked] == [5, 6]
    assert all(item.extras["qualified"] is False for item in ranked)
    assert competitions.qualified_for_award(ranked) == []


async def test_monthly_recommendation_qualification_is_not_applied_in_having(
    monkeypatch,
) -> None:
    """Progi nagrody = kolumna `qualified`; HAVING zostaje tylko na >= 1 rekomendacji.

    Dodatkowo LIMIT jest oknem WYŚWIETLANIA, więc zakwalifikowany spoza TOP 10
    musi mieć własną furtkę (`rank_in_group`), żeby nie stracić nagrody.
    """
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result([])))
    monkeypatch.setattr(
        competitions,
        "business_days_elapsed_in_month",
        lambda _year, _month: 10,
    )

    await competitions.monthly_most_recommendations(db, "2026-07")

    statement, params = db.execute.await_args.args
    sql = " ".join(str(statement).lower().split())
    having_at = sql.rindex(" having ")
    having_clause = sql[having_at : sql.index(" ), race_ranked")]
    assert ":required_verifications" not in having_clause
    assert ":min_precision_pct" not in having_clause
    assert "count(*) filter (where c.stage = 'cv_sent') >= 1" in having_clause
    # Kwalifikacja jako kolumna, nie jako filtr.
    assert (
        "count(*) filter (where c.stage = 'verified') >= :required_verifications"
    ) in sql
    assert (
        "100.0 * count(*) filter (where c.stage = 'cv_sent') "
        ">= cast(:min_precision_pct as numeric) "
        "* count(*) filter (where c.stage = 'verified')"
    ) in sql
    assert ") as qualified" in sql
    assert (
        "where display_rank <= :ranking_size "
        "or (qualified and rank_in_group <= :ranking_size)"
    ) in sql
    assert params["ranking_size"] == competitions.MONTHLY_RACE_RANKING_SIZE


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


def test_business_day_counter_skips_polish_public_holidays() -> None:
    """Styczeń 2026: 22 dni Pon–Pt, ale 1 i 6 stycznia to święta ustawowe."""
    assert (
        competitions.business_days_elapsed_in_month(
            2026,
            1,
            today=date(2026, 2, 1),
        )
        == 20
    )
    # 1 stycznia (czwartek) samo w sobie nie jest dniem roboczym.
    assert (
        competitions.business_days_elapsed_in_month(
            2026,
            1,
            today=date(2026, 1, 1),
        )
        == 0
    )
    # Do 6 stycznia (wtorek, Trzech Króli) roboczo: 2 i 5 stycznia.
    assert (
        competitions.business_days_elapsed_in_month(
            2026,
            1,
            today=date(2026, 1, 6),
        )
        == 2
    )


# Miesiąc daleko w przyszłości — żadna inna suita nie seeduje tam milestone'ów,
# więc ranking liczony globalnie nie łapie cudzych danych.
_RACE_MONTH = datetime(2033, 5, 2, 9, 0, tzinfo=timezone.utc)


async def _seed_race_recruiter(db, *, name: str, verified: int, cv_sent: int) -> int:
    """`verified` par kandydat×job, z czego `cv_sent` dostaje też rekomendację."""
    u = uuid.uuid4().hex[:8]
    user = User(
        email=f"race-{u}@example.com",
        password_hash=hash_password("x"),
        name=name,
        role=UserRole.recruiter,
        is_active=True,
    )
    client = Client(name=f"Race Client {u}")
    db.add_all([user, client])
    await db.flush()
    job = Job(title=f"Race Job {u}", client_id=client.id)
    db.add(job)
    await db.flush()

    for idx in range(verified):
        cand = Candidate(name="Rita", lastname=f"RACE-{u}-{idx}")
        db.add(cand)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_at=_RACE_MONTH + timedelta(hours=idx),
                moved_by=user.id,
                verification_status=VerificationStatus.active,
            )
        )
        if idx < cv_sent:
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=_RACE_MONTH + timedelta(hours=idx, minutes=30),
                    moved_by=user.id,
                )
            )
    await db.commit()
    return user.id


async def test_monthly_race_sql_ranks_unqualified_and_awards_only_qualified(
    monkeypatch,
) -> None:
    """Ten sam kontrakt co testy mockowe, ale na ŻYWYM Postgresie.

    Mock nie złapie błędu składni ani typów w oknie `race_ranked`, a to właśnie
    ta część zdecydowała, czy widget „Wyścig Rekomendacji" pokazuje cokolwiek.
    """
    monkeypatch.setattr(
        competitions,
        "business_days_elapsed_in_month",
        lambda _year, _month: 1,  # próg = 4 weryfikacje
    )
    async with AsyncSessionLocal() as db:
        loud_id = await _seed_race_recruiter(
            db, name="Loud but imprecise", verified=8, cv_sent=5
        )
        precise_id = await _seed_race_recruiter(
            db, name="Fewer but precise", verified=4, cv_sent=4
        )
        ranked = await competitions.monthly_most_recommendations(db, "2033-05")

    order = [item.user_id for item in ranked]
    assert order.index(loud_id) < order.index(precise_id), (
        "ranking must stay ordered by recommendations, not by qualification"
    )
    by_id = {item.user_id: item for item in ranked}
    # Lider rekomendacji nie spełnia progu 75% precision — ale JEST w rankingu.
    assert by_id[loud_id].extras["qualified"] is False
    assert by_id[loud_id].extras["disqualification_reasons"] == [
        "MIN_PRECISION_NOT_MET"
    ]
    assert by_id[loud_id].extras["precision_pct"] == 62.5
    assert by_id[precise_id].extras["qualified"] is True

    award = [item.user_id for item in competitions.qualified_for_award(ranked)]
    assert loud_id not in award
    assert precise_id in award


def test_monthly_race_threshold_uses_holiday_aware_business_days() -> None:
    """Próg nagrody = 4 × dni robocze; święta obniżają go, nie zawyżają."""
    elapsed = competitions.business_days_elapsed_in_month(
        2026, 1, today=date(2026, 2, 1)
    )
    required = competitions.MONTHLY_RACE_MIN_VERIFICATIONS_PER_DAY * elapsed
    assert required == 80  # a NIE 88 (22 dni Pon–Pt × 4)


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


def test_canonical_cte_is_attempt_aware_and_anchors_credit_on_verifier() -> None:
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
        "SELECT * FROM classified_credited "
        "UNION ALL SELECT * FROM classified_fallback "
        "UNION ALL SELECT * FROM legacy_credited" in normalized
    )


def test_classified_process_without_verifier_keeps_pre_anchor_credit() -> None:
    """Brak kotwicy nie może kasować kamienia milowego z KPI.

    `credit_user_id` ustawia się dopiero przy zaakceptowanym `verified`, więc
    proces cv_sent → client_interview → hired nie miałby ŻADNEGO creditu i
    znikał z „Moje KPI", raportów i hall of fame. Fallback przywraca atrybucję
    sprzed modelu verifier-anchored (autor ruchu / weryfikator), a rozłączność
    z kotwicą gwarantuje, że milestone liczy się dokładnie raz.
    """
    normalized = " ".join(VERIFIER_ANCHORED_CTE.split())
    assert "classified_fallback AS (" in normalized
    assert "COALESCE(verified.first_mover, mf.first_mover) AS credit_user" in normalized
    # Rozłączność: fallback bierze wyłącznie procesy bez wiersza w kotwicy.
    assert "LEFT JOIN classified_anchor anchored ON anchored.process_id" in normalized
    assert "anchored.process_id IS NULL" in normalized
    # Fallback nie omija bramki kwalifikowalności KPI.
    assert normalized.count("cp.kpi_eligible IS TRUE") == 2
