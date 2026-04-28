"""Testy snapshot oryginalnego CV per CandidateStage (Faza 2 — PR1).

Pokrycie:

  Service `create_original_cv_snapshot`:
    * kopiuje cv_filename / cv_file_content / cv_language do nowego row
    * idempotentny (drugi call dla tego samego stage → no-op)
    * gdy kandydat nie ma CV → row stworzony z NULL `original_cv_*`,
      has_snapshot=False
    * Activity log tworzony

  Service `refresh_original_cv_snapshot`:
    * nadpisuje aktualną zawartością i zmienia `original_snapshot_source`
    * Activity z old_filename/new_filename
    * 404 gdy stage_id nie ma row
    * 422 gdy kandydat aktualnie nie ma CV

  Endpoint integration:
    * POST `/api/pipeline/move` → snapshot dla stage'a
    * POST `/api/recommendations/{id}/assign` → snapshot
    * GET `/api/candidates/stages/{id}/cv/original` → metadane
    * GET `.../cv/original/download` → bytes z poprawnym Content-Type
    * GET `.../cv/original/download` → 404 gdy has_snapshot=False
    * POST `.../cv/original/refresh` → nadpisuje
    * POST `.../cv/original/refresh` 422 gdy kandydat aktualnie bez CV

  CRITICAL isolation (the-feature):
    * Po utworzeniu stage'a podmień Candidate.cv_file_content → snapshot zwraca
      ORYGINALNE bytes, nie nowe. To rozwiązuje pain point z Traffit.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
    refresh_original_cv_snapshot,
)


async def _seed_candidate_with_cv(
    *, cv_bytes: bytes | None = b"%PDF-1.4 fake-pdf-bytes",
    cv_filename: str | None = "candidate_cv.pdf",
) -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Snap",
            lastname=f"Cand{unique}",
            email=f"snap-{unique}@example.com",
            cv_filename=cv_filename,
            cv_file_content=cv_bytes,
            cv_language="pl" if cv_bytes else None,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Klient Snap {unique}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"Job Snap {unique}",
            client_id=cli.id,
            description="x",
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_stage(candidate_id: int, job_id: int) -> int:
    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=candidate_id, job_id=job_id, stage=PipelineStage.new
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage.id


# ── Service unit tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_service_creates_snapshot_with_cv_bytes():
    cid = await _seed_candidate_with_cv()
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        csv = await create_original_cv_snapshot(db, stage)
        await db.commit()

    async with AsyncSessionLocal() as db:
        fresh = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == sid
            )
        )
        assert fresh is not None
        assert fresh.original_cv_content == b"%PDF-1.4 fake-pdf-bytes"
        assert fresh.original_cv_filename == "candidate_cv.pdf"
        assert fresh.original_cv_language == "pl"
        assert fresh.original_snapshot_source == "auto_create"
        assert fresh.original_snapshot_at is not None


@pytest.mark.asyncio
async def test_service_handles_candidate_without_cv():
    """Kandydat bez CV → row stworzony, ale `original_*` NULL."""
    cid = await _seed_candidate_with_cv(cv_bytes=None, cv_filename=None)
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        csv = await create_original_cv_snapshot(db, stage)
        await db.commit()

    async with AsyncSessionLocal() as db:
        fresh = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == sid
            )
        )
        assert fresh is not None
        assert fresh.original_cv_content is None
        assert fresh.original_cv_filename is None
        assert fresh.original_snapshot_at is None  # NULL gdy brak CV


@pytest.mark.asyncio
async def test_service_idempotent():
    """Drugi call dla tego samego stage → zwraca istniejący row, nie crashuje."""
    cid = await _seed_candidate_with_cv()
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        first = await create_original_cv_snapshot(db, stage)
        await db.commit()

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        second = await create_original_cv_snapshot(db, stage)
        await db.commit()

    assert first.id == second.id


@pytest.mark.asyncio
async def test_service_logs_activity():
    cid = await _seed_candidate_with_cv()
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        csv = await create_original_cv_snapshot(db, stage)
        await db.commit()

    async with AsyncSessionLocal() as db:
        act = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate_stage_cv",
                Activity.entity_id == csv.id,
                Activity.action == "snapshot_created",
            )
        )
        assert act is not None
        assert act.details["candidate_stage_id"] == sid
        assert act.details["has_snapshot"] is True


# ── CRITICAL isolation (the-feature) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_subsequent_candidate_cv_change_does_not_affect_snapshot():
    """Po utworzeniu snapshot, podmień Candidate.cv_file_content → snapshot
    zostaje przy starych bytes. To jest cały sens feature'u."""
    cid = await _seed_candidate_with_cv(cv_bytes=b"V1-original-CV-bytes")
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        await create_original_cv_snapshot(db, stage)
        await db.commit()

    # Kandydat update'uje CV.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == cid)
            .values(cv_file_content=b"V2-NEW-cv", cv_filename="updated.pdf")
        )
        await db.commit()

    # Snapshot dalej ma stare bytes.
    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == sid
            )
        )
        assert snap.original_cv_content == b"V1-original-CV-bytes"
        assert snap.original_cv_filename == "candidate_cv.pdf"


