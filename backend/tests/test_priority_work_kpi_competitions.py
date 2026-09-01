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
from app.models.competition_winner import CompetitionType, CompetitionWinner
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
from app.tasks import competition_autofreeze


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


async def test_champions_points_score_interview_not_client_interview() -> None:
    """Skladnik „interview" punktuje `interview`, NIE `client_interview` (D3).

    Odwrocenie wzgledem poprzedniego kontraktu jest swiadome. `client_interview`
    NIE MA zadnego mapowania z Traffita (`traffit/mappers.py:404-449`), wiec ten
    skladnik byl w praktyce ZAWSZE ZEROWY — a rozdzielal nagrody 5000/3000/2000 PLN.
    Wiersz `client_interview` zostaje w tescie jako dowod, ze przestal punktowac.
    """
    rows = [
        _row(user_id=1, stage="hired", count=5),
        _row(user_id=1, stage="interview", count=8),
        _row(user_id=1, stage="cv_sent", count=22),
        _row(user_id=1, stage="verified", count=40),
        # Martwy skladnik: obecny w danych, nieobecny w punktacji.
        _row(user_id=1, stage="client_interview", count=999),
        _row(user_id=2, stage="hired", count=2, name="Below threshold"),
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(rows)))
    ranked = await competitions._rank_recruiters_by_points(
        db,
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end=datetime(2026, 10, 1, tzinfo=timezone.utc),
        weights={"placement": 150, "interview": 15, "recommendation": 5},
        min_placements=3,
    )

    # Niezakwalifikowani ZOSTAJA w rankingu z flaga (D3) zamiast znikac —
    # wypadniecie z listy czytalo sie jak brak wyniku, a nie jak niespelniony prog.
    assert len(ranked) == 2

    top = ranked[0]
    # 5*150 + 8*15 + 22*5 = 750 + 120 + 110 = 980.
    # Gdyby punktowal `client_interview` (999), liczba bylaby zupelnie inna.
    assert top.metric_value == 980
    assert top.extras["placements"] == 5
    assert top.extras["interviews"] == 8
    assert top.extras["recommendations"] == 22
    assert top.extras["qualified"] is True

    below = ranked[1]
    assert below.extras["qualified"] is False
    assert "MIN_PLACEMENTS_NOT_MET" in below.extras["disqualification_reasons"]


async def test_champions_weights_change_the_ranking() -> None:
    """Sens D3: zmiana wag NAPRAWDE przestawia podium, a nie tylko napis.

    Bez tego testu konfigurowalnosc bylaby deklaracja — formula moglaby czytac
    stala, a endpoint konfiguracji zwracac cos innego, i nikt by nie zauwazyl.
    """
    rows = [
        # A: duzo rekomendacji, malo placementow.
        #   wagi placementowe (150/15/5): 3*150 + 50*5   =  650
        #   wagi rekomendacyjne (1/1/100): 3*1  + 50*100 = 5003
        _row(user_id=1, stage="hired", count=3, name="A"),
        _row(user_id=1, stage="cv_sent", count=50, name="A"),
        # B: odwrotnie.
        #   wagi placementowe: 10*150 + 1*5   = 1505
        #   wagi rekomendacyjne: 10*1  + 1*100 =  110
        _row(user_id=2, stage="hired", count=10, name="B"),
        _row(user_id=2, stage="cv_sent", count=1, name="B"),
    ]

    async def _rank(weights):
        db = SimpleNamespace(execute=AsyncMock(return_value=_Result(rows)))
        return await competitions._rank_recruiters_by_points(
            db,
            start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            end=datetime(2026, 10, 1, tzinfo=timezone.utc),
            weights=weights,
            min_placements=0,
        )

    placement_heavy = await _rank(
        {"placement": 150, "interview": 15, "recommendation": 5}
    )
    recommendation_heavy = await _rank(
        {"placement": 1, "interview": 1, "recommendation": 100}
    )

    assert placement_heavy[0].user_id == 2  # B wygrywa na placementach
    assert recommendation_heavy[0].user_id == 1  # A wygrywa na rekomendacjach


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


