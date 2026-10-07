"""Audyt 06.10.2026 — przekazanie rekrutacji i „Do przejrzenia” (PR 2, z bazą).

Raport: ``docs/audits/2026-10-06/rekrutacja-przekazanie-i-wyszukiwanie.md``.

- H2: „Nowe requesty dla Ciebie” na pulpicie rekrutera,
- H4: uczestnicy kategorii nie są odbiorcami dzwonków rekrutacji,
- H7: rekrutacja bez przekazania do searchu w kolejce Head of Recruitment,
- add_person (H1): dodanie z pulpitu dzwoni do dodanej osoby,
- R1: nocny przegląd nie zajmuje miejsc osobami już rozstrzygniętymi,
- R5: każde dodanie do rekrutacji zamyka propozycję,
- R6: zamknięcie rekrutacji wygasza propozycje (i jednorazowa korekta),
- R8: „Pomiń zaznaczone” jednym powodem,
- telemetria otwarcia skrzynki,
- U1: „Przypisz do rekrutacji” z listy kandydatów = etap „Nowi” + blokada 12 h.

Baza testowa jest wspólna i nieczyszczona — asercje dotyczą własnych wierszy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus
from app.models.job_proposal import JobProposal, JobProposalInboxOpen
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import job_proposals as proposals
from tests.test_job_proposals import _inbox, _statuses, _user, _world


async def _seed(job_id: int, candidate_ids: list[int], source: str = "full_base"):
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": c} for c in candidate_ids], source
        )
        await db.commit()


async def _pair_status(job_id: int, candidate_id: int) -> set[str]:
    statuses = await _statuses(job_id)
    return {s for (cid, _src), s in statuses.items() if cid == candidate_id}


# ── R6: zamknięcie rekrutacji ────────────────────────────────────────────────


async def test_close_expires_open_proposals_and_keeps_human_decisions(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world(people=3)
    job_id = world["job_id"]
    open_one, dismissed, added = world["candidate_ids"]
    await _seed(job_id, world["candidate_ids"])
    async with AsyncSessionLocal() as db:
        await proposals.mark_added(db, job_id=job_id, candidate_ids=[added])
        await db.execute(
            update(JobProposal)
            .where(JobProposal.job_id == job_id, JobProposal.candidate_id == dismissed)
            .values(status="dismissed")
        )
        await db.commit()

    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "budget"},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text

    assert await _pair_status(job_id, open_one) == {"expired"}
    assert await _pair_status(job_id, dismissed) == {"dismissed"}
    assert await _pair_status(job_id, added) == {"added"}

    # Ponowne otwarcie nie wskrzesza wygasłych propozycji.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.published)
        )
        await db.commit()
        counts = await proposals.open_counts_for_jobs(db, [job_id])
    assert counts.get(job_id, 0) == 0


async def test_closing_from_the_edit_window_expires_open_proposals_too(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world(people=1)
    job_id = world["job_id"]
    [candidate_id] = world["candidate_ids"]
    await _seed(job_id, [candidate_id])

    closed = await app_client.patch(
        f"/api/jobs/{job_id}", json={"status": "closed"}, headers=app_auth_headers
    )
    assert closed.status_code == 200, closed.text
    assert await _pair_status(job_id, candidate_id) == {"expired"}


async def test_client_deletion_expires_proposals_of_the_jobs_it_closes():
    from app.services.client_deletion import _close_open_recruitments

    actor_id, _ = await _user(UserRole.admin)
    world = await _world(people=1)
    job_id = world["job_id"]
    [candidate_id] = world["candidate_ids"]
    await _seed(job_id, [candidate_id])

    async with AsyncSessionLocal() as db:
        actor = await db.get(User, actor_id)
        closed = await _close_open_recruitments(
            db, world["client_id"], actor=actor, now=datetime.now(timezone.utc)
        )
        await db.commit()
    assert closed == [job_id]
    assert await _pair_status(job_id, candidate_id) == {"expired"}


async def test_one_time_repair_expires_proposals_of_closed_jobs_once():
    from app.models.app_setting import AppSetting
    from app.services.job_proposal_closed_expiry import (
        REPAIR_MARKER,
        run_closed_job_proposal_expiry,
    )

    world = await _world(people=2)
    job_id = world["job_id"]
    await _seed(job_id, world["candidate_ids"])
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.closed)
        )
        await db.execute(delete(AppSetting).where(AppSetting.key == REPAIR_MARKER))
        await db.commit()

    async with AsyncSessionLocal() as db:
        summary = await run_closed_job_proposal_expiry(db)
        await db.commit()
    assert summary is not None
    assert summary["expired_rows"] >= 2 and summary["jobs"] >= 1
    assert set((await _statuses(job_id)).values()) == {"expired"}

    async with AsyncSessionLocal() as db:
        assert await run_closed_job_proposal_expiry(db) is None
        receipt = await db.get(AppSetting, REPAIR_MARKER)
    # Paragon niesie wyłącznie liczby i datę.
    assert set(receipt.value) == {"done_at", "expired_rows", "jobs"}


# ── R8: „Pomiń zaznaczone” ───────────────────────────────────────────────────


async def test_bulk_dismiss_needs_a_reason_and_skips_unknown_people(
    app_client: AsyncClient,
):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    world = await _world(people=3, recruiter_id=recruiter_id)
    job_id = world["job_id"]
    first, second, outside = world["candidate_ids"]
    await _seed(job_id, [first, second])

    no_reason = await app_client.post(
        f"{_inbox(job_id)}/dismiss-bulk",
        json={"candidate_ids": [first, second]},
        headers=recruiter,
    )
    assert no_reason.status_code == 422, no_reason.text
    assert await _pair_status(job_id, first) == {"proposed"}

    done = await app_client.post(
        f"{_inbox(job_id)}/dismiss-bulk",
        json={
            "candidate_ids": [first, second, outside, 999_999_999],
            "reason": "too_expensive",
        },
        headers=recruiter,
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert sorted(body["dismissed"]) == sorted([first, second])
    assert set(body["skipped"]) == {outside, 999_999_999}
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(select(JobProposal).where(JobProposal.job_id == job_id))
        ).all()
    assert {(r.candidate_id, r.status, r.dismiss_reason) for r in rows} == {
        (first, "dismissed", "too_expensive"),
        (second, "dismissed", "too_expensive"),
    }


# ── telemetria otwarcia ──────────────────────────────────────────────────────


async def test_inbox_open_is_recorded_once_per_person_and_day(
    app_client: AsyncClient,
):
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    world = await _world(people=1, recruiter_id=recruiter_id)
    job_id = world["job_id"]

    first = await app_client.post(f"{_inbox(job_id)}/opened", headers=recruiter)
    again = await app_client.post(f"{_inbox(job_id)}/opened", headers=recruiter)
    assert first.status_code == 200, first.text
    assert first.json() == {"recorded": True}
    assert again.json() == {"recorded": False}
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(JobProposalInboxOpen).where(
                    JobProposalInboxOpen.job_id == job_id
                )
            )
        ).all()
    assert [(r.user_id) for r in rows] == [recruiter_id]

    missing = await app_client.post(f"{_inbox(999_999_999)}/opened", headers=recruiter)
    assert missing.status_code == 404


# ── R5 i U1: dodanie do rekrutacji ───────────────────────────────────────────


async def test_every_way_of_adding_closes_the_proposal():
    from app.models.recruitment_pipeline import PipelineStage
    from app.services.recruitment_process_commands import open_process

    world = await _world(people=1)
    job_id = world["job_id"]
    [candidate_id] = world["candidate_ids"]
    await _seed(job_id, [candidate_id])

    async with AsyncSessionLocal() as db:
        await open_process(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage.new,
            stage_def_id=None,
            moved_at=datetime.now(timezone.utc),
            actor_user_id=None,
        )
        await db.commit()

    assert await _pair_status(job_id, candidate_id) == {"added"}


async def test_assign_from_candidate_list_lands_in_new_with_a_claim(
    app_client: AsyncClient,
):
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.recruitment_process import RecruitmentProcess

    recruiter_id, recruiter = await _user(UserRole.recruiter, pipeline="write")
    world = await _world(people=1, recruiter_id=recruiter_id)
    job_id = world["job_id"]
    [candidate_id] = world["candidate_ids"]
    await _seed(job_id, [candidate_id])
    url = f"/api/candidates/{candidate_id}/assign-to-job/{job_id}"

    first = await app_client.post(url, headers=recruiter)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "assigned"
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, first.json()["stage_id"])
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.job_id == job_id,
                RecruitmentProcess.candidate_id == candidate_id,
            )
        )
    stage_value = getattr(stage.stage, "value", stage.stage)
    assert stage_value == "new"
    assert process.claimed_by_user_id == recruiter_id
    assert process.entry_source == "added_manual"
    assert await _pair_status(job_id, candidate_id) == {"added"}

    again = await app_client.post(url, headers=recruiter)
    assert again.status_code == 200, again.text
    assert again.json() == {"status": "already_in_pipeline", "count": 1}


# ── R1: nocny przegląd ───────────────────────────────────────────────────────


async def test_nightly_review_skips_people_already_decided():
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services.auto_full_review import _already_decided
    from app.services.auto_match_outbox import candidate_revision

    world = await _world(people=5)
    job_id = world["job_id"]
    fresh, in_job, added, dismissed, blacklisted = world["candidate_ids"]
    await _seed(job_id, [fresh, added, dismissed])
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=in_job,
                job_id=job_id,
                stage=PipelineStage.new,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await proposals.mark_added(db, job_id=job_id, candidate_ids=[added])
        # Pominięcie tej samej wersji CV blokuje miejsce; pominięcie bez wersji
        # ustępuje nowemu CV (ta sama reguła co ``_resurrect_on_new_cv``).
        same_revision = candidate_revision(await db.get(Candidate, dismissed))
        await db.execute(
            update(JobProposal)
            .where(JobProposal.job_id == job_id, JobProposal.candidate_id == dismissed)
            .values(status="dismissed", dismissed_cv_revision=same_revision)
        )
        await db.execute(
            update(Candidate)
            .where(Candidate.id == blacklisted)
            .values(status=CandidateStatus.blacklisted)
        )
        await db.commit()
        candidates = {
            c.id: c
            for c in (
                await db.scalars(
                    select(Candidate).where(Candidate.id.in_(world["candidate_ids"]))
                )
            ).all()
        }
        skip = await _already_decided(db, job_id, candidates)
    assert skip == {in_job, added, dismissed, blacklisted}


# ── H4: uczestnicy kategorii ─────────────────────────────────────────────────


async def test_category_participants_are_members_but_not_bell_recipients():
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
    from app.services.job_membership import list_job_member_ids

    manual_id, _ = await _user(UserRole.recruiter)
    category_id, _ = await _user(UserRole.recruiter)
    world = await _world(people=0)
    job_id = world["job_id"]
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobCollaborator(
                    job_id=job_id,
                    user_id=manual_id,
                    source=JobCollaboratorSource.manual,
                ),
                JobCollaborator(
                    job_id=job_id,
                    user_id=category_id,
                    source=JobCollaboratorSource.auto_cc,
                ),
            ]
        )
        await db.commit()
        members = set(await list_job_member_ids(db, job_id))
        bells = set(
            await list_job_member_ids(db, job_id, include_category_participants=False)
        )
    assert {manual_id, category_id} <= members
    assert manual_id in bells
    assert category_id not in bells


# ── H1: dodanie z pulpitu ────────────────────────────────────────────────────


async def test_adding_a_person_from_the_board_rings_them(
    app_client: AsyncClient, app_auth_headers: dict
):
    person_id, _ = await _user(UserRole.recruiter)
    world = await _world(people=0)
    job_id = world["job_id"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(work_state="searching")
        )
        await db.commit()

    for _ in range(2):
        added = await app_client.post(
            f"/api/request-board/jobs/{job_id}/people",
            json={"user_id": person_id},
            headers=app_auth_headers,
        )
        assert added.status_code == 200, added.text

    async with AsyncSessionLocal() as db:
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == person_id,
                    Notification.notification_type
                    == NotificationType.request_assignment_changed,
                )
            )
        ).all()
    # Drugie dodanie tej samej osoby nie dzwoni drugi raz.
    assert [b.related_entity_id for b in bells] == [job_id]


# ── H2: „Nowe requesty dla Ciebie” ───────────────────────────────────────────


async def test_new_requests_show_until_the_first_move_on_the_board():
    from app.models.candidate import Candidate
    from app.models.job_work_assignment import JobWorkAssignment
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services import board_flow

    recruiter_id, _ = await _user(UserRole.recruiter)
    assigner_id, _ = await _user(UserRole.head_of_recruitment)
    world = await _world(people=0)
    stale = await _world(people=0)
    job_id = world["job_id"]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job)
            .where(Job.id.in_([job_id, stale["job_id"]]))
            .values(work_state="searching")
        )
        db.add_all(
            [
                JobWorkAssignment(
                    job_id=job_id,
                    user_id=recruiter_id,
                    role="recruiter",
                    source="manual",
                    state="active",
                    assigned_at=now - timedelta(hours=2),
                    assigned_by=assigner_id,
                ),
                # Przypisanie sprzed 5 dni nie jest już „nowe”.
                JobWorkAssignment(
                    job_id=stale["job_id"],
                    user_id=recruiter_id,
                    role="recruiter",
                    source="auto",
                    state="active",
                    assigned_at=now - timedelta(days=5),
                ),
            ]
        )
        await db.commit()

        user = await db.get(User, recruiter_id)
        flow = await board_flow.load_flow(db, user)
        rows = [r for r in flow.new_requests if r.job_id in (job_id, stale["job_id"])]
        assert [(r.job_id, r.assigned_by_name) for r in rows] == [
            (job_id, "Proposals head_of_recruitment")
        ]

        candidate = Candidate(name="Ruch", lastname=uuid.uuid4().hex[:8])
        db.add(candidate)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job_id,
                stage=PipelineStage.new,
                moved_at=now,
                moved_by=recruiter_id,
            )
        )
        await db.commit()
        flow = await board_flow.load_flow(db, user)
    assert job_id not in {r.job_id for r in flow.new_requests}


# ── H7: rekrutacja bez przekazania ───────────────────────────────────────────


async def test_published_job_without_handoff_is_listed_for_head_of_recruitment(
    monkeypatch,
):
    from app.services import new_job_leads

    monkeypatch.setattr(new_job_leads, "MAX_ROWS", 100_000)
    world = await _world(people=0)
    handed = await _world(people=0)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == world["job_id"]).values(is_open=False)
        )
        await db.execute(
            update(Job).where(Job.id == handed["job_id"]).values(is_open=True)
        )
        await db.commit()
        leads = await new_job_leads.load_new_job_leads(
            db, now=datetime.now(timezone.utc)
        )
    by_job = {lead.job_id: lead for lead in leads}
    assert by_job[world["job_id"]].pending_reason == "not_handed_off"
    assert handed["job_id"] not in by_job or (
        by_job[handed["job_id"]].pending_reason != "not_handed_off"
    )


pytestmark = pytest.mark.asyncio
