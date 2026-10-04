"""Runda 10 audytu — obszar PIPE (backend rekrutacji).

Każdy test odtwarza jedno znalezisko z raportów V2/X2 rundy 10. Testy z bazą
(``app_client``) zakładają własne dane i filtrują po nich — baza CI jest
wspólna.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import app.models  # noqa: F401  (register every mapper)
import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from app.models.job import Job
from app.models.user import User, UserRole


# ── R10-V2-3: job_scope_clause w widoku osobistym zna przypisania ────────────


def test_personal_scope_clause_counts_live_work_assignments() -> None:
    from app.api.recruitment_access import job_scope_clause

    recruiter = User(id=9101, role=UserRole.recruiter, is_active=True)
    personal = str(
        job_scope_clause(recruiter, Job.id, oversight_bypass=False).compile()
    )
    assert "job_work_assignments" in personal
    # Widok organizacyjny rekrutera nadal nie jest niczym zawężany.
    assert str(job_scope_clause(recruiter, Job.id)) == "true"


# ── R10-V2-2: „Moje następne kroki” — przypisania nie zjadają LIMIT ──────────


async def _seed_user(role: UserRole = UserRole.recruiter) -> tuple[dict, int]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token, hash_password

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"r10-pipe-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Pipe"),
            name=f"R10 Pipe {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    return {"Authorization": f"Bearer {create_access_token(uid, role.value)}"}, uid


async def _seed_next_steps_world(me: int, other: int, *, via: str) -> tuple[set, int]:
    """27 rekrutacji z bliskim terminem „moich” tylko przez ``via`` + jedna
    własna z dalekim terminem."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import JobStatus
    from app.models.job_collaborator import JobCollaborator
    from app.models.job_work_assignment import JobWorkAssignment

    tag = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R10PipeNext-{tag}")
        db.add(client)
        await db.flush()
        near = [
            Job(
                title=f"R10-near-{i}-{tag}",
                status=JobStatus.published,
                client_id=client.id,
                recruiter_id=other,
                deadline=today + timedelta(days=1),
            )
            for i in range(27)
        ]
        own = Job(
            title=f"R10-own-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=me,
            deadline=today + timedelta(days=30),
        )
        db.add_all([*near, own])
        await db.flush()
        if via == "assignment":
            db.add_all(
                JobWorkAssignment(
                    job_id=job.id,
                    user_id=me,
                    role="recruiter",
                    source="manual",
                    state="active",
                )
                for job in near
            )
        else:
            db.add_all(
                JobCollaborator(job_id=job.id, user_id=me, removed_from_auto_cc=True)
                for job in near
            )
        await db.commit()
        return {job.id for job in near}, own.id


