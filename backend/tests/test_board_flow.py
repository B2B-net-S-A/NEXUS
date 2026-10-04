"""„Twój ruch” na pulpicie — cały przepływ (04.10.2026, `services/board_flow.py`).

Przegląd z 04.10.2026: panel „Czeka na Ciebie” u rekruterów, TCM i Delivery
Leadów nie miał żadnego zadania, choć w Ogłoszeniach czekało ponad tysiąc osób.
Kontrakty:

- Ogłoszenia: jedna linia na rekrutację, w której osoba jest Rekruterem; TCM
  widzi też rekrutacje swojej kategorii; obcy rekruter nie widzi nic;
- Nowi z blokadą tej osoby, Screening z brakami, Zweryfikowany ze stanem QC;
- Delivery Lead: CV u klienta ponad 7 dni i niepodpisane umowy z portfela;
- Finanse tylko dla roli Finanse; admin nie dostaje żadnej z tych sekcji;
- awaria jednej sekcji nie zabiera pozostałych.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


async def _user(db, role, *, extra_roles: tuple[str, ...] = ()):
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:8]
    roles = [role, *extra_roles]
    user = User(
        email=f"flow-{role}-{marker}@example.com",
        name=f"Flow {role} {marker}",
        role=UserRole(role),
        roles=roles,
        is_active=True,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _world(db, *, recruiter_id=None, delivery_lead_id=None, category_id=None):
    from app.models.client import Client
    from app.models.job import Job, JobStatus, RemotePolicy
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )

    marker = uuid.uuid4().hex[:8]
    client = Client(name=f"Flow klient {marker}")
    template = PipelineTemplate(name=f"Flow szablon {marker}")
    db.add_all([client, template])
    await db.flush()
    defs = {}
    for order, (key, name, enum, category) in enumerate(
        [
            ("posting", "Ogłoszenia", "posting", StageCategoryEnum.internal),
            ("new", "Nowi", "new", StageCategoryEnum.internal),
            ("screening", "Screening", "screening", StageCategoryEnum.internal),
            ("verified", "Zweryfikowany", "verified", StageCategoryEnum.internal),
            ("cv_sent", "CV Wysłane", "cv_sent", StageCategoryEnum.external),
        ]
    ):
        d = PipelineStageDef(
            template_id=template.id,
            name=name,
            order=order,
            category=category,
            legacy_enum_value=enum,
        )
        db.add(d)
        defs[key] = d
    await db.flush()
    job = Job(
        title=f"Flow Java {marker}",
        location="Warszawa",
        status=JobStatus.published,
        work_state="searching",
        remote_policy=RemotePolicy.hybrid,
        client_id=client.id,
        pipeline_template_id=template.id,
        recruiter_id=recruiter_id,
        delivery_lead_id=delivery_lead_id,
        competence_category_id=category_id,
    )
    db.add(job)
    await db.flush()
    return {
        "client_id": client.id,
        "job_id": job.id,
        "template_id": template.id,
        "defs": {k: d.id for k, d in defs.items()},
        "marker": marker,
    }


async def _person_at(db, world, key, *, ago, stage=None, **extra):
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import CandidateStage

    marker = uuid.uuid4().hex[:8]
    cand = Candidate(name="Anna", lastname=f"Flow{marker}", email=f"f-{marker}@ex.com")
    db.add(cand)
    await db.flush()
    db.add(
        CandidateStage(
            candidate_id=cand.id,
            job_id=world["job_id"],
            stage=stage or key,
            stage_def_id=world["defs"][key],
            moved_at=datetime.now(timezone.utc) - ago,
            **extra,
        )
    )
    await db.flush()
    return cand.id


async def _cleanup(world_list, candidate_ids, user_ids):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.competence_category import UserCompetenceCategory
    from app.models.job import Job
    from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.recruitment_process import RecruitmentProcess
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        job_ids = [w["job_id"] for w in world_list]
        await db.execute(
            delete(RecruitmentProcess).where(RecruitmentProcess.job_id.in_(job_ids))
        )
        await db.execute(
            delete(CandidateStage).where(CandidateStage.job_id.in_(job_ids))
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.execute(
            delete(B2BGeneratedContract).where(
                B2BGeneratedContract.client_id.in_([w["client_id"] for w in world_list])
            )
        )
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        for w in world_list:
            await db.execute(
                delete(PipelineStageDef).where(
                    PipelineStageDef.template_id == w["template_id"]
                )
            )
            await db.execute(
                delete(PipelineTemplate).where(PipelineTemplate.id == w["template_id"])
            )
            await db.execute(delete(Client).where(Client.id == w["client_id"]))
        await db.execute(
            delete(UserCompetenceCategory).where(
                UserCompetenceCategory.user_id.in_(user_ids)
            )
        )
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


def _for_job(rows, job_id):
    return [r for r in rows if r.job_id == job_id]


@needs_db
@pytest.mark.asyncio
async def test_recruiter_sees_postings_claims_screening_and_verified() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
    from app.services import board_flow

    candidates: list[int] = []
    async with AsyncSessionLocal() as db:
        rec = await _user(db, "recruiter")
        other = await _user(db, "recruiter")
        world = await _world(db, recruiter_id=rec.id)
        old = await _person_at(db, world, "posting", ago=timedelta(days=4))
        fresh = await _person_at(db, world, "posting", ago=timedelta(hours=3))
        screening = await _person_at(db, world, "screening", ago=timedelta(hours=5))
        verified = await _person_at(db, world, "verified", ago=timedelta(days=1))
        claimed = await _person_at(db, world, "new", ago=timedelta(minutes=30))
        candidates += [old, fresh, screening, verified, claimed]
        db.add(
            RecruitmentProcess(
                candidate_id=claimed,
                job_id=world["job_id"],
                status=ProcessStatus.open,
                claimed_by_user_id=rec.id,
                claimed_until=datetime.now(timezone.utc) + timedelta(hours=10),
            )
        )
        await db.commit()
        rec_id, other_id = rec.id, other.id

    try:
        async with AsyncSessionLocal() as db:
            from app.models.user import User

            rec = await db.get(User, rec_id)
            flow = await board_flow.load_flow(db, rec)
            assert flow is not None and flow.applies
            postings = _for_job(flow.postings, world["job_id"])
            assert [(p.count) for p in postings] == [2]
            assert postings[0].oldest_at < datetime.now(timezone.utc) - timedelta(
                days=3
            )
            assert [
                r.candidate_id for r in _for_job(flow.claimed, world["job_id"])
            ] == [claimed]
            screen = _for_job(flow.screening, world["job_id"])
            assert [r.candidate_id for r in screen] == [screening]
            # Bez arkusza i bez stawki — oba braki nazwane.
            assert set(screen[0].missing) == {"sheet", "rate"}
            ver = _for_job(flow.verified, world["job_id"])
            assert [r.candidate_id for r in ver] == [verified]
            assert ver[0].qc_status == "unchecked"

            stranger = await db.get(User, other_id)
            other_flow = await board_flow.load_flow(db, stranger)
            assert other_flow is not None
            assert _for_job(other_flow.postings, world["job_id"]) == []
            assert _for_job(other_flow.screening, world["job_id"]) == []
    finally:
        await _cleanup([world], candidates, [rec_id, other_id])


@needs_db
@pytest.mark.asyncio
async def test_tcm_sees_postings_of_their_category_only() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.competence_category import (
        CompetenceCategory,
        UserCompetenceCategory,
    )
    from app.models.user import User
    from app.services import board_flow

    candidates: list[int] = []
    async with AsyncSessionLocal() as db:
        category_id = await db.scalar(
            select(CompetenceCategory.id)
            .where(CompetenceCategory.is_active.is_(True))
            .order_by(CompetenceCategory.id)
        )
        if category_id is None:
            pytest.skip("brak kategorii kompetencji w bazie testowej")
        tcm = await _user(db, "talent_community_manager")
        rec = await _user(db, "recruiter")
        db.add(
            UserCompetenceCategory(
                user_id=tcm.id,
                competence_category_id=category_id,
                is_primary=True,
                priority=1,
            )
        )
        world = await _world(db, recruiter_id=rec.id, category_id=category_id)
        candidates.append(await _person_at(db, world, "posting", ago=timedelta(days=1)))
        await db.commit()
        tcm_id, rec_id = tcm.id, rec.id

    try:
        async with AsyncSessionLocal() as db:
            flow = await board_flow.load_flow(db, await db.get(User, tcm_id))
            assert flow is not None
            assert [p.count for p in _for_job(flow.postings, world["job_id"])] == [1]
    finally:
        await _cleanup([world], candidates, [tcm_id, rec_id])


@needs_db
@pytest.mark.asyncio
async def test_delivery_lead_sees_waiting_client_and_unsigned_contracts() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.user import User
    from app.services import board_flow

    candidates: list[int] = []
    async with AsyncSessionLocal() as db:
        dl = await _user(db, "delivery_lead")
        world = await _world(db, delivery_lead_id=dl.id)
        waiting = await _person_at(db, world, "cv_sent", ago=timedelta(days=9))
        recent = await _person_at(db, world, "cv_sent", ago=timedelta(days=2))
        candidates += [waiting, recent]
        db.add(
            B2BGeneratedContract(
                contract_number=f"FLOW-{world['marker']}",
                partner_name="Partner Flow",
                client_id=world["client_id"],
                created_by=dl.id,
                contract_status="in_progress",
                signature_status="unsigned",
                source="generator",
                created_at=datetime.now(timezone.utc) - timedelta(days=5),
            )
        )
        # Wiersz z Excela działu jest tylko do odczytu — nie jest zaległym podpisem.
        db.add(
            B2BGeneratedContract(
                contract_number=f"XLS-{world['marker']}",
                partner_name="Partner Excel",
                client_id=world["client_id"],
                created_by=dl.id,
                contract_status="in_progress",
                signature_status="unsigned",
                source="excel",
                source_key=f"flow-{world['marker']}",
                created_at=datetime.now(timezone.utc) - timedelta(days=5),
            )
        )
        await db.commit()
        dl_id = dl.id

    try:
        async with AsyncSessionLocal() as db:
            flow = await board_flow.load_flow(db, await db.get(User, dl_id))
            assert flow is not None and flow.applies
            assert [
                r.candidate_id for r in _for_job(flow.waiting_client, world["job_id"])
            ] == [waiting]
            assert [c.contract_number for c in flow.unsigned_contracts] == [
                f"FLOW-{world['marker']}"
            ]
            # DL bez roli rekrutera nie dostaje sekcji rekrutera.
            assert flow.postings == [] and flow.screening == []
    finally:
        await _cleanup([world], candidates, [dl_id])


@needs_db
@pytest.mark.asyncio
async def test_finance_block_only_for_the_finance_role() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User
    from app.services import board_flow

    async with AsyncSessionLocal() as db:
        fin = await _user(db, "finance")
        admin = await _user(db, "admin")
        rec = await _user(db, "recruiter")
        await db.commit()
        ids = (fin.id, admin.id, rec.id)

    try:
        async with AsyncSessionLocal() as db:
            fin, admin, rec = [await db.get(User, i) for i in ids]
            block = await board_flow.load_finance(db, fin)
            assert block is not None
            assert block.gaps_open >= 0 and block.pdfs_new >= 0
            assert await board_flow.load_finance(db, admin) is None
            assert await board_flow.load_finance(db, rec) is None
            # Admin nie rekrutuje i nie prowadzi klientów z nazwy — bez sekcji.
            assert await board_flow.load_flow(db, admin) is None
    finally:
        await _cleanup([], [], list(ids))


@needs_db
@pytest.mark.asyncio
async def test_a_failing_section_does_not_take_the_others(monkeypatch) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
    from app.models.user import User
    from app.services import board_flow

    candidates: list[int] = []
    async with AsyncSessionLocal() as db:
        rec = await _user(db, "recruiter")
        world = await _world(db, recruiter_id=rec.id)
        claimed = await _person_at(db, world, "new", ago=timedelta(minutes=10))
        candidates.append(claimed)
        db.add(
            RecruitmentProcess(
                candidate_id=claimed,
                job_id=world["job_id"],
                status=ProcessStatus.open,
                claimed_by_user_id=rec.id,
                claimed_until=datetime.now(timezone.utc) + timedelta(hours=2),
            )
        )
        await db.commit()
        rec_id = rec.id

    def boom(*_args, **_kwargs):
        raise RuntimeError("awaria testowa")

    monkeypatch.setattr(board_flow, "_postings", boom)
    try:
        async with AsyncSessionLocal() as db:
            flow = await board_flow.load_flow(db, await db.get(User, rec_id))
            assert flow is not None
            assert flow.postings == []
            assert [
                r.candidate_id for r in _for_job(flow.claimed, world["job_id"])
            ] == [claimed]
    finally:
        await _cleanup([world], candidates, [rec_id])


@needs_db
@pytest.mark.asyncio
async def test_board_tasks_endpoint_carries_flow_and_hides_transit_for_finance(
    app_client,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token

    async with AsyncSessionLocal() as db:
        fin = await _user(db, "finance")
        rec = await _user(db, "recruiter")
        await db.commit()
        ids = (fin.id, rec.id)

    try:
        fin_resp = await app_client.get(
            "/api/board-tasks",
            headers={
                "Authorization": f"Bearer {create_access_token(ids[0], 'finance')}"
            },
        )
        rec_resp = await app_client.get(
            "/api/board-tasks",
            headers={
                "Authorization": f"Bearer {create_access_token(ids[1], 'recruiter')}"
            },
        )
        assert rec_resp.status_code == 200, rec_resp.text
        assert rec_resp.json()["flow"]["applies"] is True
        assert rec_resp.json()["finance"] is None
        if fin_resp.status_code == 200:
            body = fin_resp.json()
            assert body["cv_in_transit"] is None
            assert body["flow"] is None
            assert body["finance"] is not None
    finally:
        await _cleanup([], [], list(ids))


def test_unsigned_contracts_already_in_agreements_are_not_repeated() -> None:
    """Umowa z grupy „Umowy” nie stoi drugi raz w „Umowy B2B czekają na podpis”."""
    from types import SimpleNamespace

    from app.api.board_tasks import _agreement_ids, _flow_block
    from app.services import board_flow

    now = datetime.now(timezone.utc)
    flow = board_flow.FlowBlock(
        unsigned_contracts=[
            board_flow.ContractRow(1, "1/2026", None, None, now),
            board_flow.ContractRow(2, "2/2026", None, None, now),
        ]
    )
    agreements = SimpleNamespace(
        to_confirm=[SimpleNamespace(generated_id=1)], to_close=[], waiting_on_others=[]
    )
    out = _flow_block(flow, skip_contract_ids=_agreement_ids(agreements))
    assert [c.id for c in out.unsigned_contracts] == [2]
    assert _agreement_ids(None) == frozenset()
