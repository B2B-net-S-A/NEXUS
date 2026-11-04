"""Runda 10 (R10-N8-3): znacznik odczytu CV działa na prawdziwym Postgresie.

Skrót liczy Python (`hashlib.md5`), a scope porównuje go z `md5()` Postgresa.
Test sprawdza, że oba dają to samo dla tekstu z polskimi znakami — rozjazd
znaczyłby wieczne płacenie za ten sam wiersz albo zgubienie nowego CV.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select


async def _seed(raw_cv_text: str, extracted: dict | None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Znacznik",
            lastname=f"CV-{uuid.uuid4().hex[:6]}",
            email=f"cvmark-{uuid.uuid4().hex[:8]}@example.com",
            raw_cv_text=raw_cv_text,
            cv_extracted_data=extracted,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _in_scope(candidate_id: int) -> bool:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services import cv_field_backfill as runner

    async with AsyncSessionLocal() as db:
        n = await db.scalar(
            select(func.count())
            .select_from(Candidate)
            .where(Candidate.id == candidate_id, *runner._scope_filter())
        )
        return bool(n)


@pytest.mark.asyncio
async def test_marked_row_leaves_scope_until_cv_text_changes(app_client):
    from app.services import cv_field_backfill as runner

    text_now = "Doświadczenie: Łódź, żółć, programista Python. " * 10
    marked = await _seed(
        text_now, {runner.READ_MARK_KEY: runner.cv_text_digest(text_now)}
    )
    stale = await _seed(
        text_now, {runner.READ_MARK_KEY: runner.cv_text_digest("stare CV " * 40)}
    )
    unmarked = await _seed(text_now, None)

    assert not await _in_scope(marked)
    assert await _in_scope(stale), "nowy tekst CV wraca do scope'u"
    assert await _in_scope(unmarked)
