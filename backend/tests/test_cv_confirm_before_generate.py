"""CV po potwierdzeniu w karcie (21.10.2026) — prawdziwy Postgres.

Zgłoszenie zespołu: ruch na „Zweryfikowany” generował CV, zanim rekruter
dopisał notatkę do CV, z pliku wybranego przez system i bez cofnięcia.
Kontrakty:

- domyślnie ruch nie generuje CV: zero wywołań generatora, zero wpisów
  w „Pracy w tle”, zero dzwonków „Automat nie zrobił CV”;
- istniejące CV pary dalej dostaje QC zaraz po ruchu;
- `…/cv/ai-sources` proponuje plik kopii „Oryginał CV” etapu, a bez niej
  główne CV z pominięciem „nieaktualnych”; lista plików mówi, który jest który.

Dane fikcyjne.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate_document import CandidateDocument
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.notification import Notification
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import cv_auto_generate as auto
from tests.test_cv_auto_generate import _events, _fake_generator, _headers, _world
from tests.test_pending_gate_removed import pv_client  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _bells(user_id: int) -> list[Notification]:
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(Notification.user_id == user_id)
                )
            ).all()
        )


async def test_move_to_verified_does_not_generate_by_default(monkeypatch):
    world = await _world()
    calls = _fake_generator(monkeypatch)
    async with AsyncSessionLocal() as db:
        assert (
            await auto._enqueue(
                db, stage_id=world["stage_id"], user_id=world["user_id"]
            )
            is None
        )
    assert calls == []
    assert await _events(world["job_id"]) == []
    assert await _bells(world["user_id"]) == []


async def test_missing_cv_file_does_not_ring_when_nothing_was_asked(monkeypatch):
    # Dawniej: „Automat nie zrobił CV: kandydat nie ma w profilu pliku CV”.
    world = await _world(with_cv=False)
    _fake_generator(monkeypatch)
    async with AsyncSessionLocal() as db:
        await auto._enqueue(db, stage_id=world["stage_id"], user_id=world["user_id"])
    assert await _events(world["job_id"]) == []
    assert await _bells(world["user_id"]) == []


async def test_existing_pair_cv_still_gets_qc_after_the_move(monkeypatch):
    world = await _world()
    async with AsyncSessionLocal() as db:
        screening = CandidateStage(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=PipelineStage.screening,
            moved_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.add(screening)
        await db.flush()
        db.add(
            CandidateStageCV(
                candidate_stage_id=screening.id,
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                branded_status="draft",
                branded_draft_html="<p>CV wybrane w screeningu</p>",
            )
        )
        await db.commit()
        pair_stage_id = screening.id
    qc: list[tuple] = []

    async def qc_after_attach(stage_id, user_id, *, notify_ready=False):
        qc.append((stage_id, user_id))

    monkeypatch.setattr(auto, "qc_after_attach", qc_after_attach)
    calls = _fake_generator(monkeypatch)
    async with AsyncSessionLocal() as db:
        await auto._enqueue(db, stage_id=world["stage_id"], user_id=world["user_id"])
    assert qc == [(pair_stage_id, world["user_id"])]
    assert calls == []
    assert await _events(world["job_id"]) == []


async def _add_files(world: dict) -> dict[str, int]:
    """Główne CV „B2B” (nowsze), oryginał etapu (starszy), nieaktualne."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        primary = await db.get(CandidateDocument, await _primary_id(db, world))
        primary.filename = "Auto_B2B_Klient.docx"
        primary.content_sha256 = "b2b" * 21 + "x"
        primary.uploaded_at = now
        original = CandidateDocument(
            candidate_id=world["candidate_id"],
            filename="Auto_CV.pdf",
            content_sha256="a" * 64,
            uploaded_at=now - timedelta(days=7),
        )
        outdated = CandidateDocument(
            candidate_id=world["candidate_id"],
            filename="Auto_CV_EN_2019.docx",
            content_sha256="c" * 64,
            uploaded_at=now - timedelta(days=1),
            outdated_at=now,
        )
        db.add_all([original, outdated])
        await db.flush()
        ids = {"primary": primary.id, "original": original.id, "outdated": outdated.id}
        await db.commit()
        return ids


async def _primary_id(db, world: dict) -> int:
    from sqlalchemy import select

    return await db.scalar(
        select(CandidateDocument.id).where(
            CandidateDocument.candidate_id == world["candidate_id"],
            CandidateDocument.is_primary.is_(True),
        )
    )


async def _sources(client: AsyncClient, world: dict) -> dict:
    response = await client.get(
        f"/api/candidates/stages/{world['stage_id']}/cv/ai-sources",
        headers=_headers(world["user_id"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_default_file_is_the_stage_original_not_the_newest_primary(
    pv_client: AsyncClient,
):
    world = await _world()
    ids = await _add_files(world)
    async with AsyncSessionLocal() as db:
        # Kopia „Oryginał CV” na wierszu sprzed ruchu karty.
        screening = CandidateStage(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=PipelineStage.screening,
            moved_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.add(screening)
        await db.flush()
        db.add(
            CandidateStageCV(
                candidate_stage_id=screening.id,
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                original_cv_filename="Auto_CV.pdf",
                original_cv_sha256="a" * 64,
                original_snapshot_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    body = await _sources(pv_client, world)
    assert body["original_cv"]["document_id"] == ids["original"]
    files = {f["document_id"]: f for f in body["cv_files"]}
    assert files[ids["original"]]["stage_original"] is True
    assert files[ids["primary"]]["is_primary"] is True
    assert files[ids["primary"]]["stage_original"] is False
    assert files[ids["outdated"]]["outdated"] is True
    # Kolejność generatora: najpierw główne.
    assert body["cv_files"][0]["document_id"] == ids["primary"]


async def test_without_stage_copy_default_skips_outdated_files(pv_client: AsyncClient):
    world = await _world()
    ids = await _add_files(world)
    async with AsyncSessionLocal() as db:
        primary = await db.get(CandidateDocument, ids["primary"])
        primary.outdated_at = datetime.now(timezone.utc)
        primary.is_primary = False
        await db.commit()
    body = await _sources(pv_client, world)
    # Bez kopii etapu: najnowszy plik, który nie jest „nieaktualny”.
    assert body["original_cv"]["document_id"] == ids["original"]
    assert all(not f["stage_original"] for f in body["cv_files"])
