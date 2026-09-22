"""Wykluczone placementy (0343) — reguła, widok, CTE atrybucji, lista admina
oraz kredyt w kreatorze metryk pulpitu.

Kontrakty:

- seria = jedno konto, ≥ 10 par „Zatrudniony" w jednym dniu warszawskim;
  wykluczane są pary z tej serii BEZ „CV wysłane"; 9 par to nie seria;
- historyczna seria (24–25.09.2025) wykluczana CAŁA, także pary z CV;
- wykluczony `hired` znika z widoku ``analytics_first_milestones`` i z
  ``VERIFIER_ANCHORED_CTE`` (obie gałęzie), inne etapy pary zostają;
- lista wykluczeń: admin 200, rekruter 403;
- kreator metryk „Zatrudnieni, moje" kredytuje weryfikatora, jak „Moje KPI".

Baza jest wspólna i nieczyszczona: każdy test zakłada własnych ludzi,
klientów i kandydatów, a wykrywanie zawęża ZAPIS do swoich kandydatów
(``only_candidate_ids``) — globalny przebieg wykluczyłby cudze dane testowe.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


async def _user(db, role: str = "recruiter"):
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"excl-{marker}@example.com",
        name=f"Wykluczenia {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _pairs(db, mover_id: int, *, count: int, when: datetime, with_cv: int = 0):
    """``count`` par (kandydat × rekrutacja) z `hired` tego samego dnia.

    Pierwsze ``with_cv`` par ma wcześniej etap `cv_sent`.
    """
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    marker = uuid.uuid4().hex[:8]
    client = Client(name=f"excl-client-{marker}")
    db.add(client)
    await db.flush()
    job = Job(
        title=f"Wykluczenia {marker}", client_id=client.id, status=JobStatus.published
    )
    db.add(job)
    await db.flush()
    candidate_ids: list[int] = []
    for i in range(count):
        cand = Candidate(name="Ela", lastname=f"Ex{marker}{i}")
        db.add(cand)
        await db.flush()
        candidate_ids.append(cand.id)
        if i < with_cv:
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_by=mover_id,
                    moved_at=when - timedelta(days=5),
                )
            )
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_by=mover_id,
                moved_at=when + timedelta(minutes=i),
            )
        )
    await db.flush()
    return job.id, candidate_ids


async def _excluded(db, candidate_ids: list[int]) -> dict[int, str]:
    from app.models.placement_exclusion import PlacementExclusion

    rows = (
        await db.execute(
            select(PlacementExclusion.candidate_id, PlacementExclusion.reason).where(
                PlacementExclusion.candidate_id.in_(candidate_ids)
            )
        )
    ).all()
    return {cid: reason for cid, reason in rows}


# ── Reguła ───────────────────────────────────────────────────────────────────


@needs_db
@pytest.mark.asyncio
async def test_series_of_ten_without_cv_is_excluded_but_pairs_with_cv_stay():
    from app.core.database import AsyncSessionLocal
    from app.services.placement_exclusions import REASON_NO_CV, detect_new_series

    # 10:00 UTC = 12:00 w Warszawie — jeden dzień warszawski dla całej serii.
    when = datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        mover = await _user(db, "admin")
        _, ids = await _pairs(db, mover.id, count=10, when=when, with_cv=2)
        inserted = await detect_new_series(db, only_candidate_ids=ids)
        again = await detect_new_series(db, only_candidate_ids=ids)
        excluded = await _excluded(db, ids)
        await db.commit()

    assert inserted == 8
    assert again == 0, "reguła jest idempotentna"
    assert set(excluded) == set(ids[2:])
    assert set(excluded.values()) == {REASON_NO_CV}


@needs_db
@pytest.mark.asyncio
async def test_nine_hires_in_a_day_are_not_a_series():
    from app.core.database import AsyncSessionLocal
    from app.services.placement_exclusions import detect_new_series

    when = datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        mover = await _user(db, "admin")
        _, ids = await _pairs(db, mover.id, count=9, when=when)
        inserted = await detect_new_series(db, only_candidate_ids=ids)
        excluded = await _excluded(db, ids)
        await db.rollback()

    assert inserted == 0
    assert excluded == {}


@needs_db
@pytest.mark.asyncio
async def test_series_counts_the_warsaw_day_not_the_utc_day():
    """10 par tego samego dnia UTC, ale 5 przed i 5 po północy w Warszawie.

    Dwa dni warszawskie po 5 par = żadnej serii (licząc po UTC byłaby jedna).
    """
    from app.core.database import AsyncSessionLocal
    from app.services.placement_exclusions import detect_new_series

    # Czerwiec = CEST (UTC+2): 21:25 UTC = 23:25, 22:05 UTC = 00:05 kolejnego dnia.
    evening = datetime(2026, 6, 10, 21, 25, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 6, 10, 22, 5, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        mover = await _user(db, "admin")
        _, a = await _pairs(db, mover.id, count=5, when=evening)
        _, b = await _pairs(db, mover.id, count=5, when=after_midnight)
        inserted = await detect_new_series(db, only_candidate_ids=a + b)
        await db.rollback()

    assert inserted == 0


@needs_db
@pytest.mark.asyncio
async def test_historical_series_is_excluded_entirely_even_with_cv():
    from app.core.database import AsyncSessionLocal
    from app.services.placement_exclusions import (
        HISTORICAL_SERIES_SQL,
        REASON_2025_09_SERIES,
        historical_params,
    )

    when = datetime(2025, 9, 24, 8, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        mover = await _user(db, "admin")
        _, ids = await _pairs(db, mover.id, count=10, when=when, with_cv=3)
        rows = (
            await db.execute(text(HISTORICAL_SERIES_SQL), historical_params(ids))
        ).all()
        excluded = await _excluded(db, ids)
        await db.rollback()

    assert len(rows) == 10
    assert set(excluded) == set(ids)
    assert set(excluded.values()) == {REASON_2025_09_SERIES}


# ── Widok i CTE atrybucji ────────────────────────────────────────────────────


async def _pair_with_milestones(db, *, classified: bool):
    """verified(A) → cv_sent(A) → hired(B); opcjonalnie proces sklasyfikowany."""
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.recruitment_priority import PriorityOriginKind
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess

    t0 = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
    a = await _user(db)
    b = await _user(db)
    marker = uuid.uuid4().hex[:8]
    client = Client(name=f"excl-view-{marker}")
    db.add(client)
    await db.flush()
    job = Job(title=f"Widok {marker}", client_id=client.id)
    cand = Candidate(name="Ola", lastname=f"Vw{marker}")
    db.add_all([job, cand])
    await db.flush()
    for i, (stage, who) in enumerate(
        (
            (PipelineStage.verified, a.id),
            (PipelineStage.cv_sent, a.id),
            (PipelineStage.hired, b.id),
        )
    ):
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=stage,
                moved_by=who,
                moved_at=t0 + timedelta(days=i + 1),
            )
        )
    if classified:
        db.add(
            RecruitmentProcess(
                candidate_id=cand.id,
                job_id=job.id,
                client_id=client.id,
                attempt_no=1,
                status=ProcessStatus.open,
                origin_kind=PriorityOriginKind.assigned,
                opened_at=t0,
                kpi_eligible=True,
                credit_user_id=a.id,
            )
        )
    await db.flush()
    return cand.id, job.id, a.id


async def _stages(db, sql: str, cid: int, jid: int) -> set[str]:
    rows = (await db.execute(text(sql), {"cid": cid, "jid": jid})).all()
    return {str(r[0]) for r in rows}


@needs_db
@pytest.mark.asyncio
@pytest.mark.parametrize("classified", [False, True])
async def test_excluded_hired_disappears_from_view_and_cte(classified: bool):
    from app.core.database import AsyncSessionLocal
    from app.models.placement_exclusion import PlacementExclusion
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    view_sql = (
        "SELECT stage::text FROM analytics_first_milestones "
        "WHERE candidate_id = :cid AND job_id = :jid"
    )
    cte_sql = (
        VERIFIER_ANCHORED_CTE
        + " SELECT stage FROM credited WHERE candidate_id = :cid AND job_id = :jid"
    )
    async with AsyncSessionLocal() as db:
        cid, jid, _ = await _pair_with_milestones(db, classified=classified)
        before_view = await _stages(db, view_sql, cid, jid)
        before_cte = await _stages(db, cte_sql, cid, jid)
        db.add(
            PlacementExclusion(
                candidate_id=cid, job_id=jid, reason="admin_bulk_no_cv", details={}
            )
        )
        await db.flush()
        after_view = await _stages(db, view_sql, cid, jid)
        after_cte = await _stages(db, cte_sql, cid, jid)
        await db.rollback()

    assert before_view == {"verified", "cv_sent", "hired"}
    assert before_cte == {"verified", "cv_sent", "hired"}
    assert after_view == {"verified", "cv_sent"}
    assert after_cte == {"verified", "cv_sent"}


# ── Lista admina ─────────────────────────────────────────────────────────────


async def _token(user) -> dict[str, str]:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user.id, user.role.value)}"}


@needs_db
@pytest.mark.asyncio
async def test_admin_sees_the_list_recruiter_is_denied(app_client):
    from app.core.database import AsyncSessionLocal
    from app.services.placement_exclusions import detect_new_series

    when = datetime(2026, 4, 14, 9, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        recruiter = await _user(db, "recruiter")
        job_id, ids = await _pairs(db, admin.id, count=10, when=when)
        await detect_new_series(db, only_candidate_ids=ids)
        await db.commit()
        admin_headers = await _token(admin)
        recruiter_headers = await _token(recruiter)

    denied = await app_client.get(
        "/api/admin/placement-exclusions", headers=recruiter_headers
    )
    assert denied.status_code == 403

    resp = await app_client.get(
        "/api/admin/placement-exclusions", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["series_threshold"] == 10
    mine = [item for item in body["items"] if item["candidate_id"] in ids]
    assert len(mine) == 10
    row = mine[0]
    assert row["job_id"] == job_id
    assert row["moved_by_user_id"] == admin.id
    assert row["moved_by_name"] == admin.name
    assert row["reason"] == "admin_bulk_no_cv"
    assert row["had_cv_sent"] is False
    assert row["series_size"] == 10
    assert row["client_name"].startswith("excl-client-")


# ── Kreator metryk: kredyt jak w „Moje KPI" ──────────────────────────────────


@needs_db
@pytest.mark.asyncio
async def test_custom_metric_hired_for_me_credits_the_verifier(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    when = datetime.now(timezone.utc) - timedelta(days=3)
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        verifier = await _user(db)
        mover = await _user(db)
        client = Client(name=f"excl-metric-{marker}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Metryka {marker}", client_id=client.id, status=JobStatus.published
        )
        cand = Candidate(name="Iga", lastname=f"Mt{marker}")
        db.add_all([job, cand])
        await db.flush()
        db.add_all(
            [
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_by=verifier.id,
                    moved_at=when,
                ),
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_by=mover.id,
                    moved_at=when + timedelta(hours=2),
                ),
            ]
        )
        await db.commit()
        verifier_headers = await _token(verifier)
        mover_headers = await _token(mover)
        client_id = client.id

    body = {
        "source": "pipeline_moves",
        "measure": "first_reach",
        "stage": "hired",
        "filters": {"author": "me", "client_ids": [client_id]},
        "group_by": "none",
        "period": "last_30_days",
    }
    as_verifier = await app_client.post(
        "/api/dashboard-metrics/evaluate", headers=verifier_headers, json=body
    )
    as_mover = await app_client.post(
        "/api/dashboard-metrics/evaluate", headers=mover_headers, json=body
    )
    assert as_verifier.status_code == 200, as_verifier.text
    assert as_mover.status_code == 200, as_mover.text
    assert as_verifier.json()["value"] == 1.0
    assert as_mover.json()["value"] == 0.0
