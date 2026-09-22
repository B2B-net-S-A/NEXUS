"""Regulamin wypłaty konkursów płatnych (audyt 22.09.2026).

Testy na ŻYWYM Postgresie — rankingi, wykluczenie i remisy siedzą w SQL-u
(`VERIFIER_ANCHORED_CTE`, `analytics_first_milestones`), więc mock `db.execute`
niczego by tu nie dowiódł. Każdy test zasiewa dane w WŁASNYM, losowym roku:
rankingi są globalne dla okna, a testowa baza nie jest czyszczona.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competition_period_closure import CompetitionPeriodClosure
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.skill import Skill as _Skill  # noqa: F401
from app.models.user import User, UserRole
from app.services import competition_rules, competitions
from app.tasks import competition_autofreeze

_BACKEND = Path(__file__).resolve().parents[1]


def _year() -> int:
    # Rok per TEST, poza zakresem innych suit (2100–2599 w wyścigach).
    return 3000 + int(uuid.uuid4().hex[:6], 16) % 900


def _at(year: int, month: int, day: int, hour: int = 10) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=timezone.utc)


async def _user(db, name: str, role: UserRole = UserRole.recruiter) -> User:
    u = uuid.uuid4().hex[:8]
    user = User(
        email=f"contest-{u}@example.com",
        password_hash=hash_password("x"),
        name=name,
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _job(db, *, dl_id: int | None = None, closed_at=None) -> Job:
    u = uuid.uuid4().hex[:8]
    client = Client(name=f"Contest Client {u}")
    db.add(client)
    await db.flush()
    job = Job(
        title=f"Contest Job {u}",
        client_id=client.id,
        delivery_lead_id=dl_id,
        closed_at=closed_at,
    )
    db.add(job)
    await db.flush()
    return job


async def _pair(
    db,
    *,
    user: User,
    job: Job,
    at: datetime,
    stages: tuple[PipelineStage, ...],
) -> Candidate:
    """Para kandydat×oferta: weryfikacja `user` + dalsze etapy co 10 minut."""
    cand = Candidate(name="Konkurs", lastname=f"C-{uuid.uuid4().hex[:8]}")
    db.add(cand)
    await db.flush()
    db.add(
        CandidateStage(
            candidate_id=cand.id,
            job_id=job.id,
            stage=PipelineStage.verified,
            moved_at=at,
            moved_by=user.id,
            verification_status=VerificationStatus.active,
        )
    )
    for idx, stage in enumerate(stages, start=1):
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=stage,
                moved_at=at + timedelta(minutes=10 * idx),
                moved_by=user.id,
            )
        )
    await db.flush()
    return cand


async def _contract(db, cand: Candidate, job: Job, *, client: int, cost: int):
    db.add(
        Contract(
            candidate_id=cand.id,
            client_id=job.client_id,
            job_id=job.id,
            start_date=date(2000, 1, 1),
            rate_unit=RateUnit.hourly,
            billing_hours_per_month=160,
            rate_client=Decimal(client),
            rate_candidate=Decimal(cost),
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            status=ContractStatus.active,
        )
    )
    await db.flush()


async def _closure(db, ctype: CompetitionType, period: str):
    return (
        await db.execute(
            select(CompetitionPeriodClosure).where(
                CompetitionPeriodClosure.competition_type == ctype.value,
                CompetitionPeriodClosure.period == period,
            )
        )
    ).scalar_one_or_none()


async def _winners(db, ctype: CompetitionType, period: str) -> list[CompetitionWinner]:
    return list(
        (
            await db.execute(
                select(CompetitionWinner)
                .where(
                    CompetitionWinner.competition_type == ctype.value,
                    CompetitionWinner.period == period,
                )
                .order_by(CompetitionWinner.rank)
            )
        )
        .scalars()
        .all()
    )


_HIRED = (PipelineStage.cv_sent, PipelineStage.hired)


# ── 1. Wykluczenie lidera kwartału danego MIESIĄCA ─────────────────────────


async def test_freeze_excludes_leader_of_the_months_quarter() -> None:
    """Lider Q1 nie bierze nagrody za luty — ani na ekranie, ani przy wypłacie.

    Do 22.09 wykluczenie znał tylko ekran, i to liczone z BIEŻĄCEGO kwartału
    (dziś Q3 2026) — przy zamrożeniu lider kwartału zgarniał też wyścig.
    """
    year = _year()
    period = f"{year}-02"
    async with AsyncSessionLocal() as db:
        leader = await _user(db, "Lider kwartału")
        runner = await _user(db, "Druga osoba")
        job = await _job(db)
        for day in (3, 4, 5):
            await _pair(db, user=leader, job=job, at=_at(year, 2, day), stages=_HIRED)
        for day in (6, 9):
            await _pair(db, user=runner, job=job, at=_at(year, 2, day), stages=_HIRED)
        await db.commit()

        exclusion = await competitions.monthly_race_excluded_user_ids(db, period)
        assert exclusion.user_ids == frozenset({leader.id})
        assert exclusion.quarter_period == f"Q1 {year}"
        assert exclusion.source == "live_quarter_to_month_end"

        races = await competitions.compose_monthly_races(db, period)
        placements = races["placements"]
        assert placements["excluded_user_ids"] == [leader.id]
        assert placements["qualified_leader"]["user_id"] == runner.id

        podium = await competitions.freeze_competition(
            db, CompetitionType.monthly_placements, period, reason="autofreeze"
        )
        assert podium.closure_status == "frozen"
        winners = await _winners(db, CompetitionType.monthly_placements, period)
        assert [w.user_id for w in winners] == [runner.id]
        assert winners[0].prize_pln == competitions.MONTHLY_RACE_PRIZE_PLN
        snapshot = winners[0].frozen_snapshot
        assert snapshot["excluded_user_ids"] == [leader.id]
        assert snapshot["freeze_reason"] == "autofreeze"
        assert snapshot["exclusion_quarter"] == f"Q1 {year}"


async def test_exclusion_prefers_the_frozen_quarter_winner() -> None:
    year = _year()
    async with AsyncSessionLocal() as db:
        frozen = await _user(db, "Zamrożony zwycięzca")
        db.add(
            CompetitionWinner(
                competition_type=CompetitionType.quarterly_champions_recruiter.value,
                period=f"Q2 {year}",
                user_id=frozen.id,
                rank=1,
                points=1,
                metric_value=1,
                prize_pln=5000,
            )
        )
        await db.commit()
        exclusion = await competitions.monthly_race_excluded_user_ids(db, f"{year}-06")
    assert exclusion.user_ids == frozenset({frozen.id})
    assert exclusion.source == "frozen_quarter"


# ── 2. Termin zamknięcia: 3. dzień roboczy + dzienny import Traffita ──────


def test_third_business_day_skips_weekends_and_holidays() -> None:
    # 31.08.2026 (pon) → 1, 2, 3 września.
    assert competition_rules.nth_business_day_after(date(2026, 8, 31)) == date(
        2026, 9, 3
    )
    # 31.12.2025 (śr) → 2.01 (pt), 5.01 (pon), 7.01 (śr; 1.01 i 6.01 święta).
    assert competition_rules.nth_business_day_after(date(2025, 12, 31)) == date(
        2026, 1, 7
    )


async def test_traffit_marker_must_come_from_a_run_started_after_period_end() -> None:
    boundary = datetime(2026, 8, 31, 22, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        # Zmiana znacznika tylko w tej transakcji — cofamy ją na końcu, bo
        # `__daily__` czytają też sondy zdrowia w innych testach.
        for watermark, expected in (
            (boundary - timedelta(hours=1), False),
            (boundary + timedelta(hours=4), True),
        ):
            await db.execute(
                text(
                    """
                    INSERT INTO traffit_sync_state (phase, last_synced_at,
                        last_status, created_at, updated_at)
                    VALUES ('__daily__', :wm, 'ok', now(), now())
                    ON CONFLICT (phase) DO UPDATE SET last_synced_at = :wm
                    """
                ),
                {"wm": watermark},
            )
            assert (
                await competition_rules.traffit_daily_ran_after(db, boundary)
                is expected
            )
        await db.rollback()


async def test_autofreeze_waits_for_third_business_day_and_traffit(
    monkeypatch,
) -> None:
    frozen: list[str] = []

    async def _not_frozen(_db, _ctype, _period) -> bool:
        return False

    async def _freeze(_db, ctype, period, *, reason):
        assert reason == "autofreeze"
        frozen.append(f"{ctype.value}:{period}")
        return competitions.FrozenPodium([], already_frozen=False)

    monkeypatch.setattr(competition_autofreeze, "_is_period_frozen", _not_frozen)
    monkeypatch.setattr(competitions, "freeze_competition", _freeze)
    monkeypatch.setattr(competition_rules.settings, "TRAFFIT_SYNC_ENABLED", False)

    # 2.09.2026 = 2. dzień roboczy po sierpniu → sierpień jeszcze czeka;
    # Q2 (koniec 30.06) jest dojrzały od dawna.
    await competition_autofreeze._run_once(date(2026, 9, 2))
    assert frozen == [
        "quarterly_champions_dl:Q2 2026",
        "quarterly_champions_recruiter:Q2 2026",
    ]

    frozen.clear()
    await competition_autofreeze._run_once(date(2026, 9, 3))
    assert "monthly_placements:2026-08" in frozen
    assert "monthly_recommendations:2026-08" in frozen

    # Sync Traffita włączony, a udanego dziennego biegu po końcu okresu brak →
    # nic nie jest zamrażane, choć termin minął.
    frozen.clear()
    monkeypatch.setattr(competition_rules.settings, "TRAFFIT_SYNC_ENABLED", True)

    async def _no_run(_db, _boundary) -> bool:
        return False

    monkeypatch.setattr(competition_rules, "traffit_daily_ran_after", _no_run)
    await competition_autofreeze._run_once(date(2026, 9, 3))
    assert frozen == []


# ── 3. Okres bez zwycięzcy jest zamknięty i nie liczy się od nowa ─────────


async def test_no_winner_period_is_closed_and_never_recomputed(monkeypatch) -> None:
    year = _year()
    period = f"{year}-05"
    ctype = CompetitionType.monthly_placements
    async with AsyncSessionLocal() as db:
        podium = await competitions.freeze_competition(db, ctype, period)
        assert podium.saved_count == 0
        assert podium.closure_status == "no_winner"
        closure = await _closure(db, ctype, period)
        assert closure is not None and closure.status == "no_winner"
        assert await competition_autofreeze._is_period_frozen(db, ctype, period)

        async def _boom(*_args, **_kwargs):
            raise AssertionError("zamknięty okres nie może być liczony od nowa")

        monkeypatch.setattr(competitions, "compute_live", _boom)
        again = await competitions.freeze_competition(db, ctype, period)
        assert again.already_frozen is True
        assert again.closure_status == "no_winner"


# ── 4. Remis w wyścigu placementów: suma marży/h ──────────────────────────


async def _placement_tie(db, year: int, *, second_has_contracts: bool):
    """C prowadzi kwartał (lipiec), A i B remisują w sierpniu po 2 placementy."""
    leader = await _user(db, "Lider Q3")
    a = await _user(db, "A marża 50")
    b = await _user(db, "B marża 30")
    job = await _job(db)
    for day in (6, 7, 8):
        await _pair(db, user=leader, job=job, at=_at(year, 7, day), stages=_HIRED)
    for day in (4, 5):
        cand = await _pair(db, user=a, job=job, at=_at(year, 8, day), stages=_HIRED)
        await _contract(db, cand, job, client=150, cost=100)
    for day in (11, 12):
        cand = await _pair(db, user=b, job=job, at=_at(year, 8, day), stages=_HIRED)
        if second_has_contracts:
            await _contract(db, cand, job, client=130, cost=100)
    await db.commit()
    return leader, a, b


async def test_placement_tie_is_broken_by_margin_per_hour() -> None:
    year = _year()
    period = f"{year}-08"
    async with AsyncSessionLocal() as db:
        leader, a, b = await _placement_tie(db, year, second_has_contracts=True)
        podium = await competitions.freeze_competition(
            db, CompetitionType.monthly_placements, period
        )
        assert podium.closure_status == "frozen"
        winners = await _winners(db, CompetitionType.monthly_placements, period)
    assert [w.user_id for w in winners] == [a.id, b.id]
    assert winners[0].prize_pln == competitions.MONTHLY_RACE_PRIZE_PLN
    assert winners[1].prize_pln == 0
    top = winners[0].frozen_snapshot["top"]
    assert top[0]["margin_per_hour_sum"] == pytest.approx(100.0)
    assert top[1]["margin_per_hour_sum"] == pytest.approx(60.0)
    assert winners[0].frozen_snapshot["excluded_user_ids"] == [leader.id]


# ── 5. Remis nierozstrzygalny → tie_pending → decyzja admina ─────────────


async def test_unresolved_tie_waits_for_admin_and_resolve_endpoint(
    app_client, app_auth_headers
) -> None:
    year = _year()
    period = f"{year}-08"
    ctype = CompetitionType.monthly_placements
    async with AsyncSessionLocal() as db:
        _leader, a, b = await _placement_tie(db, year, second_has_contracts=False)
        podium = await competitions.freeze_competition(db, ctype, period)
        assert podium.closure_status == "tie_pending"
        # Miejsca z remisu zostają puste (0 zł) do decyzji.
        assert await _winners(db, ctype, period) == []
        closure = await _closure(db, ctype, period)
        assert closure.status == "tie_pending"
        tie = closure.details["ties"][0]
        assert tie["positions"] == [1, 2]
        assert sorted(tie["user_ids"]) == sorted([a.id, b.id])
        assert await competition_autofreeze._is_period_frozen(db, ctype, period)

    resp = await app_client.get("/api/competitions/ties", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    item = next(
        i
        for i in resp.json()["items"]
        if i["period"] == period and i["competition_type"] == ctype.value
    )
    assert item["ties"][0]["prizes_pln"] == {"1": 1500, "2": 0}
    names = {e["user_id"]: e["name"] for e in item["ties"][0]["entries"]}
    assert names[a.id] == "A marża 50"

    url = f"/api/competitions/{ctype.value}/{period}/resolve-tie"
    bad = await app_client.post(
        url, json={"user_ids": [a.id, a.id]}, headers=app_auth_headers
    )
    assert bad.status_code == 422

    resp = await app_client.post(
        url, json={"user_ids": [b.id, a.id]}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    again = await app_client.post(
        url, json={"user_ids": [b.id, a.id]}, headers=app_auth_headers
    )
    assert again.status_code == 409

    async with AsyncSessionLocal() as db:
        winners = await _winners(db, ctype, period)
        assert [(w.rank, w.user_id, w.prize_pln) for w in winners] == [
            (1, b.id, 1500),
            (2, a.id, 0),
        ]
        closure = await _closure(db, ctype, period)
        assert closure.status == "tie_resolved"
        assert closure.resolved_by is not None
        audit = (
            await db.execute(
                select(Activity).where(
                    Activity.entity_type == "competition_period_closure",
                    Activity.entity_id == closure.id,
                )
            )
        ).scalar_one()
        assert audit.action == "competition_tie_resolved"


def test_quarterly_tie_on_third_place_blocks_only_that_position() -> None:
    ranked = [
        competitions.RankedUser(user_id=uid, name=str(uid), metric_value=pts)
        for uid, pts in ((1, 900), (2, 700), (3, 500), (4, 500), (5, 100))
    ]
    ordered, ties = competition_rules.order_with_ties(
        ranked,
        primary=lambda r: (r.metric_value,),
        tiebreak=None,
        paid_slots=3,
        admin_on_tie=True,
        reason="points_tie",
    )
    assert [r.user_id for r in ordered][:2] == [1, 2]
    assert len(ties) == 1
    assert ties[0].positions == [3]
    assert sorted(ties[0].user_ids) == [3, 4]


# ── 6. Remis w wyścigu rekomendacji: precyzja, potem moment ──────────────


async def test_recommendation_tie_is_broken_by_precision_then_time() -> None:
    year = _year()
    period = f"{year}-08"
    async with AsyncSessionLocal() as db:
        job = await _job(db)
        # Trzy rekomendacje każda. `imprecise`: 4 weryfikacje (75%),
        # `precise`: 3 (100%). `late` ma tę samą precyzję co `precise`, ale
        # końcowy wynik osiąga później.
        imprecise = await _user(db, "Precyzja 75")
        precise = await _user(db, "Precyzja 100 wcześnie")
        late = await _user(db, "Precyzja 100 późno")
        for day in (3, 4, 5):
            await _pair(
                db,
                user=imprecise,
                job=job,
                at=_at(year, 8, day),
                stages=(PipelineStage.cv_sent,),
            )
        await _pair(db, user=imprecise, job=job, at=_at(year, 8, 6), stages=())
        for day in (3, 4, 5):
            await _pair(
                db,
                user=precise,
                job=job,
                at=_at(year, 8, day),
                stages=(PipelineStage.cv_sent,),
            )
        for day in (3, 4, 20):
            await _pair(
                db,
                user=late,
                job=job,
                at=_at(year, 8, day),
                stages=(PipelineStage.cv_sent,),
            )
        await db.commit()

        podium = await competitions.freeze_competition(
            db, CompetitionType.monthly_recommendations, period
        )
        assert podium.closure_status == "frozen"
        winners = await _winners(db, CompetitionType.monthly_recommendations, period)
    assert [w.user_id for w in winners] == [precise.id, late.id, imprecise.id]
    assert winners[0].prize_pln == competitions.MONTHLY_RACE_PRIZE_PLN
    assert winners[0].frozen_snapshot["ties"] == []


# ── 7. Liga DL liczy PARY, mianownik = rekrutacje zamknięte w kwartale ────


async def test_dl_league_counts_pairs_and_divides_by_closed_jobs() -> None:
    year = _year()
    async with AsyncSessionLocal() as db:
        dl = await _user(db, "DL pary", role=UserRole.delivery_lead)
        closed = await _job(db, dl_id=dl.id, closed_at=_at(year, 8, 30))
        # Rekrutacja utworzona dziś (poza kwartałem) i niezamknięta — nie wchodzi
        # do mianownika; zamknięta w kwartale — wchodzi.
        await _job(db, dl_id=dl.id)
        recruiter = await _user(db, "Rekruter DL")
        cands = []
        for day in (4, 5, 6):
            cands.append(
                await _pair(
                    db,
                    user=recruiter,
                    job=closed,
                    at=_at(year, 8, day),
                    stages=(PipelineStage.hired,),
                )
            )
        # Powrót na „Zatrudniony" tej samej pary — stary licznik wierszy
        # policzyłby ją dwa razy.
        db.add(
            CandidateStage(
                candidate_id=cands[0].id,
                job_id=closed.id,
                stage=PipelineStage.hired,
                moved_at=_at(year, 8, 20),
                moved_by=recruiter.id,
            )
        )
        await db.commit()

        start, end = competitions.quarter_bounds(year, 3)
        ranked = await competitions._rank_dls_by_placements(db, start=start, end=end)
    mine = next(r for r in ranked if r.user_id == dl.id)
    assert mine.metric_value == 3
    assert mine.extras["requests"] == 1
    assert mine.hit_ratio == 300.0


# ── 8. Lustro DDL w entrypoint.sh ──────────────────────────────────────────


def test_entrypoint_mirrors_0344() -> None:
    import importlib.util

    path = _BACKEND / "alembic" / "versions" / "0344_competition_period_closures.py"
    spec = importlib.util.spec_from_file_location("_m0344", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    squash = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    entrypoint = squash((_BACKEND / "entrypoint.sh").read_text(encoding="utf-8"))
    assert squash(migration.CREATE_SQL) in entrypoint
