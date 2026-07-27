"""Atomic dedup for Fireflies meeting-note imports.

`services/fireflies_sync.py` deduped transcripts with a non-atomic
SELECT-then-INSERT on the non-unique `notes.source_ref` (`fireflies:<id>`), so
two overlapping syncs both inserted → duplicate meeting notes. The insert now
goes through `INSERT ... ON CONFLICT DO NOTHING`, arbitrated by the partial
unique index `ux_notes_source_ref_fireflies` (migration 0186), so a repeated
source_ref yields exactly one note.

Real Postgres (in-process, migrations applied by CI before pytest).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.note import Note
from app.services.fireflies_sync import _insert_meeting_note_if_absent


async def test_fireflies_source_ref_dedup_is_atomic() -> None:
    """Inserting the same fireflies source_ref twice yields ONE note; the
    second attempt returns None (conflict skipped)."""
    sref = f"fireflies:test-{uuid.uuid4().hex}"
    try:
        async with AsyncSessionLocal() as db:
            id1 = await _insert_meeting_note_if_absent(
                db,
                content="# Spotkanie A",
                candidate_id=None,
                job_id=None,
                source_ref=sref,
                audio_url=None,
            )
            await db.commit()

            id2 = await _insert_meeting_note_if_absent(
                db,
                content="# Spotkanie A (duplikat)",
                candidate_id=None,
                job_id=None,
                source_ref=sref,
                audio_url=None,
            )
            await db.commit()

            assert id1 is not None
            assert id2 is None  # ON CONFLICT DO NOTHING → no row inserted

            count = await db.scalar(
                select(func.count()).select_from(Note).where(Note.source_ref == sref)
            )
            assert count == 1
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Note).where(Note.source_ref == sref))
            await db.commit()


async def test_null_source_ref_notes_always_insert() -> None:
    """A note with no fireflies source_ref falls outside the partial index and
    always inserts (the dedup must not swallow un-keyed notes)."""
    ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            for _ in range(2):
                nid = await _insert_meeting_note_if_absent(
                    db,
                    content="# Spotkanie bez source_ref",
                    candidate_id=None,
                    job_id=None,
                    source_ref=None,
                    audio_url=None,
                )
                assert nid is not None
                ids.append(nid)
            await db.commit()
        assert len(set(ids)) == 2  # two distinct rows
    finally:
        if ids:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Note).where(Note.id.in_(ids)))
                await db.commit()
