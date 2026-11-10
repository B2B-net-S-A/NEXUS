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


# ── Kontrola w tle po akceptacji (10.11.2026) ────────────────────────────────
# Gdy treść wymaga płatnej kontroli AI (409 `cv_review_required`), akceptacja
# puszcza ją w tle, a po wyniku CV zostaje zatwierdzone — o ile treść i rewizja
# się nie zmieniły. Kontrola biegnie prawdziwym workerem i prawdziwym
# `review_for_approval`; syntetyczne są tylko źródło, limit AI i recenzent.

SOURCE_TEXT = "Ewa BT Senior Java Developer Migracje systemów bankowych"


@pytest.fixture
def background_review(monkeypatch: pytest.MonkeyPatch):
    """Źródło i recenzent bez AI. `verifier.side_effect` zmienia werdykt."""
    import hashlib
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app.services import cv_approval_review

    source = SimpleNamespace(
        cv_bytes=b"source",
        cv_filename="source.docx",
        screening_notes="",
        identity="",
        snapshot_sha256="b" * 64,
    )
    monkeypatch.setattr(
        cv_approval_review, "load_review_source", AsyncMock(return_value=source)
    )
    monkeypatch.setattr(
        cv_approval_review, "extract_text_from_file", Mock(return_value=SOURCE_TEXT)
    )

    @asynccontextmanager
    async def quota(*args, **kwargs):
        yield

    monkeypatch.setattr(cv_approval_review, "ai_feature", quota)
    verifier = Mock(
        return_value={
            "version": cv_approval_review.VERIFIER_VERSION,
            "prompt_sha256": hashlib.sha256(
                cv_approval_review.VERIFICATION_PROMPT.encode()
            ).hexdigest(),
        }
    )
    monkeypatch.setattr(cv_approval_review, "verify_editor_content", verifier)
    return verifier


async def _draft_with_generated_source(world: dict) -> int:
    """Szkic poprawiony po generacji: zatwierdzenie wymaga kontroli AI."""
    from app.models.cv_generated_document import CvGeneratedDocument

    stage_id = await _draft_on_latest_row(world)
    async with AsyncSessionLocal() as db:
        document = CvGeneratedDocument(
            candidate_id=world["candidate_id"],
            candidate_name="Ewa BT",
            filename="source.docx",
            mode="upload",
            status="ready",
        )
        db.add(document)
        await db.flush()
        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )
        csv.generated_document_id = document.id
        await db.commit()
    return stage_id


async def _accept_with_review(api_client, monkeypatch, world):
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    await seed_entry_row(world["candidate_id"], world["job_id"])
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    hor = await _login(api_client, hor_creds)
    dl = await _login(api_client, dl_creds)
    await _move(api_client, hor, world, "verified")
    stage_id = await _draft_with_generated_source(world)
    await _move(api_client, hor, world, "qc")
    await _move(api_client, dl, world, "cpro", **CPRO_RATE)
    return stage_id, hor, [hor_id, dl_id], dl_id


async def _queued_review(stage_id: int):
    from app.models.cv_approval_job import CvApprovalJob

    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )
        jobs = list(
            (
                await db.scalars(
                    select(CvApprovalJob).where(
                        CvApprovalJob.candidate_stage_cv_id == csv.id
                    )
                )
            ).all()
        )
        return csv, jobs


async def _stage_cv(stage_id: int) -> CandidateStageCV:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )


