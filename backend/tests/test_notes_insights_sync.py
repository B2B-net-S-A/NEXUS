"""Doganianie starszej wersji promptu w nocnym odczycie notatek (22.09.2026).

Kandydat, którego notatki się nie zmieniły, a fakty policzono promptem sprzed
trybu pracy, ma dostać ponowny odczyt — ale PO kandydatach z nowymi
notatkami i bez wierszy „bez treści”.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.note import Note, NoteType
from app.services.notes_insights_extractor import EXTRACTION_MODEL, PROMPT_VERSION
from app.tasks.notes_insights_sync import _select_outdated_candidates


async def _seed(insights: dict | None) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Sync",
            lastname=f"Upgrade-{uuid.uuid4().hex[:6]}",
            email=f"notes-sync-{uuid.uuid4().hex[:8]}@example.com",
            cv_extracted_data={"_notes_insights": insights}
            if insights is not None
            else None,
        )
        db.add(cand)
        await db.flush()
        db.add(
            Note(
                content="Kandydat woli hybrydę, 2 dni w biurze.",
                note_type=NoteType.general,
                candidate_id=cand.id,
            )
        )
        await db.commit()
        return cand.id


@pytest.mark.asyncio
async def test_outdated_rows_are_selected_current_and_empty_are_not():
    old = await _seed({"_extractor": "notes_insights:v4-onsite-days:haiku-4.5"})
    legacy = await _seed({"expected_rate": {"value": 150}})
    current = await _seed(
        {"_extractor": f"notes_insights:{PROMPT_VERSION}:{EXTRACTION_MODEL}"}
    )
    no_content = await _seed({"_no_content": True})
    never = await _seed(None)

    picked = await _select_outdated_candidates(10_000, exclude=set())
    assert old in picked
    assert legacy in picked
    assert current not in picked
    assert no_content not in picked
    assert never not in picked, "brak ekstrakcji to sprawa selekcji po notatkach"

    assert old not in await _select_outdated_candidates(10_000, exclude={old})
    assert await _select_outdated_candidates(0, exclude=set()) == []