@pytest.mark.asyncio
async def test_my_next_steps_accepts_work_assignments(
    app_client: AsyncClient,
) -> None:
    headers, me = await _seed_user(UserRole.recruiter)
    _, other = await _seed_user(UserRole.recruiter)
    near, own = await _seed_next_steps_world(me, other, via="assignment")

    resp = await app_client.get("/api/pipeline/my-next-steps", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {j["job_id"] for j in body["jobs"]}
    # Przed poprawką: 26 przypisanych zajmowało LIMIT i każde było odrzucane
    # przez bramkę tablicy — lista pusta z `truncated=True`.
    assert body["truncated"] is True
    assert len(ids) == 25
    assert ids <= near


@pytest.mark.asyncio
async def test_my_next_steps_filters_removed_collaborators_before_limit(
    app_client: AsyncClient,
) -> None:
    headers, me = await _seed_user(UserRole.recruiter)
    _, other = await _seed_user(UserRole.recruiter)
    near, own = await _seed_next_steps_world(me, other, via="removed_collaborator")

    resp = await app_client.get("/api/pipeline/my-next-steps", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {j["job_id"] for j in body["jobs"]}
    assert ids == {own}
    assert body["truncated"] is False


# ── R10-V2-4: /move dla pary bez wiersza = dodanie osoby z blokadą 12 h ──────


@pytest.mark.asyncio
async def test_move_adding_a_fresh_pair_claims_and_stamps_entry_source(
    app_client: AsyncClient,
) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_process import RecruitmentProcess
    from app.services.candidate_claim import ENTRY_ADDED_MANUAL
    from tests.test_pipeline_membership_gate import (
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
        MOVE,
        headers=headers_a,
        json={"candidate_id": cand, "job_id": job_id, "stage": "new"},
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


@pytest.mark.asyncio
async def test_hiring_manager_of_a_vetoing_job_changes_only_by_admin_or_hor(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job as JobModel
    from app.services.hiring_manager_verdicts import load_manager_rejections
    from tests.test_manager_rejection_gate import _seed_vetoed_candidate
    from tests.test_pipeline_membership_gate import _seed_recruiter

    world = await _seed_vetoed_candidate()
    headers, _ = await _seed_recruiter(app_client)
    source = world["source_job_id"]

    cleared = await app_client.put(
        f"/api/jobs/{source}/hiring-manager", headers=headers, json={"clear": True}
    )
    assert cleared.status_code == 409, cleared.text
    patched = await app_client.patch(
        f"/api/jobs/{source}",
        headers=headers,
        json={"hiring_manager_contact_id": None},
    )
    assert patched.status_code == 409, patched.text

    async with AsyncSessionLocal() as db:
        target = await db.get(JobModel, world["target_job_id"])
        vetoes = await load_manager_rejections(
            db, job=target, candidate_ids=[world["candidate_id"]]
        )
    assert world["candidate_id"] in vetoes

    # Rekrutacja w pracy (04.10.2026): samo wyczyszczenie byłoby nowym brakiem
    # bramki przekazania — admin zdejmuje HM decyzją „Klient nie podał”.
    by_admin = await app_client.put(
        f"/api/jobs/{source}/hiring-manager",
        headers=app_auth_headers,
        json={"not_provided": True},
    )
    assert by_admin.status_code == 200, by_admin.text


def test_fresh_pair_entry_kwargs_mirror_bulk_add() -> None:
    from types import SimpleNamespace

    from app.api.pipeline import _fresh_pair_entry_kwargs
    from app.services.candidate_claim import ENTRY_ADDED_MANUAL, ENTRY_AUTO_MATCH

    human = SimpleNamespace(state=SimpleNamespace())
    integration = SimpleNamespace(state=SimpleNamespace(oauth_client_id="jjit"))
    user = User(id=77, role=UserRole.recruiter)
    assert _fresh_pair_entry_kwargs(user, human) == {
        "entry_source": ENTRY_ADDED_MANUAL,
        "claim_for_user_id": 77,
    }
    assert _fresh_pair_entry_kwargs(user, None)["claim_for_user_id"] == 77
    assert _fresh_pair_entry_kwargs(user, integration) == {
        "entry_source": ENTRY_AUTO_MATCH
    }


# ── R10-V2-6: przerwana generacja CV wraca do kolejki najwyżej raz ───────────


@pytest.mark.asyncio
async def test_requeue_sql_skips_jobs_already_requeued_once() -> None:
    from unittest.mock import AsyncMock, Mock

    from app.services.cv_generator_b2b import job_leases

    db = AsyncMock()
    db.execute.return_value = Mock(
        scalars=Mock(return_value=Mock(all=Mock(return_value=[])))
    )
    await job_leases.requeue_unstarted_expired_jobs(db)
    sql = str(
        db.execute.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "cv_generation_jobs.error_code != 'requeued_after_lost_worker'" in sql
    assert "error_code='requeued_after_lost_worker'" in sql.replace(" ", "")


@pytest.mark.asyncio
async def test_expired_unstarted_job_is_requeued_only_once() -> None:
    from datetime import datetime, timezone

    from sqlalchemy import delete, update

    from app.core.database import AsyncSessionLocal
    from app.models.cv_generation_job import CvGenerationJob
    from app.services.cv_generator_b2b.job_leases import (
        interrupt_expired_jobs,
        requeue_unstarted_expired_jobs,
    )

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    job = CvGenerationJob(
        kind="new",
        status="running",
        input_storage_key=f"synthetic/r10/{uuid.uuid4().hex}",
        input_sha256="0" * 64,
        lease_token=str(uuid.uuid4()),
        lease_expires_at=past,
    )
    job_id = None
    try:
        async with AsyncSessionLocal() as db:
            db.add(job)
            await db.commit()
            job_id = job.id
        async with AsyncSessionLocal() as db:
            assert job_id in await requeue_unstarted_expired_jobs(db)
            await db.commit()
        # Wykonawca bierze zadanie i znowu pada przy odczycie źródła.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(CvGenerationJob)
                .where(CvGenerationJob.id == job_id)
                .values(
                    status="running",
                    lease_token=str(uuid.uuid4()),
                    lease_expires_at=past,
                )
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert job_id not in await requeue_unstarted_expired_jobs(db)
            assert job_id in await interrupt_expired_jobs(db)
            await db.commit()
    finally:
        if job_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(CvGenerationJob).where(CvGenerationJob.id == job_id)
                )
                await db.commit()


# ── R10-V2-7: usunięcie pary nie kasuje maila, który właśnie wychodzi ────────


@pytest.mark.asyncio
async def test_remove_from_recruitment_refuses_while_rejection_mail_is_sending(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.rejection_email import (
        RejectionEmailStatus,
        ScheduledRejectionEmail,
    )
    from app.services.rejection_email_scheduler import SEND_IN_PROGRESS
    from tests.test_pipeline_membership_gate import (
        _seed_candidate,
        _seed_job,
        _seed_recruiter,
        _seed_stage,
    )

    _, sender = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=None)
    cand = await _seed_candidate()
    stage_id = await _seed_stage(cand, job_id, "rejected")
    async with AsyncSessionLocal() as db:
        mail = ScheduledRejectionEmail(
            candidate_stage_id=stage_id,
            candidate_id=cand,
            job_id=job_id,
            recruiter_id=sender,
            to_email=f"r10-{uuid.uuid4().hex[:8]}@example.com",
            subject="Dziękujemy",
            body_html="<p>Dziękujemy</p>",
            status=RejectionEmailStatus.pending,
            # Dzierżawa w przyszłości — pętla wysyłki (gdyby działała) nie
            # weźmie tego wiersza.
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=2),
            last_error=SEND_IN_PROGRESS,
        )
        db.add(mail)
        await db.commit()
        mail_id = mail.id
    try:
        resp = await app_client.delete(
            f"/api/candidates/{cand}/recruitments/{job_id}", headers=app_auth_headers
        )
        assert resp.status_code == 409, resp.text
        async with AsyncSessionLocal() as db:
            assert await db.get(ScheduledRejectionEmail, mail_id) is not None
            assert (
                await db.scalar(
                    select(CandidateStage.id).where(CandidateStage.id == stage_id)
                )
                == stage_id
            )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ScheduledRejectionEmail).where(
                    ScheduledRejectionEmail.id == mail_id
                )
            )
            await db.commit()


# ── R10-V2-9: reguła maila odrzucenia czyta poprzedni wiersz po moved_at ─────


@pytest.mark.asyncio
async def test_previous_row_for_rejection_mail_follows_moved_at() -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services.rejection_email_scheduler import _previous_row_client_visible
    from tests.test_pipeline_membership_gate import _seed_candidate, _seed_job

    job_id, _ = await _seed_job(owner_id=None)
    cand = await _seed_candidate()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        sent = CandidateStage(
            candidate_id=cand,
            job_id=job_id,
            stage=PipelineStage.cv_sent,
            moved_at=now - timedelta(days=1),
        )
        db.add(sent)
        await db.flush()
        # Import historyczny: starszy `moved_at`, wyższe id.
        imported = CandidateStage(
            candidate_id=cand,
            job_id=job_id,
            stage=PipelineStage.new,
            moved_at=now - timedelta(days=30),
        )
        db.add(imported)
        await db.flush()
        rejected = CandidateStage(
            candidate_id=cand,
            job_id=job_id,
            stage=PipelineStage.rejected,
            moved_at=now,
        )
        db.add(rejected)
        await db.flush()
        assert imported.id > sent.id
        assert await _previous_row_client_visible(db, rejected) is True
        await db.rollback()


# ── R10-V2-10: ścieżka kanoniczna radaru filtruje pulę w paczkach ────────────


@pytest.mark.asyncio
async def test_canonical_gate_applies_dealbreakers_in_chunks(monkeypatch) -> None:
    from types import SimpleNamespace

    import app.api.matching as matching
    from app.services import requirement_verification
    from app.services import talent_radar_search as trs
    from app.services.dealbreaker_filters import (
        DealbreakerInputs,
        apply_dealbreakers,
    )
    from tests.test_search_round9 import _cand, _counting_sleep, _decision

    cands = [
        _cand(i, expected_rate_hourly=(200 if i % 3 == 0 else 90))
        for i in range(1, 301)
    ]
    inputs = DealbreakerInputs(budget_hourly=100.0)

    from app.services.candidate_job_eligibility import EligibilityReason

    def eligible():
        decision = _decision("none", "visible")
        decision.reason_code = EligibilityReason.eligible
        decision.secondary_reasons = []
        return decision

    async def decisions(db, *, job, candidate_ids, now):
        return {cid: eligible() for cid in candidate_ids}

    async def noop(db, job, candidates):
        return None

    monkeypatch.setattr(matching, "evaluate_candidates_for_job", decisions)
    monkeypatch.setattr(requirement_verification, "load_verified_requirements", noop)
    counter = _counting_sleep(monkeypatch, trs)

    kept, _, hidden, _, used = await matching._gate_and_dealbreakers(
        SimpleNamespace(),
        job=SimpleNamespace(id=1),
        ordered=cands,
        now=None,
        inputs=inputs,
    )

    whole = apply_dealbreakers(cands, inputs=inputs, exclude_remote_only=False)
    assert [c.id for c in kept] == [c.id for c in whole.kept]
    assert hidden == whole.hidden_meta()
    assert used is inputs
    assert counter["yields"] >= 300 // trs.DEALBREAKER_CHUNK


# ── R10-X2-1 / X2-2: stan i status requestu na liście /jobs ─────────────────


def _work_state_cases() -> list[dict]:
    import json
    from pathlib import Path

    from app.services.request_work_state import WORK_STATES

    cases = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "frontend/src/lib/__fixtures__/request-work-state-cases.json"
        ).read_text()
    )["cases"]
    # Kolumna `jobs.work_state` przyjmuje tylko znane stany.
    return [case for case in cases if case["work_state"] in WORK_STATES]


