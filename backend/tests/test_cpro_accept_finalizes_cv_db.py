"""Akceptacja DL-a do kolejki Cpro zatwierdza CV etapu (wariant A, 10.11.2026).

Zgłoszenie osoby od Cpro: „CV” w kolejce „Do wrzucenia do Cpro” dawało plik
„SZKIC_…”, bo akceptacja Delivery Leada niczego nie zatwierdzała, a bez wersji
zatwierdzonej kolejka robi plik z bieżącej treści edytora. Pobranie w teście
idzie tą samą drogą co `lib/stage-cv-file.ts`. Dane wyłącznie fikcyjne.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from app.services.cv_dl_accept_finalize import APPROVED_VIA, SKIPPED_ACTION
from tests.test_board_tasks import (
    CPRO_RATE,
    _cleanup,
    _login,
    _seed_user,
    _seed_world,
    restore_cpro_sender,
    seed_entry_row,
)

DRAFT_HTML = (
    "<h1>Ewa BT</h1><p>Senior Java Developer</p>"
    "<h2>Doświadczenie</h2><ul><li>Migracje systemów bankowych</li></ul>"
)
DOCX_NAME = "B2B_Java Developer_Ewa BT.docx"


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def review(monkeypatch: pytest.MonkeyPatch):
    """Kontrola treści przed zatwierdzeniem — bez AI. Domyślnie przechodzi."""
    from unittest.mock import AsyncMock

    from app.services import cv_approval_review

    mock = AsyncMock(return_value={"status": "verified", "method": "test-review"})
    monkeypatch.setattr(cv_approval_review, "review_for_approval", mock)
    return mock


async def _move(client: AsyncClient, headers: dict, world: dict, key: str, **extra):
    res = await client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["job_id"],
            "stage_def_id": world["defs"][key],
            **extra,
        },
    )
    assert res.status_code == 200, res.text
    return res


async def _draft_on_latest_row(world: dict) -> int:
    """Szkic CV etapu na wierszu „Zweryfikowany” — tam rekruter go poprawia."""
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == world["candidate_id"],
                CandidateStage.job_id == world["job_id"],
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        # Ruch zakłada wiersz z migawką oryginału; szkic dopisuje generator.
        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage.id
            )
        )
        if csv is None:
            csv = CandidateStageCV(
                candidate_stage_id=stage.id,
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
            )
            db.add(csv)
        csv.branded_status = "draft"
        csv.branded_draft_html = DRAFT_HTML
        csv.branded_docx_filename = DOCX_NAME
        csv.branded_language = "pl"
        await db.commit()
        return stage.id


async def _queue_item(client: AsyncClient, headers: dict, world: dict) -> dict:
    res = await client.get("/api/board-tasks/cpro/queue", headers=headers)
    assert res.status_code == 200, res.text
    group = next(g for g in res.json()["jobs"] if g["job_id"] == world["job_id"])
    return next(i for i in group["items"] if i["candidate_id"] == world["candidate_id"])


async def _download_like_the_queue(client: AsyncClient, headers: dict, stage_id: int):
    """`fetchStageCvFile`: zatwierdzona wersja → jej DOCX, szkic → podgląd."""
    base = f"/api/candidates/stages/{stage_id}/cv/branded"
    branded = (await client.get(base, headers=headers)).json()
    if branded["status"] == "finalized":
        return await client.get(
            f"{base}/versions/{branded['version']}/docx?intent=download&surface=cpro",
            headers=headers,
        )
    return await client.post(
        f"{base}/preview-docx?intent=download&surface=cpro",
        headers=headers,
        json={
            "content_html": branded["content_html"] or "",
            "expected_revision": branded["edit_revision"],
        },
    )


async def _activities(stage_id: int, action: str) -> list[Activity]:
    async with AsyncSessionLocal() as db:
        csv_id = await db.scalar(
            select(CandidateStageCV.id).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )
        return list(
            (
                await db.scalars(
                    select(Activity).where(
                        Activity.entity_type == "candidate_stage_cv",
                        Activity.entity_id == csv_id,
                        Activity.action == action,
                    )
                )
            ).all()
        )


async def _accept(api_client, monkeypatch, world):
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    await seed_entry_row(world["candidate_id"], world["job_id"])
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    hor = await _login(api_client, hor_creds)
    dl = await _login(api_client, dl_creds)
    await _move(api_client, hor, world, "verified")
    stage_id = await _draft_on_latest_row(world)
    await _move(api_client, hor, world, "qc")
    await _move(api_client, dl, world, "cpro", **CPRO_RATE)
    return stage_id, hor, [hor_id, dl_id], dl_id


async def _cleanup_all(world: dict, users: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStageCV).where(
                CandidateStageCV.candidate_id == world["candidate_id"]
            )
        )
        await db.commit()
    await _cleanup(world, users)


@pytest.mark.asyncio
async def test_dl_accept_to_cpro_queue_gives_the_approved_file_not_a_draft(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, review
) -> None:
    world = await _seed_world()
    users: list[int] = []
    try:
        async with restore_cpro_sender():
            stage_id, hor, users, dl_id = await _accept(api_client, monkeypatch, world)

            item = await _queue_item(api_client, hor, world)
            assert item["cv"]["stage_id"] == stage_id
            res = await _download_like_the_queue(api_client, hor, stage_id)
            assert res.status_code == 200, res.text
            disposition = res.headers["content-disposition"]
            assert "SZKIC_" not in disposition, disposition
            assert "Java" in disposition
            assert item["cv"]["draft"] is False

            async with AsyncSessionLocal() as db:
                csv = await db.scalar(
                    select(CandidateStageCV).where(
                        CandidateStageCV.candidate_stage_id == stage_id
                    )
                )
                assert csv.branded_status == "finalized"
                assert csv.branded_finalized_by == dl_id
            # Ta sama ścieżka co „Zatwierdź”: kontrola treści przed zatwierdzeniem
            # biegła, a wpis mówi, że zatwierdził DL przy akceptacji.
            review.assert_awaited_once()
            (finalized,) = await _activities(stage_id, "branded_cv_finalized")
            assert finalized.user_id == dl_id
            assert finalized.details["approved_via"] == APPROVED_VIA
            assert await _activities(stage_id, SKIPPED_ACTION) == []
    finally:
        await _cleanup_all(world, users)


@pytest.mark.asyncio
async def test_review_required_keeps_the_draft_and_the_queue_says_so(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, review
) -> None:
    """Kontrola treści wymaga osobnego biegu (409) — akceptacja i tak przechodzi."""
    review.side_effect = HTTPException(
        409,
        {
            "code": "cv_review_required",
            "message": "Uruchom kontrolę bieżącej treści CV przed zatwierdzeniem.",
        },
    )
    world = await _seed_world()
    users: list[int] = []
    try:
        async with restore_cpro_sender():
            stage_id, hor, users, dl_id = await _accept(api_client, monkeypatch, world)

            item = await _queue_item(api_client, hor, world)
            assert item["accepted"] is True
            assert item["client_rate_value"] is not None
            assert item["cv"]["stage_id"] == stage_id
            assert item["cv"]["draft"] is True

            async with AsyncSessionLocal() as db:
                csv = await db.scalar(
                    select(CandidateStageCV).where(
                        CandidateStageCV.candidate_stage_id == stage_id
                    )
                )
                assert csv.branded_status == "draft"
                assert csv.branded_draft_html == DRAFT_HTML
                assert csv.edit_revision == 0
            res = await _download_like_the_queue(api_client, hor, stage_id)
            assert res.status_code == 200, res.text
            assert "SZKIC_" in res.headers["content-disposition"]
            assert await _activities(stage_id, "branded_cv_finalized") == []
            (skipped,) = await _activities(stage_id, SKIPPED_ACTION)
            assert skipped.user_id == dl_id
            assert skipped.details["reason"] == "cv_review_required"
    finally:
        await _cleanup_all(world, users)
