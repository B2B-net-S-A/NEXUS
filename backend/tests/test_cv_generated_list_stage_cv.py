"""Lista CV z generatora mówi, do którego CV etapu podpięto dokument (D4, 14.10.2026).

Profil kandydata („Pliki i umowy” → „CV dla klientów”) pobierał surowy plik
generatora, a poprawki z edytora i po QC żyją wyłącznie w CV etapu. Lista podaje
teraz wiersz etapu, z którego profil pobiera plik z poprawkami.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from tests.test_cv_auto_generate import _headers, _world
from tests.test_cv_generated_list_filters import _doc
from tests.test_pending_gate_removed import pv_client  # noqa: F401


async def _later_stage(world: dict) -> int:
    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=PipelineStage.cv_sent,
            moved_by=world["user_id"],
            moved_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(stage)
        await db.commit()
        return stage.id


async def _stage_cv(world: dict, stage_id: int, document_id: int, **fields) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStageCV(
                candidate_stage_id=stage_id,
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                generated_document_id=document_id,
                branded_from_generator=True,
                branded_draft_html="<p>CV</p>",
                **fields,
            )
        )
        await db.commit()


async def _items(client: AsyncClient, world: dict) -> dict[int, dict]:
    response = await client.get(
        "/api/cv-generator/generated",
        params={"candidate_id": world["candidate_id"]},
        headers=_headers(world["user_id"]),
    )
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()}


@pytest.mark.asyncio
async def test_attached_document_points_at_its_stage_cv(pv_client: AsyncClient):
    world = await _world()
    attached = await _doc(world, created_by=world["user_id"], name="Podpięte")
    unused = await _doc(world, created_by=world["user_id"], name="Nieużyte")
    edited_at = datetime(2026, 10, 14, 9, 30, tzinfo=timezone.utc)
    await _stage_cv(
        world,
        world["stage_id"],
        attached,
        branded_status="draft",
        branded_updated_at=edited_at,
    )

    items = await _items(pv_client, world)

    assert items[attached]["stage_cv_stage_id"] == world["stage_id"]
    assert items[attached]["stage_cv_status"] == "draft"
    assert items[attached]["stage_cv_updated_at"].startswith("2026-10-14T09:30")
    assert items[attached]["stage_cv_finalized_at"] is None
    assert items[attached]["job_title"].startswith("CV auto job")
    # Dokument, którego nikt nie podpiął, pobiera się jak dotąd — z generatora.
    assert items[unused]["stage_cv_stage_id"] is None
    assert items[unused]["stage_cv_status"] is None


@pytest.mark.asyncio
async def test_finalized_stage_cv_wins_over_later_draft(pv_client: AsyncClient):
    # Ta sama kolejność co CV firmowe pary w panelu osoby: zatwierdzone przed
    # szkicem, dopiero potem najnowszy etap.
    world = await _world()
    document = await _doc(world, created_by=world["user_id"], name="Dwa etapy")
    finalized_at = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)
    await _stage_cv(
        world,
        world["stage_id"],
        document,
        branded_status="finalized",
        branded_version=2,
        branded_finalized_at=finalized_at,
    )
    later = await _later_stage(world)
    await _stage_cv(world, later, document, branded_status="draft")

    item = (await _items(pv_client, world))[document]

    assert item["stage_cv_stage_id"] == world["stage_id"]
    assert item["stage_cv_status"] == "finalized"
    assert item["stage_cv_finalized_at"].startswith("2026-10-13T15:00")


@pytest.mark.asyncio
async def test_stage_row_without_company_cv_is_ignored(pv_client: AsyncClient):
    # Wiersz etapu w stanie „none” (np. po wycofaniu szkicu) nie jest CV do pobrania.
    world = await _world()
    document = await _doc(world, created_by=world["user_id"], name="Bez CV etapu")
    await _stage_cv(world, world["stage_id"], document, branded_status="none")

    item = (await _items(pv_client, world))[document]

    assert item["stage_cv_stage_id"] is None