async def test_freeze_reports_that_a_frozen_period_was_left_untouched(
    monkeypatch,
) -> None:
    """Niezmienność zostaje — nieodróżnialny raport nie.

    `POST /freeze` na zamrożonym okresie wyglądał dla admina identycznie jak
    świeży zapis: te same wiersze, ten sam `saved_count`. Podium nadal jest
    write-once (patrz test wyżej), ale wynik mówi teraz wprost, że ten call
    NIC nie zapisał — inaczej „poprawiłem podium" znaczy „nie poprawiłem".
    """
    existing = [SimpleNamespace(rank=1, user_id=7), SimpleNamespace(rank=2, user_id=8)]
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

    # Kontrakt zwrotu bez zmian — nadal lista zwycięzców.
    assert result == existing
    assert len(result) == 2
    assert result.already_frozen is True
    assert result.saved_count == 0
    compute.assert_not_awaited()


async def test_fresh_freeze_reports_the_rows_it_actually_wrote(monkeypatch) -> None:
    """Druga strona kontraktu: realny zapis raportuje własne wiersze."""
    ranked = [
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
    monkeypatch.setattr(competitions, "compute_live", AsyncMock(return_value=ranked))
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result([]), _Result([])]),
        add=lambda _row: None,
        commit=AsyncMock(),
    )

    result = await competitions.freeze_competition(
        db,
        CompetitionType.monthly_recommendations,
        "2026-07",
    )

    assert result.already_frozen is False
    assert result.saved_count == len(result) == 2


async def test_autofreeze_guard_accepts_a_full_three_person_podium() -> None:
    """Zamrożony okres ma do 3 wierszy — bramka nie może żądać dokładnie jednego.

    Mock tego nie złapie: MultipleResultsFound rzucał dopiero prawdziwy
    `Result` z Postgresa, a wyjątek z bramki wywracał całą iterację.
    """
    ctype = CompetitionType.monthly_placements
    period = f"T-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"podium-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="Podium",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        for rank in (1, 2, 3):
            db.add(
                CompetitionWinner(
                    competition_type=ctype.value,
                    period=period,
                    user_id=user.id,
                    rank=rank,
                    points=10 - rank,
                    metric_value=10 - rank,
                    prize_pln=0,
                )
            )
        await db.commit()

        assert await competition_autofreeze._is_period_frozen(db, ctype, period) is True
        assert (
            await competition_autofreeze._is_period_frozen(db, ctype, f"{period}-none")
            is False
        )


class _FakeFreezeSession:
    """Sesja-atrapa dla `_run_once` — liczy rollbacki po nieudanym typie."""

    def __init__(self) -> None:
        self.rollbacks = 0

    async def __aenter__(self) -> "_FakeFreezeSession":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def rollback(self) -> None:
        self.rollbacks += 1


async def test_autofreeze_failure_in_one_type_does_not_starve_the_rest(
    monkeypatch,
) -> None:
    """Jeden wywrócony konkurs nie może zabrać reszcie tej samej iteracji.

    Bramka stała PRZED try, więc jej wyjątek uciekał aż do pętli: kolejne
    typy miesięczne i cały blok kwartalny nie były w tej iteracji nawet
    próbowane — a styczeń to jedyny moment, gdy Q4 jest do zamrożenia.
    """
    session = _FakeFreezeSession()
    monkeypatch.setattr(competition_autofreeze, "AsyncSessionLocal", lambda: session)

    async def _guard(_db, ctype, _period) -> bool:
        if ctype is CompetitionType.monthly_recommendations:
            raise RuntimeError("guard exploded")
        return False

    monkeypatch.setattr(competition_autofreeze, "_is_period_frozen", _guard)

    frozen: list[str] = []

    async def _freeze(_db, ctype, period):
        frozen.append(f"{ctype.value}:{period}")
        return competitions.FrozenPodium([object()], already_frozen=False)

    monkeypatch.setattr(competitions, "freeze_competition", _freeze)

    # Styczeń — poprzedni kwartał (Q4 2025) != bieżący, więc blok kwartalny leci.
    results = await competition_autofreeze._run_once(date(2026, 1, 15))

    assert frozen == [
        "monthly_placements:2025-12",
        "quarterly_champions_dl:Q4 2025",
        "quarterly_champions_recruiter:Q4 2025",
    ]
    assert set(results) == set(frozen)
    assert session.rollbacks == 1


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
