"""Regresja: embedding świeżo utworzonego kandydata (prod 2026-09-16).

``POST /candidates/from-cv`` tworzy kandydata, robi ``flush()`` i od razu woła
``schedule_or_embed_candidate`` na TEJ SAMEJ sesji. Każda kolumna, której
INSERT nie ustawił (``tags``, ``ai_summary``, ``experience``…), jest po flushu
„expired", a ``desired_state`` → ``_build_candidate_text`` czyta je
synchronicznie → SQLAlchemy próbuje doładować je poza greenletem →
``MissingGreenlet`` → „[from-cv] embedding failed" dla KAŻDEGO nowego
kandydata (55/55 w 4 h na prod). Istniejący kandydaci (409) nigdy nie padali,
bo przychodzą z pełnym SELECT-em.

Kontrakty:
1. Po samym ``flush()`` outbox-wrapper NIE rzuca i kolejkuje upsert
   z revision > 0 i niepustym hashem.
2. Doładowanie dotyka wyłącznie kolumn NIEZAŁADOWANYCH — zmiana w pamięci,
   jeszcze niesflushowana, przeżywa (pełny ``refresh`` by ją cofnął).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.services import index_outbox_service as outbox

pytestmark = pytest.mark.asyncio


async def _cleanup(candidate_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM match_index_outbox WHERE entity_id = :e"),
            {"e": candidate_id},
        )
        await db.execute(text("DELETE FROM candidates WHERE id = :e"), {"e": candidate_id})
        await db.commit()


async def test_fresh_flushed_candidate_is_enqueued_without_greenlet_error(monkeypatch):
    monkeypatch.setattr(settings, "AI_INDEX_OUTBOX_ENABLED", True)
    captured: dict = {}

    async def _fake_enqueue(**kw):
        captured.update(kw)

    monkeypatch.setattr(outbox, "_enqueue_isolated", _fake_enqueue)

    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Fresh", lastname=f"Flush-{uuid.uuid4().hex[:8]}")
        db.add(cand)
        await db.flush()  # jak w from-cv: id jest, created_at/updated_at jeszcze nie
        cid = cand.id
        try:
            ok = await outbox.schedule_or_embed_candidate(cid, db)
        finally:
            await db.rollback()
    await _cleanup(cid)

    assert ok is True
    assert captured["entity_id"] == cid
    assert captured.get("operation", "upsert") == "upsert"
    assert captured["revision"] > 0, "updated_at nie zostało doładowane po flushu"
    assert captured["desired_hash"]


async def test_load_unloaded_columns_keeps_pending_in_memory_change():
    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Keep", lastname=f"Pending-{uuid.uuid4().hex[:8]}")
        db.add(cand)
        await db.flush()
        cid = cand.id
        try:
            cand.ai_summary = "niesflushowana zmiana"
            loaded = await outbox.load_unloaded_columns(db, cand)
            # Nieustawione kolumny bez defaultu (np. availability_date) były
            # expired i zostały doładowane…
            assert loaded and "availability_date" in loaded
            # …ale ustawiona w pamięci nie — i jej wartość przeżyła.
            assert "ai_summary" not in loaded
            assert cand.ai_summary == "niesflushowana zmiana"
            assert cand.availability_date is None
            assert cand.updated_at is not None
            # Drugie wywołanie nie ma już czego doładowywać.
            assert await outbox.load_unloaded_columns(db, cand) == []
        finally:
            await db.rollback()
    await _cleanup(cid)
