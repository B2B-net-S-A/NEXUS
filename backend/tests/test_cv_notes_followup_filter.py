"""Runda 7 (R7-X4-5): notatka z telefonu po ciszy klienta nie trafia do promptu CV.

Taka notatka ma ``job_id=NULL`` (jedna na osobę, nie na proces), a jej treść
wymienia klientów i rekrutacje WSZYSTKICH czekających procesów. CV pod
klienta A dostawało więc w ``<screening_notes>`` nazwę klienta B.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.note import Note
from app.services.cv_generator_b2b import standalone_service as svc


def test_followup_filter_compiles_to_a_null_safe_clause():
    sql = str(
        svc._not_followup_note().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "source_ref IS NULL" in sql
    assert "NOT LIKE 'followup:%%'" in sql or "NOT LIKE 'followup:%'" in sql


@pytest.mark.asyncio
async def test_candidate_notes_skip_the_followup_call_note():
    from tests.test_cv_auto_generate import _world

    world = await _world()
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                Note(
                    content="Kandydat zna Kafkę i Kubernetes.",
                    candidate_id=world["candidate_id"],
                ),
                Note(
                    content=(
                        "Follow-up (klient milczy): coś się zmieniło.\n"
                        "Procesy: Inny Klient SA — Java Developer (rezygnuje)"
                    ),
                    candidate_id=world["candidate_id"],
                    source_ref="followup:999",
                ),
            ]
        )
        await db.commit()
        text = await svc.collect_candidate_notes_text(
            db, candidate_id=world["candidate_id"]
        )
    assert "Kafkę" in text
    assert "Inny Klient SA" not in text
