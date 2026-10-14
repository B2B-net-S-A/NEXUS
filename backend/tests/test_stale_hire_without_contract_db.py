"""„Zatrudniony” bez żadnej umowy u klienta po 12 miesiącach — zapytania na
prawdziwym schemacie (decyzja Artura 14.10.2026). Część czysta:
``test_stale_hire_without_contract.py``."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.scheduling import business_today


async def _seed() -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"StaleHire-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"StaleHire-{tag}", status=JobStatus.closed, client_id=client.id
        )
        db.add(job)
        await db.flush()
        people = {}
        for label, days_ago in (("old", 730), ("fresh", 30)):
            person = Candidate(
                name=label,
                lastname=f"StaleHire-{tag}",
                email=f"stale-{label}-{tag}@example.com",
            )
            db.add(person)
            await db.flush()
            db.add(
                CandidateStage(
                    candidate_id=person.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=now - timedelta(days=days_ago),
                )
            )
            people[label] = person.id
        await db.commit()
        return {**people, "client": client.id}


async def test_old_hire_without_a_contract_is_not_working_with_us() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.employment_marker import (
        current_hired_signal_exists,
        load_employment_markers,
    )

    world = await _seed()
    ids = [world["old"], world["fresh"]]
    async with AsyncSessionLocal() as db:
        markers = await load_employment_markers(db, ids, today=business_today())
        found = await db.execute(
            select(Candidate.id).where(
                Candidate.id.in_(ids), current_hired_signal_exists(Candidate.id)
            )
        )

    assert markers[world["old"]] is None
    fresh = markers[world["fresh"]]
    assert (fresh.source, fresh.phase) == ("pipeline", "working")
    assert fresh.clients[0].client_id == world["client"]
    # Ten sam warunek dla filtra listy (`employment=at_client`).
    assert set(found.scalars().all()) == {world["fresh"]}