async def _cleanup_generated(world: dict, users: list[int]) -> None:
    from app.models.cv_generated_document import CvGeneratedDocument

    await _cleanup_all(world, users)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CvGeneratedDocument).where(
                CvGeneratedDocument.candidate_id == world["candidate_id"]
            )
        )
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["enforced", "advisory"])
async def test_review_required_runs_in_background_then_the_queue_gets_the_approved_file(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, background_review, mode
) -> None:
    """`advisory` = produkcja 10.11.2026: ścisłe dowody wyłączone, kontrola AI włączona."""
    from app.services.cv_approval_worker import execute_review_job
    from app.services.cv_dl_accept_finalize import REVIEW_QUEUED_ACTION

    if mode == "advisory":
        monkeypatch.setenv("CV_SOURCE_EVIDENCE_ENFORCED", "false")
        monkeypatch.setenv("CV_FINAL_REVIEW_ENABLED", "true")
    world = await _seed_world()
    users: list[int] = []
    try:
        async with restore_cpro_sender():
            stage_id, hor, users, dl_id = await _accept_with_review(
                api_client, monkeypatch, world
            )

            # Akceptacja przeszła, kontrola czeka w kolejce na koszt DL-a.
            csv, (job,) = await _queued_review(stage_id)
            assert csv.branded_status == "draft"
            assert job.status == "queued"
            assert job.user_id == dl_id
            assert job.expected_revision == csv.edit_revision
            (queued,) = await _activities(stage_id, REVIEW_QUEUED_ACTION)
            assert queued.user_id == dl_id
            assert queued.details["review_id"] == job.id
            assert await _activities(stage_id, SKIPPED_ACTION) == []
            item = await _queue_item(api_client, hor, world)
            assert item["cv"]["draft"] is True
            assert item["cv"]["review_pending"] is True

            await execute_review_job(job.id)

            csv = await _stage_cv(stage_id)
            assert csv.branded_status == "finalized"
            assert csv.branded_finalized_by == dl_id
            assert csv.branded_render_metadata["content_review"]["reused"] is True
            background_review.assert_called_once()
            (finalized,) = await _activities(stage_id, "branded_cv_finalized")
            assert finalized.user_id == dl_id
            assert finalized.details["approved_via"] == APPROVED_VIA
            assert finalized.details["review_id"] == job.id
            item = await _queue_item(api_client, hor, world)
            assert item["cv"]["draft"] is False
            assert item["cv"]["review_pending"] is False
            res = await _download_like_the_queue(api_client, hor, stage_id)
            assert res.status_code == 200, res.text
            assert "SZKIC_" not in res.headers["content-disposition"]
    finally:
        await _cleanup_generated(world, users)


@pytest.mark.asyncio
async def test_enforced_review_with_findings_keeps_the_draft(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, background_review
) -> None:
    """Tryb wymuszony: recenzent nie potwierdził treści → szkic i plakietka."""
    from app.services.cv_approval_worker import execute_review_job
    from app.services.cv_generator_b2b.factual_verification import (
        FactualVerificationError,
    )

    background_review.side_effect = FactualVerificationError(
        ["roles[0]"], reason="unsupported", statuses={"roles[0]": "unsupported"}
    )
    world = await _seed_world()
    users: list[int] = []
    try:
        async with restore_cpro_sender():
            stage_id, hor, users, dl_id = await _accept_with_review(
                api_client, monkeypatch, world
            )
            _, (job,) = await _queued_review(stage_id)

            await execute_review_job(job.id)

            csv, (job,) = await _queued_review(stage_id)
            assert job.status == "rejected"
            assert csv.branded_status == "draft"
            assert await _activities(stage_id, "branded_cv_finalized") == []
            (skipped,) = await _activities(stage_id, SKIPPED_ACTION)
            assert skipped.user_id == dl_id
            assert skipped.details["reason"] == "review_rejected"
            assert skipped.details["review_id"] == job.id
            item = await _queue_item(api_client, hor, world)
            assert item["cv"]["draft"] is True
            assert item["cv"]["review_pending"] is False
            res = await _download_like_the_queue(api_client, hor, stage_id)
            assert "SZKIC_" in res.headers["content-disposition"]
    finally:
        await _cleanup_generated(world, users)


@pytest.mark.asyncio
async def test_edit_during_background_review_keeps_the_draft(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, background_review
) -> None:
    """Rekruter poprawia CV, gdy kontrola już biegnie: DL zaakceptował inną treść."""
    from app.services import cv_approval_worker
    from app.services.cv_approval_review import execute_approval_review

    edited = DRAFT_HTML.replace("Migracje", "Utrzymanie")

    async def edit_then_review(db, prepared, user_id):
        async with AsyncSessionLocal() as other:
            csv = await other.scalar(
                select(CandidateStageCV)
                .where(CandidateStageCV.id == csv_id)
                .with_for_update()
            )
            csv.branded_draft_html = edited
            csv.edit_revision += 1
            await other.commit()
        return await execute_approval_review(db, prepared, user_id)

    monkeypatch.setattr(cv_approval_worker, "execute_approval_review", edit_then_review)
    world = await _seed_world()
    users: list[int] = []
    try:
        async with restore_cpro_sender():
            stage_id, hor, users, dl_id = await _accept_with_review(
                api_client, monkeypatch, world
            )
            csv, (job,) = await _queued_review(stage_id)
            csv_id = csv.id

            await cv_approval_worker.execute_review_job(job.id)

            csv, (job,) = await _queued_review(stage_id)
            assert job.status == "verified"
            assert csv.branded_status == "draft"
            assert csv.branded_draft_html == edited
            assert await _activities(stage_id, "branded_cv_finalized") == []
            (skipped,) = await _activities(stage_id, SKIPPED_ACTION)
            assert skipped.details["reason"] == "draft_changed"
            item = await _queue_item(api_client, hor, world)
            assert item["cv"]["draft"] is True
            assert item["cv"]["review_pending"] is False
    finally:
        await _cleanup_generated(world, users)
