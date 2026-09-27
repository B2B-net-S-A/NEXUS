"""Runda 11 audytu — obszar PIPE (backend rekrutacji).

Testy z bazą (``app_client`` / ``AsyncSessionLocal``) zakładają własne dane
i filtrują po nich — baza CI jest wspólna.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (register every mapper)
import pytest
from httpx import AsyncClient


# ── PIPE-1: /bulk-move dla pary bez wiersza = dodanie osoby (jak /move) ──────


@pytest.mark.asyncio
async def test_bulk_move_adding_a_fresh_pair_stamps_entry_source_and_claims(
    app_client: AsyncClient,
) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_process import RecruitmentProcess
    from app.services.candidate_claim import ENTRY_ADDED_MANUAL
    from tests.test_pipeline_membership_gate import (
        BULK_MOVE,
        MOVE,
        _seed_candidate,
        _seed_job,
        _seed_recruiter,
    )

    headers_a, uid_a = await _seed_recruiter(app_client)
    headers_b, _ = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=None)
    cand = await _seed_candidate()

    added = await app_client.post(
        BULK_MOVE,
        headers=headers_a,
        json={"candidate_ids": [cand], "job_id": job_id, "stage": "new"},
    )
    assert added.status_code == 200, added.text

    async with AsyncSessionLocal() as db:
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == cand,
                RecruitmentProcess.job_id == job_id,
            )
        )
        assert process is not None
        assert process.entry_source == ENTRY_ADDED_MANUAL
        assert process.claimed_by_user_id == uid_a

    taken = await app_client.post(
        MOVE,
        headers=headers_b,
        json={"candidate_id": cand, "job_id": job_id, "stage": "screening"},
    )
    assert taken.status_code == 423, taken.text
    assert taken.json()["detail"]["code"] == "CANDIDATE_CLAIMED"


def test_bulk_move_passes_fresh_pair_kwargs_to_transition() -> None:
    """Strażnik kształtu: pętla /bulk-move woła ``_fresh_pair_entry_kwargs``."""
    import inspect

    from app.api import pipeline

    source = inspect.getsource(pipeline.bulk_move_candidates)
    assert "_fresh_pair_entry_kwargs(current_user, request)" in source
    assert "request" in inspect.signature(pipeline.bulk_move_candidates).parameters


# ── PIPE-2: status requestu — champion nie przykrywa „Klient milczy” ─────────


@pytest.mark.asyncio
async def test_request_status_champion_does_not_cover_silent_or_finished() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.services import job_similarity as sim

    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    cases = {
        "searching": "champion",
        "client_silent": "searching",
        "finished": "searching",
        # Słownik statusu nie zna „Do przejrzenia” — champion zostaje.
        "to_review": "champion",
    }
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R11PipeStatus-{tag}")
        db.add(client)
        await db.flush()
        jobs = {
            state: Job(
                title=f"R11-status-{state}-{tag}",
                status=JobStatus.published,
                client_id=client.id,
                work_state=state,
                champion_found_at=now,
            )
            for state in cases
        }
        db.add_all(jobs.values())
        await db.commit()
        rows = await sim.request_statuses_and_stages(
            db, [job.id for job in jobs.values()]
        )
    for state, expected in cases.items():
        status_, stage = rows[jobs[state].id]
        assert status_ == expected, state
        # Oba wyrażenia mówią „champion” przy „Klient milczy” / „Zakończony”
        # jednakowo — czyli wcale.
        if state in ("client_silent", "finished"):
            assert stage == state


def test_request_status_expr_reads_work_state_for_champion() -> None:
    from app.services import job_similarity as sim

    sq = sim.request_status_subquery([1])
    compiled = str(sim.request_status_expr(sq).compile())
    assert "work_state" in compiled


# ── PIPE-3: CV firmowe pary widoczne z nowego wiersza etapu ──────────────────


def test_with_pair_source_points_to_other_stage_only() -> None:
    from app.api.candidate_stage_cv import with_pair_source
    from app.schemas.candidate_stage_cv import (
        CVBrandedResponse,
        RecruitmentBrandedCvSummary,
    )

    empty = CVBrandedResponse(candidate_stage_id=20, status="none")
    other = RecruitmentBrandedCvSummary(status="finalized", stage_id=10)
    pointed = with_pair_source(empty, other)
    assert pointed.pair_source_stage_id == 10
    assert pointed.pair_source_status == "finalized"
    assert pointed.status == "none"
    assert pointed.content_html is None

    # Ten sam etap, brak CV pary, etap z własnym CV — bez wskazania.
    same = RecruitmentBrandedCvSummary(status="draft", stage_id=20)
    assert with_pair_source(empty, same).pair_source_stage_id is None
    nothing = RecruitmentBrandedCvSummary()
    assert with_pair_source(empty, nothing).pair_source_stage_id is None
    own = CVBrandedResponse(candidate_stage_id=20, status="draft")
    assert with_pair_source(own, other).pair_source_stage_id is None


@pytest.mark.asyncio
async def test_new_stage_row_points_to_the_pairs_company_cv(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services.candidate_stage_cv_service import create_original_cv_snapshot
    from tests.test_candidate_stage_cv_branded import _seed_full_stage

    first_id, cand_id, job_id = await _seed_full_stage()
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CandidateStageCV)
            .where(CandidateStageCV.candidate_stage_id == first_id)
            .values(branded_status="draft", branded_draft_html="<p>CV</p>")
        )
        later = CandidateStage(
            candidate_id=cand_id,
            job_id=job_id,
            stage=PipelineStage.verified,
            moved_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        db.add(later)
        await db.flush()
        await create_original_cv_snapshot(db, later)
        await db.commit()
        later_id = later.id

    response = await app_client.get(
        f"/api/candidates/stages/{later_id}/cv/branded", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "none"
    assert body["candidate_stage_id"] == later_id
    assert body["pair_source_stage_id"] == first_id
    assert body["pair_source_status"] == "draft"

    # Etap z własnym CV nie wskazuje nigdzie indziej.
    own = await app_client.get(
        f"/api/candidates/stages/{first_id}/cv/branded", headers=app_auth_headers
    )
    assert own.status_code == 200, own.text
    assert own.json()["pair_source_stage_id"] is None
