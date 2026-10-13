"""„Ostatnia rekrutacja” w oknie dodawania — tytuł dla rekrutera (audyt 48 h).

Reguła „Trzy nazwy rekrutacji”: ekrany wewnętrzne pokazują
`working_title ?? title` (SQL `job_display_title_expr`). Okno „Dodaj
kandydatów do pipeline” pokazywało przy osobie samą nazwę od klienta.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services.candidate_job_cards import latest_cards


class _Db:
    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(all=lambda: [])


@pytest.mark.asyncio
async def test_card_query_reads_the_title_for_recruiters() -> None:
    db = _Db()
    await latest_cards(db, candidate_ids=[1], exclude_job_id=2)
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "coalesce(jobs.working_title, jobs.title)" in sql


# ── Z bazą (CI) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_last_recruitment_shows_working_title_then_client_title() -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    token = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Ostatnia-{token}")
        db.add(client)
        await db.flush()
        named = Job(
            title=f"ZOB-1234 Analityk {token}",
            working_title=f"Analityk biznesowy · BPMN {token}",
            working_title_auto=False,
            status=JobStatus.published,
            client_id=client.id,
        )
        plain = Job(
            title=f"Tester {token}", status=JobStatus.published, client_id=client.id
        )
        people = [
            Candidate(
                name="Ostatnia", lastname=f"{token}{i}", email=f"{token}{i}@example.com"
            )
            for i in range(2)
        ]
        db.add_all([named, plain, *people])
        await db.flush()
        at = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
        db.add_all(
            [
                CandidateStage(
                    candidate_id=people[0].id,
                    job_id=named.id,
                    stage=PipelineStage.screening,
                    moved_at=at,
                ),
                CandidateStage(
                    candidate_id=people[1].id,
                    job_id=plain.id,
                    stage=PipelineStage.screening,
                    moved_at=at,
                ),
            ]
        )
        await db.commit()
        ids = [p.id for p in people]
        job_ids = [named.id, plain.id]
        client_id = client.id
    try:
        async with AsyncSessionLocal() as db:
            cards = await latest_cards(db, candidate_ids=ids)
        assert cards[ids[0]].job_title == f"Analityk biznesowy · BPMN {token}"
        assert cards[ids[1]].job_title == f"Tester {token}"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.candidate_id.in_(ids))
            )
            await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
            await db.execute(delete(Job).where(Job.id.in_(job_ids)))
            await db.execute(delete(Client).where(Client.id == client_id))
            await db.commit()
