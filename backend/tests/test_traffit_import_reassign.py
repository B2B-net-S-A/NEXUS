"""Audyt 22.09 r2 (REC-01): przepięcia podobnych rekrutacji z importu.

Przepięcie (propozycja `reassign` w połączonej rekrutacji) odpalał wyłącznie
ruch zrobiony w NEXUSIE, a import Traffita to 99,6% ruchów. Teraz etapy „u
klienta" WSTAWIONE przez import z ostatnich 7 dni też przepinają osobę.
Prawdziwy Postgres; każdy test zakłada własne dane.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_proposal import JobProposal
from app.services import job_similarity as sim
from app.services.traffit.stage_side_effects import apply_imported_stage_side_effects


async def _world() -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Reassign import {tag}")
        db.add(client)
        await db.flush()
        a = Job(title=f"Kotlin A {tag}", client_id=client.id, status=JobStatus.closed)
        b = Job(
            title=f"Kotlin B {tag}", client_id=client.id, status=JobStatus.published
        )
        person = Candidate(
            name="Import", lastname=f"Reassign-{tag}", email=f"ri-{tag}@example.com"
        )
        db.add_all([a, b, person])
        await db.commit()
        await sim.link_jobs(db, b.id, [a.id], user_id=None)
        await db.commit()
        return {"a": a.id, "b": b.id, "person": person.id}


async def _reassigned(job_id: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(JobProposal.candidate_id).where(
                JobProposal.job_id == job_id, JobProposal.source == "reassign"
            )
        )
        return set(rows.scalars())


def _row(world, *, days_ago: float, stage: str = "cv_sent") -> dict:
    return {
        "candidate_id": world["person"],
        "job_id": world["a"],
        "stage_legacy_enum": stage,
        "moved_at": datetime.now(timezone.utc) - timedelta(days=days_ago),
    }


@pytest.fixture
def _flags(monkeypatch):
    monkeypatch.setattr(settings, "TRAFFIT_IMPORT_SIDE_EFFECTS_ENABLED", False)
    monkeypatch.setattr(settings, "TRAFFIT_IMPORT_REASSIGN_ENABLED", True)
    monkeypatch.setattr(settings, "TRAFFIT_IMPORT_REASSIGN_WINDOW_DAYS", 7)


@pytest.mark.asyncio
async def test_recent_imported_cv_sent_is_reassigned_to_the_linked_job(_flags):
    world = await _world()
    row = _row(world, days_ago=1)
    async with AsyncSessionLocal() as db:
        applied = await apply_imported_stage_side_effects(
            db, rows=[row], inserted_rows=[row]
        )
    assert applied["reassigned"] == 1
    assert world["person"] in await _reassigned(world["b"])


@pytest.mark.asyncio
async def test_old_or_updated_or_non_client_stage_is_not_reassigned(_flags):
    world = await _world()
    old = _row(world, days_ago=30)
    screening = _row(world, days_ago=1, stage="screening")
    fresh = _row(world, days_ago=1)
    async with AsyncSessionLocal() as db:
        applied_old = await apply_imported_stage_side_effects(
            db, rows=[old, screening], inserted_rows=[old, screening]
        )
        # Wiersz zaktualizowany (nie wstawiony) to nie nowe wysłanie.
        applied_updated = await apply_imported_stage_side_effects(
            db, rows=[fresh], inserted_rows=[]
        )
    assert applied_old["reassigned"] == 0
    assert applied_updated["reassigned"] == 0
    assert await _reassigned(world["b"]) == set()


@pytest.mark.asyncio
async def test_reassign_flag_off_keeps_the_import_silent(_flags, monkeypatch):
    monkeypatch.setattr(settings, "TRAFFIT_IMPORT_REASSIGN_ENABLED", False)
    world = await _world()
    row = _row(world, days_ago=1)
    async with AsyncSessionLocal() as db:
        applied = await apply_imported_stage_side_effects(
            db, rows=[row], inserted_rows=[row]
        )
    assert applied["reassigned"] == 0
    assert await _reassigned(world["b"]) == set()


# ── Runda 7 audytu (N2-2, N2-4) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_person_hired_in_the_source_is_not_reassigned(_flags):
    """N2-2: „Akceptacja” i „Zatrudniony” w jednym wsadzie — osoba pracuje."""
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    world = await _world()
    acceptance = _row(world, days_ago=1, stage="acceptance")
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["person"],
                job_id=world["a"],
                stage=PipelineStage.hired,
                moved_at=datetime.now(timezone.utc) - timedelta(hours=12),
            )
        )
        await db.commit()
        applied = await apply_imported_stage_side_effects(
            db, rows=[acceptance], inserted_rows=[acceptance]
        )
    assert applied["reassigned"] == 0
    assert await _reassigned(world["b"]) == set()


@pytest.mark.asyncio
async def test_finished_request_does_not_receive_import_reassigns(_flags):
    """N2-4: „Zakończony” request jest nadal `published`, ale nie jest w pracy."""
    world = await _world()
    async with AsyncSessionLocal() as db:
        target = await db.get(Job, world["b"])
        target.work_state = "finished"
        await db.commit()
    row = _row(world, days_ago=1)
    async with AsyncSessionLocal() as db:
        applied = await apply_imported_stage_side_effects(
            db, rows=[row], inserted_rows=[row]
        )
    assert applied["reassigned"] == 0
    assert await _reassigned(world["b"]) == set()
