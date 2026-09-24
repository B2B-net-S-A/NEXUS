"""Cztery kategorie kompetencji (0371): przepięcie ``data_ai`` i security z QA.

Każdy test działa w JEDNEJ transakcji wycofywanej na końcu — przepięcie
dotyka wszystkich wierszy wspólnej bazy testowej, a cofnięcie zostawia ją
nietkniętą. Asercje czytają wyłącznie wiersze założone przez test.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select, text

from app.services.competence_category_four import (
    CATEGORIES,
    _remap_statements,
    sync_statements,
)

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


async def _cc_id(db, slug: str) -> int:
    from app.models.competence_category import CompetenceCategory

    return await db.scalar(
        select(CompetenceCategory.id).where(CompetenceCategory.slug == slug)
    )


async def _user(db):
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"cc4-{marker}@example.com",
        name=f"CC4 {marker}",
        role=UserRole.recruiter,
        roles=["recruiter"],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _job(db, title: str, cc_id: int | None):
    from app.models.client import Client
    from app.models.job import Job

    client = Client(name=f"cc4-client-{uuid.uuid4().hex[:8]}")
    db.add(client)
    await db.flush()
    job = Job(title=title, client_id=client.id, competence_category_id=cc_id)
    db.add(job)
    await db.flush()
    return job


@pytest.mark.unit
def test_four_active_categories_and_data_ai_retired() -> None:
    assert [c["slug"] for c in CATEGORIES] == [
        "infrastructure_operations",
        "software_development",
        "security_quality",
        "management_delivery",
    ]
    retire = [
        sql for sql, params in sync_statements() if params.get("slug") == "data_ai"
    ]
    assert retire and "is_active = false" in retire[0]


@needs_db
@pytest.mark.asyncio
async def test_data_ai_rows_move_to_infra_and_primary_is_kept() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.competence_category import (
        CandidateCompetenceCategory,
        UserCompetenceCategory,
    )

    async with AsyncSessionLocal() as db:
        try:
            data_ai = await _cc_id(db, "data_ai")
            infra = await _cc_id(db, "infrastructure_operations")
            assert data_ai and infra

            cand = Candidate(name="Cc", lastname=f"Four{uuid.uuid4().hex[:8]}")
            db.add(cand)
            await db.flush()
            db.add_all(
                [
                    CandidateCompetenceCategory(
                        candidate_id=cand.id,
                        competence_category_id=data_ai,
                        is_primary=True,
                        confidence_score=0.9,
                    ),
                    CandidateCompetenceCategory(
                        candidate_id=cand.id,
                        competence_category_id=infra,
                        is_primary=False,
                        confidence_score=0.6,
                    ),
                ]
            )
            person = await _user(db)
            db.add_all(
                [
                    UserCompetenceCategory(
                        user_id=person.id,
                        competence_category_id=data_ai,
                        priority=1,
                        is_primary=True,
                    ),
                    UserCompetenceCategory(
                        user_id=person.id,
                        competence_category_id=infra,
                        priority=2,
                        is_primary=False,
                    ),
                ]
            )
            job = await _job(db, "Data Engineer", data_ai)
            await db.flush()

            for statement in _remap_statements():
                await db.execute(text(statement))
            db.expire_all()

            cand_rows = (
                await db.execute(
                    select(
                        CandidateCompetenceCategory.competence_category_id,
                        CandidateCompetenceCategory.is_primary,
                    ).where(CandidateCompetenceCategory.candidate_id == cand.id)
                )
            ).all()
            assert cand_rows == [(infra, True)]

            user_rows = (
                await db.execute(
                    select(
                        UserCompetenceCategory.competence_category_id,
                        UserCompetenceCategory.priority,
                    ).where(UserCompetenceCategory.user_id == person.id)
                )
            ).all()
            assert user_rows == [(infra, 1)]

            refreshed = await db.execute(
                text("SELECT competence_category_id FROM jobs WHERE id = :id"),
                {"id": job.id},
            )
            assert refreshed.scalar() == infra
        finally:
            await db.rollback()


@needs_db
@pytest.mark.asyncio
async def test_security_jobs_leave_qa_but_testers_stay() -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            qa = await _cc_id(db, "security_quality")
            infra = await _cc_id(db, "infrastructure_operations")
            security = await _job(db, "Security Engineer (SOC)", qa)
            pentester = await _job(db, "Pentester (blue+red)", qa)
            tester = await _job(db, "Security Tester", qa)
            manual = await _job(db, "Tester manualny", qa)
            await db.flush()

            for statement in _remap_statements():
                await db.execute(text(statement))

            rows = dict(
                (
                    await db.execute(
                        text(
                            "SELECT id, competence_category_id FROM jobs "
                            "WHERE id = ANY(:ids)"
                        ),
                        {"ids": [security.id, pentester.id, tester.id, manual.id]},
                    )
                ).all()
            )
            assert rows[security.id] == infra
            assert rows[pentester.id] == infra
            assert rows[tester.id] == qa
            assert rows[manual.id] == qa
        finally:
            await db.rollback()
