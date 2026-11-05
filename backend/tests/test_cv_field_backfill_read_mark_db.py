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


@pytest.mark.asyncio
async def test_read_of_another_person_leaves_a_review_and_no_facts(
    app_client, monkeypatch
):
    """Na prawdziwej bazie: wiersz kwarantanny jest, faktów ani tekstu nie ma."""

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services import cv_field_backfill as runner
    from app.services import cv_text_backfill
    from app.services.candidate_identity_quarantine import get_identity_review

    class _OkFeature:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    async def fake_parse(cv_text, *, model, template):
        return {
            "first_name": "Ewa",
            "last_name": "Fikcyjna",
            "city": "Gdańsk",
            "skills": ["Python"],
            "_confidence": {},
        }

    monkeypatch.setattr(runner, "ai_feature", _OkFeature)
    monkeypatch.setattr(runner, "parse_cv_with_claude", fake_parse)
    monkeypatch.setattr(runner, "SLEEP_BETWEEN_CALLS_S", 0)

    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Jan",
            lastname=f"Testowy{uuid.uuid4().hex[:6]}",
            email=f"bramka-{uuid.uuid4().hex[:8]}@example.com",
            raw_cv_text="Doświadczenie innej osoby. " * 20,
            cv_storage_key=f"cv/{uuid.uuid4().hex}.pdf",
        )
        db.add(candidate)
        await db.commit()
        candidate_id = candidate.id

    async with AsyncSessionLocal() as db:
        stats = await runner.backfill_cv_fields(db, candidate_ids=[candidate_id])
    assert stats["identity_quarantined"] == 1

    async with AsyncSessionLocal() as db:
        saved = await db.get(Candidate, candidate_id)
        assert saved.raw_cv_text is None
        assert saved.city is None
        review = await get_identity_review(
            db,
            candidate_id=candidate_id,
            source_kind="legacy_cv",
            source_id=candidate_id,
        )
        assert review is not None and review.is_quarantined

        pending = await db.execute(
            cv_text_backfill._pending_candidates_stmt(None).where(
                Candidate.id == candidate_id
            )
        )
        assert pending.first() is None, "tekst z tego pliku nie wraca po kwarantannie"