@pytest.mark.asyncio
async def test_list_request_stage_matches_visible_state_cases() -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import JobStatus
    from app.services import job_similarity as sim

    cases = _work_state_cases()
    assert any(c["work_state"] == "client_silent" and c["champion"] for c in cases)
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R10PipeState-{tag}")
        db.add(client)
        await db.flush()
        jobs = [
            Job(
                title=f"R10-state-{i}-{tag}",
                status=JobStatus.published,
                client_id=client.id,
                work_state=case["work_state"],
                champion_found_at=(
                    datetime.now(timezone.utc) if case["champion"] else None
                ),
            )
            for i, case in enumerate(cases)
        ]
        db.add_all(jobs)
        await db.commit()
        stages = await sim.request_statuses_and_stages(db, [j.id for j in jobs])
    for job, case in zip(jobs, cases):
        assert stages[job.id][1] == case["visible"], case


@pytest.mark.asyncio
async def test_onboarding_counts_as_hired_in_request_status() -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services import job_similarity as sim
    from tests.test_pipeline_membership_gate import _seed_candidate, _seed_job

    job_id, _ = await _seed_job(owner_id=None)
    cand = await _seed_candidate()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                CandidateStage(
                    candidate_id=cand,
                    job_id=job_id,
                    stage=PipelineStage.hired,
                    moved_at=now - timedelta(minutes=5),
                ),
                CandidateStage(
                    candidate_id=cand,
                    job_id=job_id,
                    stage=PipelineStage.onboarding,
                    moved_at=now,
                ),
            ]
        )
        await db.commit()
        status_, stage = (await sim.request_statuses_and_stages(db, [job_id]))[job_id]
    assert status_ == "filled"
    assert stage == "filled"


def test_contract_stages_exclude_onboarding() -> None:
    from app.models.recruitment_pipeline import PipelineStage
    from app.services import job_similarity as sim

    assert PipelineStage.onboarding not in sim.CONTRACT_STAGES
    assert PipelineStage.onboarding in sim.HIRED_STAGES
