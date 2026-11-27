"""0797: weryfikacja liczy się od wejścia pary na QC CV albo dalej (Postgres).

Decyzja Artura 27.11.2026. ``board_reach`` z kodem ruchu jest lustrem
``board_column_for`` na wspólnych przypadkach Tablicy, a widok
``analytics_first_milestones`` i ``credited`` (cele, Liga, Zespół) liczą
weryfikację w dniu wejścia na QC CV — z zasługą dla osoby, która
zweryfikowała. Baza testowa nie jest czyszczona, więc asercje patrzą tylko na
konta i pary utworzone przez test.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.board_stage_badges import board_column_for
from app.services.kpi_catalog import KpiMetric
from app.services.kpi_engine import count_canonical_metric
from app.services.verification_milestone import reaches_cv_qc_sql

CASES = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "frontend/src/lib/__fixtures__/board-stage-cases.json"
    ).read_text()
)["cases"]
QC_OR_LATER = {"cv_qc", "cv_sent", "client_interview", "contract", "hired"}
# Po 12.10.2026 — `credited` liczy z Tablicy, nie z DynaReportera.
VERIFIED_AT = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
QC_AT = VERIFIED_AT + timedelta(days=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
async def test_sql_mirrors_board_column(case) -> None:
    expected = (
        board_column_for(case["name"], case["stage"], category=case.get("category"))
        in QC_OR_LATER
    )
    sql = (
        "SELECT " + reaches_cv_qc_sql("mv", "sd") + " FROM ("
        "SELECT CAST(:s AS text) AS stage) mv, ("
        "SELECT stage_def_board_reach(:n, :c = 'terminal', FALSE)"
        " AS board_reach) sd"
    )
    async with AsyncSessionLocal() as db:
        got = await db.scalar(
            text(sql),
            {"n": case["name"], "s": case["stage"], "c": case.get("category")},
        )
    assert got is expected


@pytest_asyncio.fixture
async def seeded():
    """Rekruter R weryfikuje trzy pary, karty dalej przesuwa D:
    A — wchodzi na „QC CV” po dwóch dniach, B — u Nordei na „Wysłać do Cpro”
    (kod `new`), C — zostaje w „Zweryfikowanym”."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"qcver-r-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Weryf R",
            role=UserRole.recruiter,
            is_active=True,
        )
        lead = User(
            email=f"qcver-d-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Weryf D",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        client = Client(name=f"QC weryfikacja {unique}")
        template = PipelineTemplate(name=f"QC weryfikacja {unique}")
        db.add_all([recruiter, lead, client, template])
        await db.flush()
        qc = PipelineStageDef(
            template_id=template.id,
            name="QC CV",
            order=1,
            category=StageCategoryEnum.internal,
            legacy_enum_value="interview",
        )
        cpro = PipelineStageDef(
            template_id=template.id,
            name="Wysłać do Cpro",
            order=2,
            category=StageCategoryEnum.internal,
            legacy_enum_value="new",
        )
        job = Job(title=f"QC weryfikacja {unique}", client_id=client.id)
        db.add_all([qc, cpro, job])
        await db.flush()

        pairs = {}
        for key in ("qc", "cpro", "stuck"):
            candidate = Candidate(name="Kai", lastname=f"{key}-{unique}")
            db.add(candidate)
            await db.flush()
            pairs[key] = candidate.id
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=VERIFIED_AT,
                    moved_by=recruiter.id,
                )
            )
        db.add_all(
            [
                CandidateStage(
                    candidate_id=pairs["qc"],
                    job_id=job.id,
                    stage=PipelineStage.interview,
                    stage_def_id=qc.id,
                    moved_at=QC_AT,
                    moved_by=lead.id,
                ),
                CandidateStage(
                    candidate_id=pairs["cpro"],
                    job_id=job.id,
                    stage=PipelineStage.new,
                    stage_def_id=cpro.id,
                    moved_at=QC_AT,
                    moved_by=lead.id,
                ),
            ]
        )
        await db.commit()
        return {"recruiter": recruiter.id, "lead": lead.id, "job": job.id, **pairs}


@pytest.mark.asyncio
async def test_view_counts_verification_on_entering_qc(seeded) -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT candidate_id, first_reached_at, first_moved_by
                    FROM analytics_first_milestones
                    WHERE job_id = :job AND stage::text = 'verified'
                    """
                ),
                {"job": seeded["job"]},
            )
        ).all()
    by_pair = {r.candidate_id: r for r in rows}
    assert set(by_pair) == {seeded["qc"], seeded["cpro"]}
    for key in ("qc", "cpro"):
        assert by_pair[seeded[key]].first_reached_at == QC_AT
        assert by_pair[seeded[key]].first_moved_by == seeded["recruiter"]


@pytest.mark.asyncio
async def test_goal_counter_credits_the_verifier_on_qc_day(seeded) -> None:
    async with AsyncSessionLocal() as db:
        on_verify_day = await count_canonical_metric(
            db,
            user_id=seeded["recruiter"],
            metric=KpiMetric.first_verifications,
            since=VERIFIED_AT - timedelta(hours=1),
            until=VERIFIED_AT + timedelta(hours=1),
        )
        on_qc_day = await count_canonical_metric(
            db,
            user_id=seeded["recruiter"],
            metric=KpiMetric.first_verifications,
            since=QC_AT - timedelta(hours=1),
            until=QC_AT + timedelta(hours=1),
        )
        lead = await count_canonical_metric(
            db,
            user_id=seeded["lead"],
            metric=KpiMetric.first_verifications,
            since=QC_AT - timedelta(hours=1),
            until=QC_AT + timedelta(hours=1),
        )
    assert on_verify_day == 0
    assert on_qc_day == 2
    assert lead == 0
