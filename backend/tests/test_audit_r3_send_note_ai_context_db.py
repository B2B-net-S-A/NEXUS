"""Decyzja C w czytnikach AI notatek kandydata — z bazą (audyt r3, 24.11.2026).

Wymaga Postgresa (CI). Delivery Lead przesuwa kartę na „CV wysłane” i minutę
później pisze „Wysłany 150/100-110” (cena dla klienta / stawka osoby):

* nocny odczyt faktów (``load_note_rows``, ten sam wybór zasila
  ``notes_profile_backfill``) nie bierze tej notatki, a pełny limit notatek
  wypełniają inne — filtr przed limitem;
* notatki Luny przy przepięciu screeningu (``_job_scoped_notes``) nie niosą jej
  rekruterowi, Delivery Lead dostaje ją jak dotąd.

Wariant bez bazy: ``test_audit_r3_send_note_ai_context.py``. Treści fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from tests.test_recruitment_rate_hints_db import SEND_NOTE, _user

TALK = "Rozmowa: Kafka od 4 lat, projekt w banku."


async def _seed(*, dl_id: int, recruiter_id: int, extra_talks: int = 0) -> dict:
    """Para po „CV wysłane” przez DL-a; notatka z wysyłki jest najnowsza."""
    unique = uuid.uuid4().hex[:8]
    sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R3 klient {unique}")
        db.add(client)
        await db.flush()
        job = Job(title=f"R3 {unique}", client_id=client.id, status=JobStatus.published)
        candidate = Candidate(
            name="Tomasz", lastname=f"R3{unique}", email=f"r3-{unique}@example.com"
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.cv_sent,
                moved_at=sent_at,
                moved_by=dl_id,
            )
        )
        for index in range(1 + extra_talks):
            db.add(
                Note(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    author_id=recruiter_id,
                    content=f"{TALK} ({index})",
                    source_created_at=sent_at - timedelta(hours=2 + index),
                )
            )
        await db.commit()
        world = {"candidate": candidate.id, "job": job.id}
    async with AsyncSessionLocal() as db:
        send = Note(
            candidate_id=world["candidate"],
            job_id=world["job"],
            author_id=dl_id,
            content=SEND_NOTE,
            source_created_at=sent_at + timedelta(minutes=1),
        )
        db.add(send)
        await db.commit()
        world["send"] = send.id
    return world


async def test_facts_reader_skips_the_send_note_and_fills_the_limit():
    from app.services.notes_insights_extractor import NOTES_LIMIT, load_note_rows

    dl_id, _, _ = await _user(UserRole.delivery_lead)
    recruiter_id, _, _ = await _user(UserRole.recruiter)
    world = await _seed(dl_id=dl_id, recruiter_id=recruiter_id, extra_talks=NOTES_LIMIT)

    async with AsyncSessionLocal() as db:
        rows = await load_note_rows(db, world["candidate"])

    ids = [row[0] for row in rows]
    assert world["send"] not in ids
    assert all("150/100-110" not in (row[3] or "") for row in rows)
    # Notatka z wysyłki nie zajmuje miejsca w limicie.
    assert len(rows) == NOTES_LIMIT


async def test_reassign_notes_hide_the_send_note_from_the_recruiter_only():
    from app.services.screening_reassign import _job_scoped_notes

    dl_id, _, _ = await _user(UserRole.delivery_lead)
    recruiter_id, _, _ = await _user(UserRole.recruiter)
    world = await _seed(dl_id=dl_id, recruiter_id=recruiter_id)
    jobs = (world["job"], world["job"])

    async with AsyncSessionLocal() as db:
        recruiter = await db.get(User, recruiter_id)
        lead = await db.get(User, dl_id)
        for_recruiter = await _job_scoped_notes(
            db, candidate_id=world["candidate"], job_ids=jobs, user=recruiter
        )
        for_lead = await _job_scoped_notes(
            db, candidate_id=world["candidate"], job_ids=jobs, user=lead
        )

    assert "150/100-110" not in for_recruiter
    assert "Kafka od 4 lat" in for_recruiter
    assert SEND_NOTE in for_lead
    assert "Kafka od 4 lat" in for_lead
