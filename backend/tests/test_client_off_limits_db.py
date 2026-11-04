"""Off-limits przy dodaniu do rekrutacji — ścieżki z bazą (21.10.2026).

Osoba, która dziś pracuje w firmie z aktywnym zamówieniem, wchodzi do
rekrutacji tylko z potwierdzeniem „sama się zgłosiła” (nagłówek
``X-Off-Limits-Confirmation``); bez niego 409 i żadnej karty. „Nie, to my”
przy partii = osoba wypada, reszta się dodaje.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select


pytestmark = pytest.mark.asyncio


async def _seed() -> dict:
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.core.security import create_access_token
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"offlimits-{tag}@example.com",
            name=f"Rekruter {tag}",
            role=UserRole.recruiter,
            is_active=True,
        )
        guarded = Client(name=f"OffLimits {tag}")
        hiring = Client(name=f"Hiring {tag}")
        template = PipelineTemplate(name=f"OffLimitsTpl-{tag}")
        consultant = Candidate(name="Konsultant", lastname=f"OL-{tag}")
        employed = [
            Candidate(
                name=f"Osoba{i}",
                lastname=f"OL-{tag}",
                email=f"ol-{i}-{tag}@example.com",
                status=CandidateStatus.active,
                linkedin_current_company=f"OffLimits {tag} Sp. z o.o.",
            )
            for i in range(3)
        ]
        free = Candidate(
            name="Wolna",
            lastname=f"OL-{tag}",
            email=f"ol-free-{tag}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=f"Inna firma {tag}",
        )
        db.add_all([user, guarded, hiring, template, consultant, *employed, free])
        await db.flush()
        contract = Contract(
            candidate_id=consultant.id,
            client_id=guarded.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=today - timedelta(days=100),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.flush()
        job = Job(
            title=f"OffLimitsJob-{tag}",
            status=JobStatus.published,
            client_id=hiring.id,
            pipeline_template_id=template.id,
            recruiter_id=user.id,
        )
        db.add_all(
            [
                ClientOrder(
                    client_id=guarded.id,
                    contract_id=contract.id,
                    title=f"OL-{tag}",
                    order_type="periodic",
                    status=ClientOrderStatus.active,
                    start_date=today - timedelta(days=30),
                    end_date=today + timedelta(days=60),
                    rate_client=Decimal("150.000"),
                ),
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
            "job_id": job.id,
            "client_ids": [guarded.id, hiring.id],
            "template_id": template.id,
            "contract_id": contract.id,
            "candidate_ids": [consultant.id, *(c.id for c in employed), free.id],
            "employed": [c.id for c in employed],
            "free": free.id,
            "user_id": user.id,
            "client_name": guarded.name,
            "headers": {
                "Authorization": "Bearer "
                f"{create_access_token(user.id, UserRole.recruiter.value)}"
            },
        }


async def _cleanup(world: dict) -> None:
    """Najlepszym wysiłkiem — dane mają unikalny znacznik (wzór
    ``test_recruiter_outside_team_candidates``)."""
    from sqlalchemy.exc import IntegrityError

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract
    from app.models.job import Job
    from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.recruitment_process import RecruitmentProcess
    from app.models.user import User

    statements = [
        delete(CandidateStage).where(CandidateStage.job_id == world["job_id"]),
        delete(RecruitmentProcess).where(RecruitmentProcess.job_id == world["job_id"]),
        delete(Job).where(Job.id == world["job_id"]),
        delete(ClientOrder).where(ClientOrder.contract_id == world["contract_id"]),
        delete(Contract).where(Contract.id == world["contract_id"]),
        delete(PipelineStageDef).where(
            PipelineStageDef.template_id == world["template_id"]
        ),
        delete(PipelineTemplate).where(PipelineTemplate.id == world["template_id"]),
        delete(Client).where(Client.id.in_(world["client_ids"])),
        delete(Candidate).where(Candidate.id.in_(world["candidate_ids"])),
        delete(User).where(User.id == world["user_id"]),
    ]
    async with AsyncSessionLocal() as db:
        try:
            for statement in statements:
                await db.execute(statement)
            await db.commit()
        except IntegrityError:
            await db.rollback()


async def _process_meta(job_id: int, candidate_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_process import RecruitmentProcess

    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(RecruitmentProcess.id, RecruitmentProcess.entry_meta).where(
                    RecruitmentProcess.job_id == job_id,
                    RecruitmentProcess.candidate_id == candidate_id,
                )
            )
        ).first()


def _confirm(answers: dict[int, str]) -> dict[str, str]:
    return {
        "X-Off-Limits-Confirmation": json.dumps({str(k): v for k, v in answers.items()})
    }


async def test_bulk_add_asks_once_then_keeps_who_confirmed_how(
    app_client: AsyncClient,
) -> None:
    world = await _seed()
    first, second, _ = world["employed"]
    url = f"/api/jobs/{world['job_id']}/proposals/bulk"
    body = {"candidate_ids": [first, second, world["free"]], "source": "candidate_list"}
    try:
        asked = await app_client.post(url, headers=world["headers"], json=body)
        assert asked.status_code == 409, asked.text
        detail = asked.json()["detail"]
        assert detail["code"] == "off_limits_confirmation_required"
        assert {c["candidate_id"] for c in detail["candidates"]} == {first, second}
        assert {c["client_name"] for c in detail["candidates"]} == {
            world["client_name"]
        }
        # Wyjątek = rollback: nawet osoba spoza off-limits nie weszła.
        assert await _process_meta(world["job_id"], world["free"]) is None

        added = await app_client.post(
            url,
            headers={
                **world["headers"],
                **_confirm({first: "linkedin_inbound", second: "skip"}),
            },
            json=body,
        )
        assert added.status_code == 200, added.text
        payload = added.json()
        assert sorted(payload["added"]) == sorted([first, world["free"]])
        assert [(s["candidate_id"], s["reason"]) for s in payload["skipped"]] == [
            (second, "off_limits_declined")
        ]

        row = await _process_meta(world["job_id"], first)
        assert row is not None
        stamp = row.entry_meta["off_limits"]
        assert stamp["how"] == "linkedin_inbound"
        assert stamp["confirmed_by"] == world["user_id"]
        assert stamp["client_name"] == world["client_name"]
        free_row = await _process_meta(world["job_id"], world["free"])
        assert free_row is not None
        assert "off_limits" not in (free_row.entry_meta or {})
    finally:
        await _cleanup(world)


async def test_move_of_a_new_person_needs_the_same_confirmation(
    app_client: AsyncClient,
) -> None:
    world = await _seed()
    person = world["employed"][2]
    body = {"candidate_id": person, "job_id": world["job_id"], "stage": "new"}
    try:
        asked = await app_client.post(
            "/api/pipeline/move", headers=world["headers"], json=body
        )
        assert asked.status_code == 409, asked.text
        assert asked.json()["detail"]["code"] == "off_limits_confirmation_required"
        assert await _process_meta(world["job_id"], person) is None

        moved = await app_client.post(
            "/api/pipeline/move",
            headers={**world["headers"], **_confirm({person: "left_company"})},
            json=body,
        )
        assert moved.status_code == 200, moved.text
        row = await _process_meta(world["job_id"], person)
        assert row is not None
        assert row.entry_meta["off_limits"]["how"] == "left_company"
    finally:
        await _cleanup(world)


async def test_shared_linkedin_assignment_requires_off_limits_confirmation() -> None:
    """The helper used by the supported extension cannot bypass off-limits."""
    from app.api.candidates import _assign_candidate_to_job
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import PipelineStage
    from app.services import client_off_limits

    world = await _seed()
    person = world["employed"][0]
    try:
        async with AsyncSessionLocal() as db:
            with pytest.raises(client_off_limits.OffLimitsConfirmationRequired):
                await _assign_candidate_to_job(
                    db=db,
                    candidate_id=person,
                    job_id=world["job_id"],
                    stage=PipelineStage.new,
                    user_id=world["user_id"],
                )
            await db.rollback()
        assert await _process_meta(world["job_id"], person) is None
    finally:
        await _cleanup(world)
