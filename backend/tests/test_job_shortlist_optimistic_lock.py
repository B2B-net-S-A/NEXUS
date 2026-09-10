"""Blokada optymistyczna shortlisty jest ATOMOWA — dwa równoległe zapisy.

`PATCH /api/shortlist/{id}` porównywał `version` z wiersza przeczytanego BEZ
blokady. Dwa równoległe zapisy z tą samą wersją oba przechodziły kontrolę
i drugi po cichu nadpisywał pierwszy — dokładnie to, przed czym blokada miała
chronić. Teraz wiersz jest blokowany (`FOR UPDATE`) przed porównaniem, więc
drugi zapis czeka na commit pierwszego i dostaje 409.

Okno wyścigu jest wymuszone: `ensure_job_membership` (woła się między odczytem
a porównaniem wersji) dostaje opóźnienie, więc oba żądania na pewno czytają
wiersz, zanim którekolwiek zapisze.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.api import job_shortlist
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_shortlist import JobShortlistEntry

pytestmark = pytest.mark.asyncio


async def _seed_entry() -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"SLLock Client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"SLLock Job {tag}",
            client_id=client.id,
            status=JobStatus.published,
        )
        candidate = Candidate(
            name="Ola",
            lastname=f"Wyscig-{tag}",
            email=f"sllock-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, candidate])
        await db.flush()
        entry = JobShortlistEntry(job_id=job.id, candidate_id=candidate.id)
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry.id


async def test_two_simultaneous_saves_with_the_same_version_cannot_both_pass(
    app_client, app_auth_headers, monkeypatch
) -> None:
    entry_id = await _seed_entry()
    async with AsyncSessionLocal() as db:
        version = await db.scalar(
            select(JobShortlistEntry.version).where(JobShortlistEntry.id == entry_id)
        )

    original = job_shortlist.ensure_job_membership

    async def slow_membership(db, user, job_id, **kwargs):
        await original(db, user, job_id, **kwargs)
        await asyncio.sleep(0.3)

    monkeypatch.setattr(job_shortlist, "ensure_job_membership", slow_membership)

    async def save(note: str):
        return await app_client.patch(
            f"/api/shortlist/{entry_id}",
            json={"version": version, "note": note},
            headers=app_auth_headers,
        )

    first, second = await asyncio.gather(save("notatka A"), save("notatka B"))

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 409], (first.text, second.text)
    winner = first if first.status_code == 200 else second

    async with AsyncSessionLocal() as db:
        stored = await db.get(JobShortlistEntry, entry_id)
        assert stored.note == winner.json()["note"]
        assert stored.version == version + 1
