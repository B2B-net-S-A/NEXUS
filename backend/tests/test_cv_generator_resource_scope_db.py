"""Hosted PostgreSQL coverage: history filtering must happen before LIMIT; the
readiness picker lists every recruitment of the candidate (decision 10.09.2026)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api import cv_generator_b2b as api
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_history_is_scoped_before_limit_and_readiness_lists_all():
    uid = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        # Roll back all fixtures, including synthetic users, after assertions.
        owner = User(
            email=f"cv-owner-{uid}@example.test", name="Owner", role=UserRole.recruiter
        )
        outsider = User(
            email=f"cv-out-{uid}@example.test", name="Outsider", role=UserRole.recruiter
        )
        finance = User(
            email=f"cv-fin-{uid}@example.test", name="Finance", role=UserRole.finance
        )
        client = Client(name=f"CV scope {uid}")
        candidate = Candidate(name="Synthetic", lastname="Scope")
        db.add_all([owner, outsider, finance, client, candidate])
        await db.flush()
        own_job = Job(
            title="Own recruitment", client_id=client.id, recruiter_id=owner.id
        )
        other_job = Job(
            title="Other recruitment", client_id=client.id, recruiter_id=outsider.id
        )
        db.add_all([own_job, other_job])
        await db.flush()
        own_stage = CandidateStage(
            candidate_id=candidate.id, job_id=own_job.id, stage=PipelineStage.new
        )
        other_stage = CandidateStage(
            candidate_id=candidate.id, job_id=other_job.id, stage=PipelineStage.new
        )
        # Place outsider's document first: filtering after LIMIT would hide ours.
        now = datetime.now(timezone.utc) + timedelta(days=30)
        own_doc = CvGeneratedDocument(
            candidate_id=candidate.id,
            job_id=own_job.id,
            candidate_name="Own",
            filename="own.docx",
            status="processing",
            created_by=owner.id,
            created_at=now,
        )
        other_doc = CvGeneratedDocument(
            candidate_id=candidate.id,
            job_id=other_job.id,
            candidate_name="Other",
            filename="other.docx",
            status="ready",
            created_by=outsider.id,
            created_at=now + timedelta(seconds=1),
        )
        db.add_all([own_stage, other_stage, own_doc, other_doc])
        await db.flush()
        own_list = await api.list_generated_cvs(owner, db, limit=1)
        assert [row.id for row in own_list] == [own_doc.id]
        finance_list = await api.list_generated_cvs(finance, db, limit=2)
        assert [row.id for row in finance_list] == [other_doc.id, own_doc.id]
        # Decyzja 10.09.2026 („wszyscy mogą”): picker gotowości NIE jest
        # zawężany do zespołu — rekrutacja nieobecna tutaj byłaby rekrutacją,
        # pod którą nie da się wygenerować CV z interfejsu.
        readiness = await api.list_candidate_recruitments(candidate.id, owner, db)
        assert {row.job_id for row in readiness} == {own_job.id, other_job.id}
        finance_readiness = await api.list_candidate_recruitments(
            candidate.id, finance, db
        )
        assert {row.job_id for row in finance_readiness} == {own_job.id, other_job.id}
        assert await api._load_generated_document(db, own_doc.id, owner) is own_doc
        assert (
            await api._load_generated_document(db, other_doc.id, finance) is other_doc
        )
        with pytest.raises(HTTPException) as exc:
            await api._load_generated_document(db, other_doc.id, owner)
        assert exc.value.status_code == 403
        # More than a global history page must not hide this candidate's CV.
        for i in range(65):
            db.add(
                CvGeneratedDocument(
                    candidate_name=f"Other {i}",
                    filename="other.docx",
                    created_by=outsider.id,
                    job_id=other_job.id,
                )
            )
        newer_own = CvGeneratedDocument(
            candidate_id=candidate.id,
            job_id=own_job.id,
            candidate_name="Own upload",
            filename="own.docx",
            created_by=owner.id,
            mode="upload",
        )
        db.add(newer_own)
        await db.flush()
        first_page = await api.list_generated_cvs(
            owner, db, limit=1, candidate_id=candidate.id, job_id=own_job.id
        )
        assert [r.id for r in first_page] == [newer_own.id]
        second_page = await api.list_generated_cvs(
            owner,
            db,
            limit=1,
            candidate_id=candidate.id,
            job_id=own_job.id,
            before_id=first_page[-1].id,
        )
        assert [r.id for r in second_page] == [own_doc.id]
        assert (
            await api.list_generated_cvs(
                owner,
                db,
                limit=1,
                candidate_id=candidate.id,
                job_id=own_job.id,
                before_id=own_doc.id,
            )
            == []
        )
        await db.rollback()


@pytest.mark.asyncio
async def test_author_outside_the_team_keeps_own_cv_on_real_scope():
    """Generować może każdy (10.09.2026) — autor spoza zespołu rekrutacji widzi
    swoje CV na liście (także z filtrem rekrutacji, zamiast 403) i otwiera je,
    ale cudzych CV tej rekrutacji dalej nie widzi."""
    uid = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        owner = User(
            email=f"cv-a-owner-{uid}@example.test",
            name="Owner",
            role=UserRole.recruiter,
        )
        author = User(
            email=f"cv-a-author-{uid}@example.test",
            name="Author",
            role=UserRole.recruiter,
        )
        client = Client(name=f"CV author scope {uid}")
        candidate = Candidate(name="Synthetic", lastname="Author")
        db.add_all([owner, author, client, candidate])
        await db.flush()
        job = Job(title="Owner recruitment", client_id=client.id, recruiter_id=owner.id)
        db.add(job)
        await db.flush()
        teams_doc = CvGeneratedDocument(
            candidate_id=candidate.id,
            job_id=job.id,
            candidate_name="Team",
            filename="team.docx",
            status="ready",
            created_by=owner.id,
        )
        authors_doc = CvGeneratedDocument(
            candidate_id=candidate.id,
            job_id=job.id,
            candidate_name="Author",
            filename="author.docx",
            status="ready",
            created_by=author.id,
        )
        db.add_all([teams_doc, authors_doc])
        await db.flush()

        listed = await api.list_generated_cvs(
            author, db, limit=10, candidate_id=candidate.id, job_id=job.id
        )
        assert [row.id for row in listed] == [authors_doc.id]
        assert listed[0].can_delete is True
        assert (
            await api._load_generated_document(db, authors_doc.id, author)
            is authors_doc
        )
        with pytest.raises(HTTPException) as exc:
            await api._load_generated_document(db, teams_doc.id, author)
        assert exc.value.status_code == 403
        # The team keeps seeing every CV of its recruitment, the outsider's too.
        team_view = await api.list_generated_cvs(
            owner, db, limit=10, candidate_id=candidate.id, job_id=job.id
        )
        assert {row.id for row in team_view} == {teams_doc.id, authors_doc.id}
        await db.rollback()
