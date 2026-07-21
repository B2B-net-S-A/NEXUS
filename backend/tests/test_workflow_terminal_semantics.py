"""M4-P0.2 — custom terminal stages keep their hire/reject semantics.

A custom PipelineStageDef carries no ``legacy_enum_value`` (the StageDef schema
has no such field and clone_template doesn't copy it), so move_candidate mapped
it to ``new`` — a client's custom "Zatrudniony" stage never fired the auto-draft
Contract (keyed on ``hired``) and a custom "Odrzucony" never triggered the
rejection path. Fix: when a stage_def is terminal and no legacy_enum_value is
set, derive the legacy stage from ``terminal_type``.

Also: clone_template dropped ``scorecard_schema`` — a cloned template lost its
per-stage evaluation rubric.

Behavioural against a real Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.pipeline import move_candidate
from app.api.pipeline_templates import clone_template
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
    TerminalType,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.schemas.pipeline import StageMove


async def _seed_job_with_custom_terminal(term: TerminalType) -> dict:
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"wf-{u}@example.com", password_hash=hash_password("x"),
            name="Rec", role=UserRole.recruiter, is_active=True,
        )
        client = Client(name=f"WF {u}")
        cand = Candidate(name="Cust", lastname=f"Stage-{u}")
        tpl = PipelineTemplate(name=f"Custom {u}")
        db.add_all([user, client, cand, tpl])
        await db.flush()
        stage = PipelineStageDef(
            template_id=tpl.id,
            name=f"Custom-{term.value}-{u}",
            order=1,
            category=StageCategoryEnum.terminal,
            is_terminal=True,
            terminal_type=term,
            # legacy_enum_value deliberately unset — this is the whole point.
        )
        db.add(stage)
        await db.flush()
        # Owner = the acting recruiter (job.recruiter_id), so the P1-PIPE-01
        # membership gate admits them (these tests exercise terminal-stage
        # semantics, not access control).
        job = Job(
            title=f"WF Job {u}",
            client_id=client.id,
            pipeline_template_id=tpl.id,
            recruiter_id=user.id,
        )
        db.add(job)
        await db.commit()
        return {
            "cand": cand.id, "job": job.id, "stage_def": stage.id,
            "user_id": user.id, "client": client.id,
        }


async def _current_user(uid: int) -> User:
    async with AsyncSessionLocal() as db:
        return await db.get(User, uid)


async def test_custom_hired_stage_maps_to_hire_and_creates_contract() -> None:
    ids = await _seed_job_with_custom_terminal(TerminalType.hired)
    user = await _current_user(ids["user_id"])
    async with AsyncSessionLocal() as db:
        await move_candidate(
            StageMove(candidate_id=ids["cand"], job_id=ids["job"], stage_def_id=ids["stage_def"]),
            current_user=user,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        st = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == ids["cand"],
                CandidateStage.job_id == ids["job"],
            )
        )
        assert st is not None and st.stage == PipelineStage.hired, (
            "custom hired stage did not map to the hire signal (M4-P0.2)"
        )
        draft = await db.scalar(
            select(Contract).where(
                Contract.candidate_id == ids["cand"],
                Contract.job_id == ids["job"],
                Contract.status == ContractStatus.draft,
            )
        )
        assert draft is not None, "auto-draft Contract not created for custom hire"


async def test_custom_rejected_stage_maps_to_rejected() -> None:
    """The 'requires rejection_reason_id' guard only fires when legacy_enum is a
    terminal reject/withdraw — so its firing proves the terminal_type→rejected
    mapping worked for a custom stage."""
    ids = await _seed_job_with_custom_terminal(TerminalType.rejected)
    user = await _current_user(ids["user_id"])
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await move_candidate(
                StageMove(
                    candidate_id=ids["cand"], job_id=ids["job"], stage_def_id=ids["stage_def"]
                ),
                current_user=user,
                db=db,
            )
    assert exc.value.status_code == 422
    assert "rejection_reason_id" in str(exc.value.detail), (
        "custom rejected stage did not map to the reject signal (M4-P0.2)"
    )


async def test_clone_template_copies_scorecard_schema() -> None:
    u = uuid.uuid4().hex[:8]
    rubric = {"criteria": [{"name": "Culture fit", "weight": 3}]}
    async with AsyncSessionLocal() as db:
        admin = User(
            email=f"wfa-{u}@example.com", password_hash=hash_password("x"),
            name="Adm", role=UserRole.admin, is_active=True,
        )
        tpl = PipelineTemplate(name=f"Src {u}")
        db.add_all([admin, tpl])
        await db.flush()
        db.add(
            PipelineStageDef(
                template_id=tpl.id, name=f"Interview-{u}", order=1,
                category=StageCategoryEnum.internal, scorecard_schema=rubric,
            )
        )
        await db.commit()
        tpl_id, admin_id = tpl.id, admin.id

    admin = await _current_user(admin_id)
    async with AsyncSessionLocal() as db:
        await clone_template(tpl_id, current_user=admin, new_name=f"Copy {u}", db=db)

    async with AsyncSessionLocal() as db:
        cloned = await db.scalar(
            select(PipelineTemplate).where(PipelineTemplate.name == f"Copy {u}")
        )
        stages = (
            await db.execute(
                select(PipelineStageDef).where(
                    PipelineStageDef.template_id == cloned.id
                )
            )
        ).scalars().all()
    assert stages and stages[0].scorecard_schema == rubric, (
        "clone_template dropped scorecard_schema (M4-P0.2)"
    )
