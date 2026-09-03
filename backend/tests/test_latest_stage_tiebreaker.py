"""„Bieżący etap pary" ma jedną definicję w całym repo.

Kanoniczny tiebreaker to ``(moved_at DESC, id DESC)``. Dwa moduły liczyły to
przez ``MAX(id)`` z komentarzem „id rośnie wraz z moved_at". Dla importu
z Traffita to nieprawda — `moved_at` przychodzi z zewnątrz i bywa cofnięty,
więc wiersz o najwyższym `id` nie musi być najnowszym zdarzeniem. Zmierzone
na produkcji 2026-09-02: 2 712 par, dla których obie definicje wskazują inny
wiersz, plus 4 699 par z remisem `moved_at`.

Test dowodzi tego na danych, które ODTWARZAJĄ import: wiersz wstawiony PÓŹNIEJ
(wyższe `id`) niesie STARSZY `moved_at`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.models.skill import Skill  # noqa: F401
from sqlalchemy import select

NOW = datetime(2035, 3, 18, 10, 0, tzinfo=timezone.utc)


async def _seed_backdated_pair() -> dict:
    """Para, dla której MAX(id) i (moved_at, id) wskazują RÓŻNE wiersze."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"TieClient-{tag}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        job = Job(
            title=f"TieJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        candidate = Candidate(
            name="Jan",
            lastname=f"Tie-{tag}",
            email=f"tie-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, candidate])
        await db.commit()
        await db.refresh(job)
        await db.refresh(candidate)

        # Ruch WŁASNY: nowszy w czasie, wstawiony jako pierwszy (niższe id).
        current = CandidateStage(
            candidate_id=candidate.id,
            job_id=job.id,
            stage=PipelineStage.cv_sent,
            moved_at=NOW,
        )
        db.add(current)
        await db.commit()
        await db.refresh(current)

        # Import z Traffita: STARSZE zdarzenie dosłane później (wyższe id).
        backdated = CandidateStage(
            candidate_id=candidate.id,
            job_id=job.id,
            stage=PipelineStage.screening,
            moved_at=NOW - timedelta(days=30),
            external_source="traffit",
            external_id=f"tie-{tag}",
        )
        db.add(backdated)
        await db.commit()
        await db.refresh(backdated)

        assert backdated.id > current.id, "Fixture nie odtwarza kształtu importu"
        return {
            "job_id": job.id,
            "candidate_id": candidate.id,
            "current_id": current.id,
            "backdated_id": backdated.id,
        }


async def test_helper_picks_the_newest_event_not_the_newest_row():
    from app.core.database import AsyncSessionLocal
    from app.services.pipeline_latest import latest_stage_ids

    world = await _seed_backdated_pair()

    async with AsyncSessionLocal() as db:
        subquery = latest_stage_ids(job_ids=[world["job_id"]])
        picked = (await db.execute(select(subquery.c.latest_id))).scalars().all()

    assert picked == [world["current_id"]], (
        "Wybrano wiersz o najwyższym id zamiast najnowszego zdarzenia — "
        "dokładnie defekt, który dawał inny etap niż tablica i KPI."
    )


async def test_the_two_definitions_really_disagree_on_this_fixture():
    """Kontrola samego fixture'a: bez rozjazdu test wyżej niczego nie dowodzi."""
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage
    from sqlalchemy import func

    world = await _seed_backdated_pair()

    async with AsyncSessionLocal() as db:
        by_max_id = await db.scalar(
            select(func.max(CandidateStage.id)).where(
                CandidateStage.job_id == world["job_id"]
            )
        )

    assert by_max_id == world["backdated_id"]
    assert by_max_id != world["current_id"]
