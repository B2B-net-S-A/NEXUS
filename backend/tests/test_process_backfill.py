"""Testy RecruitmentProcess backfill + komparator shadow (M4 plan PR-06).

Kontrakty (sekcja 14.2 + AC PR-06 + decyzja §20.2):

- deterministyczny porządek (moved_at ASC, id ASC); tied timestamps
  rozstrzyga id; backdated eventy nie zmieniają wyniku (latest po ID przy
  tym samym moved_at, po moved_at gdy różne),
- jedna para = jeden proces, attempt_no=1 (reopen = ten sam proces),
- terminal latest → closed (+closed_at); aktywny latest → open,
- terminal-then-active (niejawny reopen w historii) → OPEN (jeden proces),
- semantic z bridge stage_def→StageRevision (published), fallback legacy,
  kwarantanna 'unmapped' bez zgadywania,
- rerun idempotentny (0 zmian bez resync); resync_stale aktualizuje pointer
  po nowym ruchu legacy i bumpuje state_version,
- partial unique: drugi otwarty proces pary → IntegrityError,
- komparator: pairs_without_process/stale_pointers liczone poprawnie.

Uses in-process fixtures (real postgres in CI) — migracja 0178 przez
`alembic upgrade heads`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.services.process_backfill import (
    backfill_recruitment_processes,
    compare_shadow_state,
)

BASE = "/api/admin/recruitment-processes"


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Proc",
            lastname=f"Bf-{uuid.uuid4().hex[:6]}",
            email=f"procbf-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"ProcClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Proc-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage_value: str,
    *,
    moved_at: datetime,
) -> int:
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
            moved_at=moved_at,
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage.id


async def _run_backfill(**kwargs) -> dict:
    async with AsyncSessionLocal() as db:
        return await backfill_recruitment_processes(db, **kwargs)


async def _get_process(candidate_id: int, job_id: int) -> RecruitmentProcess:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
        )


async def test_backfill_open_pair_with_history(app_client: AsyncClient):
    now = datetime.now(timezone.utc)
    cand, job = await _seed_candidate(), await _seed_job()
    first = await _seed_stage(cand, job, "new", moved_at=now - timedelta(days=5))
    latest = await _seed_stage(cand, job, "screening", moved_at=now - timedelta(days=1))

    await _run_backfill()
    p = await _get_process(cand, job)
    assert p is not None
    assert p.attempt_no == 1
    assert p.status == ProcessStatus.open
    assert p.legacy_current_candidate_stage_id == latest
    assert p.current_semantic_state == "screening_completed"
    assert p.opened_at is not None and p.closed_at is None
    assert p.source_authority == "backfill"
    assert first != latest  # sanity


async def test_backfill_terminal_pair_is_closed(app_client: AsyncClient):
    now = datetime.now(timezone.utc)
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "screening", moved_at=now - timedelta(days=3))
    await _seed_stage(cand, job, "hired", moved_at=now - timedelta(days=1))

    await _run_backfill()
    p = await _get_process(cand, job)
    assert p.status == ProcessStatus.closed
    assert p.closed_at is not None
    assert p.current_semantic_state == "hired"


async def test_terminal_then_active_is_single_open_process(
    app_client: AsyncClient,
):
    """Niejawny reopen w historii → JEDEN proces, status open (decyzja §20.2)."""
    now = datetime.now(timezone.utc)
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "hired", moved_at=now - timedelta(days=10))
    await _seed_stage(cand, job, "interview", moved_at=now - timedelta(days=2))

    await _run_backfill()
    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(RecruitmentProcess).where(
                        RecruitmentProcess.candidate_id == cand,
                        RecruitmentProcess.job_id == job,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].status == ProcessStatus.open
    assert rows[0].attempt_no == 1


async def test_tied_timestamps_resolved_by_id(app_client: AsyncClient):
    now = datetime.now(timezone.utc)
    cand, job = await _seed_candidate(), await _seed_job()
    tie = now - timedelta(days=1)
    await _seed_stage(cand, job, "new", moved_at=tie)
    second = await _seed_stage(cand, job, "screening", moved_at=tie)

    await _run_backfill()
    p = await _get_process(cand, job)
    assert p.legacy_current_candidate_stage_id == second  # wyższe id wygrywa


async def test_backdated_event_does_not_become_current(app_client: AsyncClient):
    now = datetime.now(timezone.utc)
    cand, job = await _seed_candidate(), await _seed_job()
    current = await _seed_stage(
        cand, job, "interview", moved_at=now - timedelta(days=1)
    )
    # Backdated (wyższe id, starszy moved_at) — np. import historyczny.
    await _seed_stage(cand, job, "new", moved_at=now - timedelta(days=30))

    await _run_backfill()
    p = await _get_process(cand, job)
    assert p.legacy_current_candidate_stage_id == current


async def test_rerun_is_idempotent_and_resync_updates(app_client: AsyncClient):
    now = datetime.now(timezone.utc)
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "screening", moved_at=now - timedelta(days=2))

    await _run_backfill()
    p1 = await _get_process(cand, job)
    v1, ptr1 = p1.state_version, p1.legacy_current_candidate_stage_id

    # Rerun bez zmian źródła → zero modyfikacji.
    await _run_backfill()
    p2 = await _get_process(cand, job)
    assert (p2.state_version, p2.legacy_current_candidate_stage_id) == (v1, ptr1)

    # Legacy poszedł dalej → zwykły rerun NIE dotyka (insert-only)…
    newer = await _seed_stage(cand, job, "cv_sent", moved_at=now)
    await _run_backfill()
    p3 = await _get_process(cand, job)
    assert p3.legacy_current_candidate_stage_id == ptr1

    # …a resync_stale aktualizuje pointer/semantic i bumpuje wersję.
    await _run_backfill(resync_stale=True)
    p4 = await _get_process(cand, job)
    assert p4.legacy_current_candidate_stage_id == newer
    assert p4.current_semantic_state == "submitted_to_client"
    assert p4.state_version == v1 + 1


async def test_partial_unique_one_open_process(app_client: AsyncClient):
    from sqlalchemy.exc import IntegrityError

    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "new", moved_at=datetime.now(timezone.utc))
    await _run_backfill()

    async with AsyncSessionLocal() as db:
        db.add(
            RecruitmentProcess(
                candidate_id=cand,
                job_id=job,
                attempt_no=2,
                status=ProcessStatus.open,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_shadow_compare_counts(app_client: AsyncClient):
    now = datetime.now(timezone.utc)
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "screening", moved_at=now - timedelta(days=1))
    await _run_backfill()
    # Nowy ruch legacy → stale pointer.
    await _seed_stage(cand, job, "interview", moved_at=now)

    async with AsyncSessionLocal() as db:
        report = await compare_shadow_state(db, sample_limit=50)
    assert report["stale_pointers"] >= 1
    assert any(
        s["candidate_id"] == cand and s["job_id"] == job for s in report["stale_sample"]
    )
    # Shadow compare działa na parach, a RecruitmentProcess na attemptach.
    # Liczba attemptów może być większa po reopen, a voided proces może nie
    # mieć legacy rows po jawnej archiwizacji. Obie strony muszą jednak
    # raportować dokładnie ten sam overlap par.
    legacy_overlap = report["pairs_total"] - report["pairs_without_process"]
    process_overlap = (
        report["process_pairs_total"] - report["process_pairs_without_legacy"]
    )
    assert legacy_overlap == process_overlap
    assert report["processes_total"] >= report["process_pairs_total"]


async def test_shadow_compare_uses_only_latest_attempt(app_client: AsyncClient):
    """Historyczny attempt nie może generować fałszywego stale pointera."""
    now = datetime.now(timezone.utc)
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "screening", moved_at=now - timedelta(days=1))
    await _run_backfill()
    latest = await _seed_stage(cand, job, "interview", moved_at=now)

    async with AsyncSessionLocal() as db:
        first_attempt = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == cand,
                RecruitmentProcess.job_id == job,
                RecruitmentProcess.attempt_no == 1,
            )
        )
        assert first_attempt is not None
        first_attempt.status = ProcessStatus.closed
        first_attempt.closed_at = now
        db.add(
            RecruitmentProcess(
                candidate_id=cand,
                job_id=job,
                attempt_no=2,
                previous_process_id=first_attempt.id,
                status=ProcessStatus.open,
                legacy_current_candidate_stage_id=latest,
                current_semantic_state="client_interview",
                source_authority="live_command",
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        report = await compare_shadow_state(db, sample_limit=50)

    assert report["processes_total"] > report["process_pairs_total"]
    assert not any(
        sample["candidate_id"] == cand and sample["job_id"] == job
        for sample in report["stale_sample"]
    )


async def test_admin_api_flow(app_client: AsyncClient, app_auth_headers):
    now = datetime.now(timezone.utc)
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "new", moved_at=now - timedelta(days=1))

    r = await app_client.post(
        f"{BASE}/backfill?limit_pairs=100000", headers=app_auth_headers
    )
    assert r.status_code == 200, r.text

    # Poczekaj aż background job skończy (in-process, szybki).
    import asyncio as _asyncio

    for _ in range(100):
        st = (
            await app_client.get(f"{BASE}/backfill/status", headers=app_auth_headers)
        ).json()
        if not st["running"] and st["finished_at"]:
            break
        await _asyncio.sleep(0.1)
    assert st["last_error"] is None, st

    detail = await app_client.get(
        f"{BASE}/by-pair/{cand}/{job}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["pointer_in_sync"] is True
    assert body["processes"][0]["attempt_no"] == 1

    cmp_resp = await app_client.get(f"{BASE}/shadow-compare", headers=app_auth_headers)
    assert cmp_resp.status_code == 200
    assert "stale_pointers" in cmp_resp.json()


async def test_admin_api_requires_admin(app_client: AsyncClient):
    r = await app_client.post(f"{BASE}/backfill")
    assert r.status_code in (401, 403)
