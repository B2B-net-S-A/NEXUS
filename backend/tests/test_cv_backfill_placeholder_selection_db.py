"""Wybór profili do `backfill-names` na prawdziwym Postgresie.

Zapytanie przekazuje listę wypełniaczy jako tablicę: test sprawdza, że baza ją
przyjmuje, a bieg widzi profile `Unknown` z Traffita i nie rusza pozostałych.
"""

from __future__ import annotations

import uuid

import pytest


async def _seed(name: str, lastname: str, *, external_source: str = "traffit") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name=name,
            lastname=lastname,
            external_source=external_source,
            external_id=f"tt-{uuid.uuid4().hex[:10]}",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


@pytest.mark.asyncio
async def test_dry_run_selects_only_traffit_placeholder_rows(app_client):
    from app.core.database import AsyncSessionLocal
    from app.services.cv_backfill import backfill_missing_names

    unknown = await _seed("Unknown", "Unknown")
    await _seed("Unknown", f"Realne-{uuid.uuid4().hex[:6]}")
    question_mark = await _seed("?", "?")
    await _seed("Realne", f"Nazwisko-{uuid.uuid4().hex[:6]}")
    await _seed("Unknown", "Unknown", external_source="manual")

    async with AsyncSessionLocal() as db:
        # `after_id` tnie do świeżych wierszy, bo baza testowa jest wspólna.
        stats = await backfill_missing_names(db, after_id=unknown - 1, dry_run=True)

    assert stats["total"] == 3
    assert stats["last_id"] == question_mark
