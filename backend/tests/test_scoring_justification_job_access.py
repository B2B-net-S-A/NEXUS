"""Uzasadnienie „Dopasowania” (`/api/candidates/{id}/scoring/{job}`) a dostęp do rekrutacji.

Trasa miała tylko bramkę roli i sekcji kandydatów (sourcing). Przy braku wpisu
w cache woła PŁATNY model i zapisuje wynik, więc osoba bez dostępu do
rekrutacji mogła wygenerować i przeczytać ocenę cudzej oferty.

Bramka jest ta sama co przy kolumnie wyniku C2 (`_authorized_job` w
`candidate_search`): sekcja rekrutacji (pipeline) do odczytu + rekrutacja
istnieje. Nie jest ostrzejsza: rekruter spoza zespołu rekrutacji dalej widzi tę
liczbę na ekranach C2, więc dostaje też uzasadnienie.

Prawdziwy Postgres i auth; zamockowany tylko model (i bramka limitu AI).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

import app.models  # noqa: F401  (register every mapper)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.match_justification import CandidateMatchJustification
from app.models.section_permission import UserSectionOverride
from app.models.user import User, UserRole
from app.services import canonical_fit
from app.services import match_justification_service as mjs


@asynccontextmanager
async def _admitted(db, feature, *, user_id=None, units=1):
    yield None


@pytest.fixture
def model_spy(monkeypatch):
    """Model i wektory zamockowane; spy mówi, czy ktoś zawołał płatny model."""
    spy = AsyncMock(return_value={"summary": "Ocena.", "pros": ["Go"], "watchouts": []})
    monkeypatch.setattr(mjs, "ai_feature", _admitted)
    monkeypatch.setattr(mjs, "_call_claude_json", spy)
    monkeypatch.setattr(canonical_fit, "request_vector", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.services.embedding_service.similarity_for_candidate_ids",
        AsyncMock(return_value={}),
    )
    return spy


async def _world(*, pipeline: str | None) -> dict:
    """Rekrutacja bez zespołu, kandydat i rekruter (z opcjonalnym override sekcji)."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Scoring access {tag}")
        user = User(
            email=f"scoring-access-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Scoring"),
            name="Scoring Access",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add_all([client, user])
        await db.flush()
        job = Job(title=f"Go developer {tag}", client_id=client.id, must_skills=["Go"])
        candidate = Candidate(name="Dostęp", lastname=f"Oceny {tag}", skills=["Go"])
        db.add_all([job, candidate])
        await db.flush()
        if pipeline is not None:
            db.add(
                UserSectionOverride(
                    user_id=user.id, section="pipeline", access=pipeline
                )
            )
        await db.commit()
        return {
            "user_id": user.id,
            "job_id": job.id,
            "candidate_id": candidate.id,
            "headers": {
                "Authorization": "Bearer "
                + create_access_token(user.id, UserRole.recruiter.value)
            },
        }


async def _cached_rows(world: dict) -> int:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(CandidateMatchJustification).where(
                CandidateMatchJustification.job_id == world["job_id"]
            )
        )
        return len(rows.all())


async def _cleanup(world: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateMatchJustification).where(
                CandidateMatchJustification.job_id == world["job_id"]
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_get_without_pipeline_access_is_refused_before_the_model(
    app_client: AsyncClient, model_spy
):
    world = await _world(pipeline="none")
    path = f"/api/candidates/{world['candidate_id']}/scoring/{world['job_id']}"
    try:
        for query in ("", "?refresh=true"):
            response = await app_client.get(path + query, headers=world["headers"])
            assert response.status_code == 403, response.text

        model_spy.assert_not_called()
        assert await _cached_rows(world) == 0
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_feedback_without_pipeline_access_is_refused_and_leaves_no_rating(
    app_client: AsyncClient, model_spy
):
    # Wiersz w cache istnieje (ktoś z dostępem go wygenerował): bez dostępu do
    # rekrutacji nie wolno ani go ocenić, ani z odpowiedzi czytać treści.
    allowed = await _world(pipeline=None)
    denied = await _world(pipeline="none")
    path = f"/api/candidates/{allowed['candidate_id']}/scoring/{allowed['job_id']}"
    try:
        generated = await app_client.get(path, headers=allowed["headers"])
        assert generated.status_code == 200, generated.text

        response = await app_client.post(
            f"{path}/feedback", json={"rating": -1}, headers=denied["headers"]
        )
        assert response.status_code == 403, response.text

        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(CandidateMatchJustification).where(
                    CandidateMatchJustification.job_id == allowed["job_id"]
                )
            )
            assert row is not None and row.rating is None
    finally:
        await _cleanup(allowed)


@pytest.mark.asyncio
async def test_missing_recruitment_is_404_and_the_model_is_not_called(
    app_client: AsyncClient, model_spy
):
    world = await _world(pipeline=None)
    try:
        response = await app_client.get(
            f"/api/candidates/{world['candidate_id']}/scoring/2000000000",
            headers=world["headers"],
        )
        assert response.status_code == 404, response.text
        model_spy.assert_not_called()
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_recruiter_outside_the_job_team_keeps_the_justification(
    app_client: AsyncClient, model_spy
):
    # Bramka nie jest ostrzejsza niż kolumna wyniku C2: ta sama liczba jest
    # widoczna dla rekrutera spoza zespołu, więc uzasadnienie też.
    world = await _world(pipeline=None)
    path = f"/api/candidates/{world['candidate_id']}/scoring/{world['job_id']}"
    try:
        response = await app_client.get(path, headers=world["headers"])
        assert response.status_code == 200, response.text
        assert response.json()["summary"] == "Ocena."
        assert model_spy.await_count == 1
    finally:
        await _cleanup(world)
