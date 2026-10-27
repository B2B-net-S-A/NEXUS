"""Minutowa migawka `credited` całej firmy (27.10.2026, lag NEXUSA).

Panel „Moje KPI”, cele, panel zespołu, Liga i wyścigi, „Aktywność
rekrutacyjna”, kafel „Wyniki zespołu”, „Mój dzień”, kreator metryk, trend
i raport rekrutacji czytają `credited` z jednej migawki na minutę zamiast
liczyć `VERIFIER_ANCHORED_CTE` każdy osobno.

Reguły pod ochroną:

1. **Liczby co do jednej jak przed zmianą.** Każde zapytanie konsumenta
   z `CREDITED_FROM_SNAPSHOT_CTE` wykonujemy drugi raz z pełnym
   `VERIFIER_ANCHORED_CTE` w tym miejscu i porównujemy wiersze — także przy
   zawężeniu migawki do osoby, etapu i okna (`credited_bind`).
2. **Jedno przeliczenie na minutę**, z jednym wykonawcą przy równoległych
   żądaniach; zamrożenie konkursu liczy migawkę od nowa.
3. **`process_windows` nie niesie `rp.*`** — sortowanie okna z całymi
   wierszami procesów zrzuciło na produkcji ok. 100 GB na dysk.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core import cache as cache_module
from app.services import credited_snapshot
from app.services.credited_snapshot import CREDITED_FROM_SNAPSHOT_CTE
from app.services.kpi_engine import WARSAW
from app.services.kpi_panel import VERIFIER_ANCHORED_CTE


@pytest.fixture(autouse=True)
def _clean_cache():
    cache_module._cache.clear()
    yield
    cache_module._cache.clear()


# ── 2. Jedno przeliczenie, jeden wykonawca ───────────────────────────────────


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _CountingDb:
    def __init__(self):
        self.runs = 0

    async def execute(self, stmt, params=None):
        self.runs += 1
        await asyncio.sleep(0.01)
        reached = datetime(2027, 7, 2, 10, 0, tzinfo=timezone.utc)
        return _Result(
            [("verified", reached, 1, 2, 3), ("hired", reached, None, None, 4)]
        )


async def test_parallel_readers_share_one_computation(monkeypatch):
    monkeypatch.setattr(credited_snapshot, "_SNAPSHOT_TTL_SECONDS", 60)
    db = _CountingDb()

    first, second, third = await asyncio.gather(
        credited_snapshot.credited_rows(db),
        credited_snapshot.credited_rows(db),
        credited_snapshot.credited_rows(db),
    )
    assert db.runs == 1
    assert first == second == third
    assert first[1] == ("hired", first[1][1], None, None, 4)

    await credited_snapshot.credited_rows(db)
    assert db.runs == 1

    await credited_snapshot.invalidate_credited_snapshot()
    await credited_snapshot.credited_rows(db)
    assert db.runs == 2


async def test_bind_narrows_like_the_consumer_sql():
    rows = (
        ("verified", datetime(2027, 7, 1, tzinfo=WARSAW), 1, 1, 7),
        ("verified", datetime(2027, 8, 1, tzinfo=WARSAW), 1, 2, 7),
        ("cv_sent", datetime(2027, 7, 5, tzinfo=WARSAW), 1, 1, 8),
    )

    class _Db:
        async def execute(self, stmt, params=None):
            return _Result(rows)

    bound = await credited_snapshot.credited_bind(
        _Db(),
        stage="verified",
        since=datetime(2027, 7, 1, tzinfo=WARSAW),
        until=datetime(2027, 8, 1, tzinfo=WARSAW),
    )
    # Półotwarte okno: początek wchodzi, koniec nie.
    assert bound["credited_job_id"] == [1]
    assert (await credited_snapshot.credited_bind(_Db(), credit_user=8))[
        "credited_stage"
    ] == ["cv_sent"]
    # Naiwna data: zawężenie zostaje w SQL-u konsumenta.
    naive = await credited_snapshot.credited_bind(_Db(), since=datetime(2027, 7, 2))
    assert len(naive["credited_stage"]) == 3


async def test_freeze_recomputes_the_snapshot():
    import inspect

    from app.services import competitions

    source = inspect.getsource(competitions.freeze_competition)
    assert source.index("invalidate_credited_snapshot()") < source.index(
        "compute_live("
    )


# ── 3. Wąskie `process_windows` ──────────────────────────────────────────────


def test_process_windows_does_not_carry_whole_process_rows():
    process_windows = VERIFIER_ANCHORED_CTE.split("first_classified AS")[0]
    assert "rp.*" not in process_windows
    for column in (
        "rp.id",
        "rp.candidate_id",
        "rp.job_id",
        "rp.attempt_no",
        "rp.opened_at",
        "rp.status",
        "rp.origin_kind",
        "rp.credit_user_id",
        "rp.kpi_eligible",
        # `priority_work_policy` czyta je z `classified_process`.
        "rp.eligibility_assignment_id",
    ):
        assert column in process_windows, column


# ── 1. Zgodność liczb na bazie ───────────────────────────────────────────────


class _ParityDb:
    """Sesja, która każde zapytanie z migawką sprawdza pełnym CTE."""

    def __init__(self, db):
        self._db = db
        self.checked: list[str] = []

    def __getattr__(self, name):
        return getattr(self._db, name)

    async def execute(self, stmt, params=None, *args, **kwargs):
        result = await self._db.execute(stmt, params, *args, **kwargs)
        sql = getattr(stmt, "text", "")
        if CREDITED_FROM_SNAPSHOT_CTE not in sql:
            return result
        frozen = result.freeze()
        reference_stmt = text(
            sql.replace(CREDITED_FROM_SNAPSHOT_CTE, VERIFIER_ANCHORED_CTE, 1)
        ).bindparams(
            *[
                bind
                for key, bind in stmt._bindparams.items()
                if not key.startswith("credited_")
            ]
        )
        reference_params = {
            key: value
            for key, value in (params or {}).items()
            if not key.startswith("credited_")
        }
        reference = (await self._db.execute(reference_stmt, reference_params)).all()
        got = frozen().all()
        assert Counter(map(tuple, got)) == Counter(map(tuple, reference)), sql[-400:]
        self.checked.append(sql)
        return frozen()

    async def scalar(self, stmt, params=None, *args, **kwargs):
        return (await self.execute(stmt, params, *args, **kwargs)).scalar()


async def _seed(db):
    """Trzy osoby, pary w lipcu 2027 (po 12.10.2026 — liczy Tablica), w tym
    etapy dokładnie na granicach miesiąca i kamień bez autora."""
    from app.core.security import hash_password
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job
    from app.models.recruitment_pipeline import (
        CandidateStage,
        PipelineStage,
        VerificationStatus,
    )
    from app.models.skill import Skill as _Skill  # noqa: F401
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]

    def _user(name, role):
        return User(
            email=f"credited-{name}-{tag}@example.com",
            password_hash=hash_password("x"),
            name=f"{name} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
        )

    first = _user("rekruterka", UserRole.recruiter)
    second = _user("rekruter", UserRole.recruiter)
    lead = _user("dl", UserRole.delivery_lead)
    head = _user("hor", UserRole.head_of_recruitment)
    client = Client(name=f"Klient migawki {tag}")
    db.add_all([first, second, lead, head, client])
    await db.flush()
    jobs = [Job(title=f"Rekrutacja {tag} {i}", client_id=client.id) for i in range(2)]
    people = [Candidate(name="Kandydat", lastname=f"M-{tag}-{i}") for i in range(4)]
    db.add_all(jobs + people)
    await db.flush()

    month_start = datetime(2027, 7, 1, tzinfo=WARSAW)
    month_end = datetime(2027, 8, 1, tzinfo=WARSAW)
    plan = [
        # (kandydat, rekrutacja, etap, kiedy, kto)
        (0, 0, PipelineStage.verified, month_start, first.id),
        (0, 0, PipelineStage.cv_sent, month_start + timedelta(days=3), lead.id),
        (0, 0, PipelineStage.hired, month_start + timedelta(days=12), lead.id),
        (1, 0, PipelineStage.verified, month_start + timedelta(days=8), second.id),
        (1, 0, PipelineStage.cv_sent, month_start + timedelta(days=9), second.id),
        (2, 1, PipelineStage.verified, month_start + timedelta(days=15), first.id),
        (2, 1, PipelineStage.acceptance, month_end, first.id),
        (3, 1, PipelineStage.cv_sent, month_start + timedelta(days=17), None),
    ]
    for cand, job, stage, when, who in plan:
        db.add(
            CandidateStage(
                candidate_id=people[cand].id,
                job_id=jobs[job].id,
                stage=stage,
                moved_at=when,
                moved_by=who,
                verification_status=VerificationStatus.active,
            )
        )
    await db.commit()
    return {"first": first, "second": second, "lead": lead, "head": head}


async def test_every_consumer_counts_the_same_as_the_full_cte():
    from app.api import reports as reports_api
    from app.services import (
        competition_rules,
        competitions,
        kpi_engine,
        kpi_panel,
        kpi_team,
        recruitment_activity,
        recruitment_trend,
    )
    from app.core.database import AsyncSessionLocal
    from app.services.custom_metrics import engine as metric_engine
    from app.services.kpi_catalog import KpiMetric, KpiPeriod

    async with AsyncSessionLocal() as session:
        people = await _seed(session)
        db = _ParityDb(session)
        now = datetime(2027, 7, 20, 12, 0, tzinfo=WARSAW)
        for user in (people["first"], people["second"], people["lead"]):
            panel = await kpi_panel.compute_my_panel(db, user=user, now=now)
            await kpi_panel.month_own_handoffs(db, user=user, now=now)
            await kpi_engine.evaluate_user_kpis(db, user=user, now=now)
            await kpi_engine.count_canonical_metric(
                db,
                user_id=user.id,
                metric=KpiMetric.first_verifications,
                since=datetime(2027, 7, 1, tzinfo=WARSAW),
                until=datetime(2027, 8, 1, tzinfo=WARSAW),
            )
        assert panel.rekomendacje.month == 0  # DL: CV wysłał, zasługa weryfikatorki
        first_panel = await kpi_panel.compute_my_panel(
            db, user=people["first"], now=now
        )
        assert first_panel.weryfikacje.month == 2
        assert first_panel.rekomendacje.month == 1
        assert first_panel.placementy_month == 1

        for period in (KpiPeriod.day, KpiPeriod.week, KpiPeriod.month):
            await kpi_team.compute_team_panel(db, period=period, now=now)
        team = await kpi_team.compute_team_panel(
            db,
            bounds=(
                datetime(2027, 7, 1, tzinfo=WARSAW),
                datetime(2027, 8, 1, tzinfo=WARSAW),
            ),
            now=now,
        )
        assert team.totals.unattributed >= 1

        await competitions.quarterly_champions_recruiter(db, "Q3 2027")
        await competitions.monthly_most_recommendations(db, "2027-07")
        await competitions.monthly_most_placements(db, "2027-07")
        await competition_rules.last_recommendation_at_by_user(
            db,
            user_ids=[people["first"].id, people["second"].id],
            start=datetime(2027, 7, 1, tzinfo=timezone.utc),
            end=datetime(2027, 8, 1, tzinfo=timezone.utc),
        )

        head = people["head"]
        for metric in ("verification", "recommendation", "acceptance", "placement"):
            for subject, team_scope in (
                (None, True),
                (people["first"].id, False),
            ):
                await recruitment_activity.list_recruitment_activity_details(
                    db,
                    head,
                    metric=metric,
                    window="range",
                    selected_day=date(2027, 7, 1),
                    selected_month=date(2027, 7, 1),
                    subject_user_id=subject,
                    team_scope=team_scope,
                    page=1,
                    page_size=25,
                    date_from=date(2027, 7, 1),
                    date_to=date(2027, 7, 31),
                )
        await recruitment_activity.list_recruitment_activity_details(
            db,
            head,
            metric="recommendation",
            window="month",
            selected_day=date(2027, 7, 20),
            selected_month=date(2027, 7, 1),
            subject_user_id=None,
            team_scope=False,
            unattributed=True,
            page=1,
            page_size=25,
        )
        await recruitment_activity.build_recruitment_activity_summary(
            db,
            head,
            selected_day=date(2027, 7, 13),
            selected_month=date(2027, 7, 1),
            team_scope=True,
            today=date(2027, 7, 20),
        )
        totals = await recruitment_activity.team_period_totals(
            db,
            head,
            metrics=("verification", "recommendation", "acceptance", "placement"),
            date_from=date(2027, 7, 1),
            date_to=date(2027, 7, 31),
        )
        for metric, value in totals.totals.items():
            listed = await recruitment_activity.list_recruitment_activity_details(
                db,
                head,
                metric=metric,
                window="range",
                selected_day=date(2027, 7, 1),
                selected_month=date(2027, 7, 1),
                subject_user_id=None,
                team_scope=True,
                page=1,
                page_size=1,
                date_from=date(2027, 7, 1),
                date_to=date(2027, 7, 31),
            )
            assert value == listed.period_total, metric

        await recruitment_trend.monthly_milestone_trend(db, months=3, now=now)
        await metric_engine._credited_snapshot(db, date(2027, 6, 1))
        await reports_api.report_recruitment(current_user=head, db=db, period="year")

        # Każdy przepięty konsument przeszedł przez porównanie z pełnym CTE.
        assert len(db.checked) >= 40, len(db.checked)
        await session.rollback()


async def test_team_totals_need_team_rights():
    from fastapi import HTTPException

    from app.core.database import AsyncSessionLocal
    from app.services import recruitment_activity

    async with AsyncSessionLocal() as session:
        people = await _seed(session)
        with pytest.raises(HTTPException) as denied:
            await recruitment_activity.team_period_totals(
                session,
                people["first"],
                metrics=("verification",),
                date_from=date(2027, 7, 1),
                date_to=date(2027, 7, 31),
            )
        assert denied.value.status_code == 403