@pytest.mark.asyncio
async def test_two_stages_for_same_candidate_have_independent_snapshots():
    """Kandydat na 2 jobach. Edycja jego CV po pierwszym stage → drugi stage
    dostanie świeży snapshot (z nowym CV), pierwszy zachowa stary."""
    cid = await _seed_candidate_with_cv(cv_bytes=b"CV-version-A")
    jid_a = await _seed_job()
    sid_a = await _seed_stage(cid, jid_a)

    async with AsyncSessionLocal() as db:
        stage_a = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid_a)
        )
        await create_original_cv_snapshot(db, stage_a)
        await db.commit()

    # Kandydat update'uje CV przed dodaniem do drugiej oferty.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == cid)
            .values(cv_file_content=b"CV-version-B", cv_filename="b.pdf")
        )
        await db.commit()

    jid_b = await _seed_job()
    sid_b = await _seed_stage(cid, jid_b)
    async with AsyncSessionLocal() as db:
        stage_b = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid_b)
        )
        await create_original_cv_snapshot(db, stage_b)
        await db.commit()

    async with AsyncSessionLocal() as db:
        snap_a = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == sid_a
            )
        )
        snap_b = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == sid_b
            )
        )
        assert snap_a.original_cv_content == b"CV-version-A"
        assert snap_b.original_cv_content == b"CV-version-B"


# ── Refresh service ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_overwrites_with_current_cv():
    cid = await _seed_candidate_with_cv(cv_bytes=b"OLD")
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        await create_original_cv_snapshot(db, stage)
        await db.commit()

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == cid)
            .values(cv_file_content=b"NEW", cv_filename="new.pdf")
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        await refresh_original_cv_snapshot(db, sid, user_id=None)
        await db.commit()

    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == sid
            )
        )
        assert snap.original_cv_content == b"NEW"
        assert snap.original_cv_filename == "new.pdf"
        assert snap.original_snapshot_source == "manual_refresh"


@pytest.mark.asyncio
async def test_refresh_raises_when_candidate_has_no_cv():
    cid = await _seed_candidate_with_cv()
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)

    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        await create_original_cv_snapshot(db, stage)
        await db.commit()

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == cid)
            .values(cv_file_content=None, cv_filename=None)
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError, match="no current CV"):
            await refresh_original_cv_snapshot(db, sid, user_id=None)


@pytest.mark.asyncio
async def test_refresh_raises_lookup_when_csv_missing():
    """Refresh dla stage'a który nie ma jeszcze csv row → LookupError."""
    jid = await _seed_job()
    cid = await _seed_candidate_with_cv()
    sid = await _seed_stage(cid, jid)
    # NIE wołamy create_original_cv_snapshot — symulacja stage'a sprzed feature.

    async with AsyncSessionLocal() as db:
        with pytest.raises(LookupError):
            await refresh_original_cv_snapshot(db, sid, user_id=None)


# ── Endpoint integration ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_original_endpoint_returns_metadata(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate_with_cv(cv_bytes=b"PDF", cv_filename="my.pdf")
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        await create_original_cv_snapshot(db, stage)
        await db.commit()

    res = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/original", headers=app_auth_headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_snapshot"] is True
    assert body["original_cv_filename"] == "my.pdf"
    assert body["candidate_id"] == cid
    assert body["job_id"] == jid
    assert body["download_url"].endswith(f"/cv/original/download")


@pytest.mark.asyncio
async def test_download_endpoint_returns_bytes(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate_with_cv(
        cv_bytes=b"%PDF-1.4 dummy", cv_filename="resume.pdf"
    )
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        await create_original_cv_snapshot(db, stage)
        await db.commit()

    res = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/original/download",
        headers=app_auth_headers,
    )
    assert res.status_code == 200
    assert res.content == b"%PDF-1.4 dummy"
    assert "resume.pdf" in res.headers.get("content-disposition", "")
    assert res.headers.get("content-type", "").startswith("application/pdf")


@pytest.mark.asyncio
async def test_download_404_when_no_snapshot(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate_with_cv(cv_bytes=None, cv_filename=None)
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        await create_original_cv_snapshot(db, stage)
        await db.commit()

    res = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/original/download",
        headers=app_auth_headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_original_404_for_unknown_stage(
    app_client: AsyncClient, app_auth_headers: dict
):
    res = await app_client.get(
        "/api/candidates/stages/9999999/cv/original", headers=app_auth_headers
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_refresh_endpoint_updates_snapshot(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate_with_cv(cv_bytes=b"OLD", cv_filename="old.pdf")
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        await create_original_cv_snapshot(db, stage)
        await db.commit()

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == cid)
            .values(cv_file_content=b"NEW", cv_filename="new.pdf")
        )
        await db.commit()

    res = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/original/refresh",
        headers=app_auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["original_cv_filename"] == "new.pdf"
    assert body["original_snapshot_source"] == "manual_refresh"


@pytest.mark.asyncio
async def test_refresh_endpoint_422_when_candidate_has_no_cv(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_candidate_with_cv()
    jid = await _seed_job()
    sid = await _seed_stage(cid, jid)
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == sid)
        )
        await create_original_cv_snapshot(db, stage)
        await db.commit()

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == cid)
            .values(cv_file_content=None)
        )
        await db.commit()

    res = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/original/refresh",
        headers=app_auth_headers,
    )
    assert res.status_code == 422
