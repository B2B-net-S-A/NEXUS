"""Rekruter prowadzi swoich kandydatów w rekrutacji, do której nie jest przypisany.

Decyzja Artura 07.10.2026: rekruterzy przepinają swoich ludzi do różnych
rekrutacji — także takich, do których nie przypisał ich automat ani Head of
Recruitment. Kontrakty:

- dodanie przez rekrutera spoza zespołu przechodzi (200), a dodający zostaje
  właścicielem procesu — to na nim stoją dzwonki przekazań, follow-up i KPI;
- taka rekrutacja jest w „Moje” listy ``/jobs`` (lista i licznik tym samym
  predykatem), a wiersz niesie liczbę moich kandydatów;
- „Rekruter” rekrutacji się nie zmienia (``jobs_mine_clause`` bez procesów —
  czytają go „Moje następne kroki” i kreator metryk).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql


def _sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_mine_list_scope_includes_my_open_processes_but_team_rule_does_not() -> None:
    from app.api.jobs import jobs_mine_clause, jobs_mine_scope_clause

    user = SimpleNamespace(id=7, roles=["recruiter"], role="recruiter")
    assert "recruitment_processes.owner_user_id" in _sql(jobs_mine_scope_clause(user))
    assert "recruitment_processes" not in _sql(jobs_mine_clause(user))


async def _seed() -> dict:
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token, hash_password
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        lead = User(
            email=f"outside-lead-{tag}@example.com",
            name=f"Lead {tag}",
            role=UserRole.recruiter,
            is_active=True,
        )
        outsider = User(
            email=f"outside-rec-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Out"),
            name=f"Outsider {tag}",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"Outside-{tag}")
        template = PipelineTemplate(name=f"OutsideTpl-{tag}")
        candidate = Candidate(
            name="Ola",
            lastname=f"Outside-{tag}",
            email=f"outside-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([lead, outsider, client, template, candidate])
        await db.flush()
        job = Job(
            title=f"OutsideJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=template.id,
            recruiter_id=lead.id,
        )
        db.add_all(
            [
                job,
                PipelineStageDef(
                    template_id=template.id,
                    name="new",
                    order=0,
                    category=StageCategoryEnum.internal,
                    legacy_enum_value="new",
                    is_terminal=False,
                ),
            ]
        )
        await db.commit()
        return {
            "tag": tag,
            "job_id": job.id,
            "client_id": client.id,
            "template_id": template.id,
            "candidate_id": candidate.id,
            "lead_id": lead.id,
            "outsider_id": outsider.id,
            "headers": {
                "Authorization": "Bearer "
                f"{create_access_token(outsider.id, UserRole.recruiter.value)}"
            },
        }


async def _cleanup(world: dict) -> None:
    """Sprzątanie najlepszym wysiłkiem: dodanie do pipeline'u zapisuje też
    wiersze w tabelach pobocznych (migawka CV, telemetria, kolejki), których
    ten test nie zna. Wspólna baza testowa i tak nie jest czyszczona, a dane
    mają unikalny znacznik — błąd klucza obcego nie może zamaskować wyniku."""
    from sqlalchemy.exc import IntegrityError

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job
    from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.recruitment_process import RecruitmentProcess
    from app.models.user import User

    statements = [
        delete(CandidateStage).where(CandidateStage.job_id == world["job_id"]),
        delete(RecruitmentProcess).where(RecruitmentProcess.job_id == world["job_id"]),
        delete(Job).where(Job.id == world["job_id"]),
        delete(PipelineStageDef).where(
            PipelineStageDef.template_id == world["template_id"]
        ),
        delete(PipelineTemplate).where(PipelineTemplate.id == world["template_id"]),
        delete(Client).where(Client.id == world["client_id"]),
        delete(Candidate).where(Candidate.id == world["candidate_id"]),
        delete(User).where(User.id.in_([world["lead_id"], world["outsider_id"]])),
    ]
    async with AsyncSessionLocal() as db:
        try:
            for statement in statements:
                await db.execute(statement)
            await db.commit()
        except IntegrityError:
            await db.rollback()


@pytest.mark.asyncio
async def test_outsider_adds_own_candidate_owns_it_and_finds_job_in_mine(
    app_client: AsyncClient,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_process import RecruitmentProcess

    world = await _seed()
    headers = world["headers"]
    try:
        before = await app_client.get(
            f"/api/jobs?page_size=50&q={world['tag']}&mine=true&open_only=true",
            headers=headers,
        )
        assert before.status_code == 200, before.text
        assert world["job_id"] not in {row["id"] for row in before.json()["items"]}
        counts_before = (
            await app_client.get("/api/jobs/quick-counts", headers=headers)
        ).json()

        added = await app_client.post(
            f"/api/jobs/{world['job_id']}/proposals/bulk",
            headers=headers,
            json={
                "candidate_ids": [world["candidate_id"]],
                "source": "candidate_list",
            },
        )
        assert added.status_code == 200, added.text
        assert added.json()["total_added"] == 1, added.text

        async with AsyncSessionLocal() as db:
            owner = await db.scalar(
                select(RecruitmentProcess.owner_user_id).where(
                    RecruitmentProcess.job_id == world["job_id"],
                    RecruitmentProcess.candidate_id == world["candidate_id"],
                )
            )
        assert owner == world["outsider_id"]

        after = await app_client.get(
            f"/api/jobs?page_size=50&q={world['tag']}&mine=true&open_only=true",
            headers=headers,
        )
        assert after.status_code == 200, after.text
        rows = {row["id"]: row for row in after.json()["items"]}
        assert world["job_id"] in rows
        row = rows[world["job_id"]]
        assert row["priority_carry_over_count"] == 1
        # Rekruterem rekrutacji nadal jest prowadzący — nie dopisujemy do zespołu.
        assert [person["user_id"] for person in row["recruiters"]] == [world["lead_id"]]

        counts_after = (
            await app_client.get("/api/jobs/quick-counts", headers=headers)
        ).json()
        assert counts_after["mine"] == counts_before["mine"] + 1
    finally:
        await _cleanup(world)
