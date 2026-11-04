"""Wyścig o ten sam e-mail na prawdziwym indeksie unikalnym — z bazą (wymaga CI).

Okno wyścigu odtwarzamy deterministycznie: sito duplikatów „nie widzi”
zwycięzcy (jak niezacommitowanego wiersza drugiej transakcji), a INSERT/UPDATE
trafia w `ix_candidates_email`. Przed poprawką: 500 w `/from-cv` i zatruta
sesja we wspólnej ścieżce CV. Wariant bez bazy: ``test_fix48_ws10_email_race.py``.
Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.index_outbox import IndexOutboxEvent


async def _seed_winner(email: str) -> int:
    async with AsyncSessionLocal() as db:
        winner = Candidate(
            name="Jan", lastname=f"Zwycięzca{uuid.uuid4().hex[:6]}", email=email
        )
        db.add(winner)
        await db.commit()
        return winner.id


async def _drop(*ids: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(IndexOutboxEvent).where(
                IndexOutboxEvent.entity_type == "candidate",
                IndexOutboxEvent.entity_id.in_(ids),
            )
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_from_cv_losing_the_race_answers_409_with_the_existing_profile(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
):
    from app.api import candidates as candidates_api
    from app.services.dedup_service import find_candidate_by_email as real_find

    email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    lastname = f"Wyścig{uuid.uuid4().hex[:6]}"
    winner_id = await _seed_winner(email)
    calls: list[str] = []

    async def _blind_first(db, value, **kw):
        calls.append(value)
        if len(calls) == 1:
            return []  # zwycięzca jeszcze niezacommitowany
        return await real_find(db, value, **kw)

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(candidates_api, "find_candidate_by_email", _blind_first)
    monkeypatch.setattr(
        candidates_api,
        "_read_cv_for_new_candidate",
        AsyncMock(
            return_value=(
                "tekst CV",
                {"first_name": "Jan", "last_name": lastname, "email": email},
            )
        ),
    )
    try:
        resp = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files={"file": ("cv.pdf", b"%PDF-1.4 wyscig", "application/pdf")},
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["existing_candidate_id"] == winner_id
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Candidate)
                    .where(Candidate.lastname == lastname)
                )
                == 0
            )
    finally:
        await _drop(winner_id)


@pytest.mark.asyncio
async def test_ingest_drops_an_email_taken_in_parallel_and_the_session_survives(
    monkeypatch,
):
    from app.services import cv_ingest_service, index_outbox_service
    from app.services.cv_enrichment import CvWritePolicy

    email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    winner_id = await _seed_winner(email)

    async def _blind(_db, _candidate, parsed):
        return parsed  # sito nie widzi zwycięzcy

    monkeypatch.setattr(cv_ingest_service, "_without_taken_email", _blind)
    monkeypatch.setattr(
        index_outbox_service,
        "schedule_or_embed_candidate",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(cv_ingest_service, "assign_primary_cc_if_empty", AsyncMock())

    try:
        async with AsyncSessionLocal() as db:
            try:
                loser = Candidate(name="Jan", lastname="Przegrany")
                db.add(loser)
                await db.flush()
                # Zmiana wołającego sprzed wspólnej ścieżki (jak `raw_cv_text`
                # w uploadzie) nie może zniknąć razem z adresem.
                loser.raw_cv_text = "cv"
                await cv_ingest_service.finish_cv_ingest(
                    db,
                    candidate=loser,
                    parsed={
                        "_source": "claude:cv_enrichment:v7",
                        "email": email,
                        "phone": "+48 500 600 700",
                        "skills": [{"name": "Python", "level": "senior"}],
                    },
                    source_document_id=None,
                    source_hash=uuid.uuid4().hex,
                    policy=CvWritePolicy.FILL_EMPTY,
                    trigger="email",
                )
                await db.flush()
                saved = (
                    await db.execute(
                        select(
                            Candidate.email,
                            Candidate.phone,
                            Candidate.raw_cv_text,
                            Candidate.skills,
                        ).where(Candidate.id == loser.id)
                    )
                ).one()
                assert saved.email is None
                assert saved.phone == "+48 500 600 700"
                assert saved.raw_cv_text == "cv"
                assert [skill["name"] for skill in saved.skills] == ["Python"]
            finally:
                await db.rollback()
    finally:
        await _drop(winner_id)
