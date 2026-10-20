"""„Kandydaci do zamknięcia” — kafelek pulpitu (20.10.2026, `services/closing_candidates.py`).

Kontrakty:

- na liście są tylko pary, których najnowszy wiersz stoi w kolumnie Tablicy
  „Akceptacja i umowa” (zaakceptowany, umowa wysłana, podpisana), z krokiem;
- Head of Recruitment widzi wszystkie opublikowane rekrutacje, Delivery Lead
  swoje, rekruter te, w których jest Rekruterem albo prowadzi kandydata;
  osoba bez tych ról nie widzi nic;
- wiersz niesie klienta, Delivery Leada, rekrutera pary i obie stawki;
  stawkę do klienta trasa ukrywa rolom bez prawa do niej.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.services.closing_candidates import rate_fields, step_of
from app.services.recruitment_rates import RecruitmentRate

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


def test_step_follows_contract_badge() -> None:
    assert step_of("contract_signed") == "signed"
    assert step_of("contract_sent") == "sent"
    assert step_of(None) == "accepted"


def test_rate_fields_hide_client_rate_without_permission() -> None:
    rate = RecruitmentRate(
        candidate_id=1,
        job_id=2,
        client_rate_value=Decimal("150"),
        client_rate_unit="hourly",
        client_rate_currency="PLN",
        candidate_rate_value=Decimal("120"),
        candidate_rate_unit="hourly",
        candidate_rate_currency="PLN",
    )
    hidden = rate_fields(rate, show_client_rate=False)
    assert hidden["client_rate_value"] is None
    assert hidden["candidate_rate_value"] == Decimal("120")
    shown = rate_fields(rate, show_client_rate=True)
    assert shown["client_rate_value"] == Decimal("150")
    assert rate_fields(None, show_client_rate=True) == {}


async def _user(db, role):
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:8]
    user = User(
        email=f"closing-{role}-{marker}@example.com",
        name=f"Closing {role} {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _world(db, *, recruiter_id=None, delivery_lead_id=None):
    from app.models.client import Client
    from app.models.job import Job, JobStatus, RemotePolicy
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )

    marker = uuid.uuid4().hex[:8]
    client = Client(name=f"Closing klient {marker}")
    template = PipelineTemplate(name=f"Closing szablon {marker}")
    db.add_all([client, template])
    await db.flush()
    defs = {}
    for order, (key, name, enum, category) in enumerate(
        [
            ("cv_sent", "CV Wysłane", "cv_sent", StageCategoryEnum.external),
            ("acceptance", "Akceptacja", "acceptance", StageCategoryEnum.external),
            ("sent", "Umowa wysłana", "acceptance", StageCategoryEnum.external),
            ("signed", "Umowa podpisana", "acceptance", StageCategoryEnum.external),
            ("hired", "Zatrudniony", "hired", StageCategoryEnum.external),
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
        title=f"Closing Java {marker}",
        location="Warszawa",
        status=JobStatus.published,
        work_state="finished",
        remote_policy=RemotePolicy.hybrid,
        client_id=client.id,
        pipeline_template_id=template.id,
        recruiter_id=recruiter_id,
        delivery_lead_id=delivery_lead_id,
    )
    db.add(job)
    await db.flush()
    return {
        "client_id": client.id,
        "client_name": client.name,
        "job_id": job.id,
        "template_id": template.id,
        "defs": {k: d.id for k, d in defs.items()},
    }


async def _person_at(db, world, key, *, ago, enum, **extra):
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import CandidateStage

    marker = uuid.uuid4().hex[:8]
    cand = Candidate(
        name="Ewa", lastname=f"Closing{marker}", email=f"c-{marker}@ex.com"
    )
    db.add(cand)
    await db.flush()
    db.add(
        CandidateStage(
            candidate_id=cand.id,
            job_id=world["job_id"],
            stage=enum,
            stage_def_id=world["defs"][key],
            moved_at=datetime.now(timezone.utc) - ago,
            **extra,
        )
    )
    await db.flush()
    return cand.id


async def _cleanup(world_list, candidate_ids, user_ids):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
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
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


def _for_job(rows, job_id):
    return [r for r in rows if r.job_id == job_id]


@needs_db
@pytest.mark.asyncio
async def test_lists_contract_column_with_steps_rates_and_people() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User
    from app.services import closing_candidates

    candidates: list[int] = []
    async with AsyncSessionLocal() as db:
        hor = await _user(db, "head_of_recruitment")
        rec = await _user(db, "recruiter")
        dl = await _user(db, "delivery_lead")
        world = await _world(db, recruiter_id=rec.id, delivery_lead_id=dl.id)
        accepted = await _person_at(
            db,
            world,
            "acceptance",
            enum="acceptance",
            ago=timedelta(days=3),
            client_rate_value=Decimal("150"),
            client_rate_unit="hourly",
            client_rate_currency="PLN",
            expected_rate_value=Decimal("120"),
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        sent = await _person_at(
            db, world, "sent", enum="acceptance", ago=timedelta(days=2)
        )
        signed = await _person_at(
            db, world, "signed", enum="acceptance", ago=timedelta(days=1)
        )
        at_client = await _person_at(
            db, world, "cv_sent", enum="cv_sent", ago=timedelta(days=5)
        )
        hired = await _person_at(
            db, world, "hired", enum="hired", ago=timedelta(days=4)
        )
        candidates += [accepted, sent, signed, at_client, hired]
        await db.commit()
        hor_id, rec_id, dl_id = hor.id, rec.id, dl.id
        rec_name, dl_name = rec.name, dl.name

    try:
        async with AsyncSessionLocal() as db:
            result = await closing_candidates.load(db, await db.get(User, hor_id))
            rows = _for_job(result.rows, world["job_id"])
            # Najdłużej czekający na górze; CV u klienta i Zatrudniony poza listą.
            assert [(r.candidate_id, r.step) for r in rows] == [
                (accepted, "accepted"),
                (sent, "sent"),
                (signed, "signed"),
            ]
            first = rows[0]
            assert first.client_name == world["client_name"]
            assert first.delivery_lead_name == dl_name
            # Bez procesu i weryfikacji rekruter pary = Rekruter rekrutacji.
            assert first.recruiter_name == rec_name
            assert first.rate is not None
            assert first.rate.client_rate_value == Decimal("150")
            assert first.rate.candidate_rate_value == Decimal("120")
            assert rows[1].rate is None
            # Liczniki kroków liczą wszystkich, nie tylko pokazane wiersze.
            assert result.step_counts["accepted"] >= 1
            assert result.step_counts["sent"] >= 1
            assert result.step_counts["signed"] >= 1
    finally:
        await _cleanup([world], candidates, [hor_id, rec_id, dl_id])


@needs_db
@pytest.mark.asyncio
async def test_scope_follows_role() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User
    from app.services import closing_candidates

    candidates: list[int] = []
    async with AsyncSessionLocal() as db:
        rec = await _user(db, "recruiter")
        other_rec = await _user(db, "recruiter")
        dl = await _user(db, "delivery_lead")
        other_dl = await _user(db, "delivery_lead")
        viewer = await _user(db, "user")
        mine = await _world(db, recruiter_id=rec.id, delivery_lead_id=dl.id)
        foreign = await _world(
            db, recruiter_id=other_rec.id, delivery_lead_id=other_dl.id
        )
        candidates.append(
            await _person_at(
                db, mine, "acceptance", enum="acceptance", ago=timedelta(days=1)
            )
        )
        candidates.append(
            await _person_at(
                db, foreign, "acceptance", enum="acceptance", ago=timedelta(days=1)
            )
        )
        await db.commit()
        ids = [rec.id, other_rec.id, dl.id, other_dl.id, viewer.id]

    try:
        async with AsyncSessionLocal() as db:
            for user_id in (ids[0], ids[2]):
                result = await closing_candidates.load(db, await db.get(User, user_id))
                assert _for_job(result.rows, mine["job_id"])
                assert not _for_job(result.rows, foreign["job_id"])
            empty = await closing_candidates.load(db, await db.get(User, ids[4]))
            assert empty.rows == [] and empty.total == 0
            assert empty.step_counts == {"accepted": 0, "sent": 0, "signed": 0}
    finally:
        await _cleanup([mine, foreign], candidates, ids)
