"""Generator v3: ręcznie wygenerowane CV podpina się jako szkic CV etapu.

Decyzja Artura: podpięcie ZAWSZE, gdy etap nie ma jeszcze szkicu — także
u osoby spoza zespołu rekrutacji. Robi to worker (przeżywa zamknięcie karty
i ``recovery_loop``) tą samą operacją co auto-CV
(``cv_auto_generate.attach_as_stage_draft``): szkic, nigdy zatwierdzenie.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401
from app.api import cv_generator_b2b as api
from app.core.database import AsyncSessionLocal
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.user import User, UserRole
from app.services import cv_auto_generate as auto
from tests.test_cv_auto_generate import _fake_attach, _headers, _stage_cv, _world
from tests.test_cv_auto_generate_central_policies import (
    _docx,
    _documents,
    _run_worker,
    _stub_generation,
    _worker_harness,
)
from tests.test_pending_gate_removed import pv_client  # noqa: F401


# ── worker ──────────────────────────────────────────────────────────────────


async def test_worker_attaches_the_first_ready_document_to_the_stage(monkeypatch):
    rule, _rendered, _quota, _pending = _worker_harness(monkeypatch, first_ready=False)
    attach = AsyncMock()
    monkeypatch.setattr(api, "_attach_manual_stage_draft", attach)
    await _run_worker(rule, attach_stage_draft=True)
    attach.assert_awaited_once_with(stage_id=3, user_id=7, generated_id=11)


async def test_worker_does_not_attach_without_the_flag(monkeypatch):
    rule, _rendered, _quota, _pending = _worker_harness(monkeypatch, first_ready=False)
    attach = AsyncMock()
    monkeypatch.setattr(api, "_attach_manual_stage_draft", attach)
    await _run_worker(rule)
    attach.assert_not_awaited()


async def test_resumed_job_repeats_the_idempotent_attach(monkeypatch):
    """Wznowienie z gotowym pierwszym dokumentem (proces padł między commitem
    dokumentu a podpięciem): podpięcie jest powtarzane — idempotentne, bo
    `attach_as_stage_draft` podpina wyłącznie etap bez szkicu."""
    rule, _rendered, _quota, _pending = _worker_harness(monkeypatch, first_ready=True)
    attach = AsyncMock()
    monkeypatch.setattr(api, "_attach_manual_stage_draft", attach)
    await _run_worker(rule, attach_stage_draft=True)
    attach.assert_awaited_once_with(stage_id=3, user_id=7, generated_id=11)


async def test_resumed_job_without_the_flag_does_not_attach(monkeypatch):
    rule, _rendered, _quota, _pending = _worker_harness(monkeypatch, first_ready=True)
    attach = AsyncMock()
    monkeypatch.setattr(api, "_attach_manual_stage_draft", attach)
    await _run_worker(rule)
    attach.assert_not_awaited()


# ── operacja podpięcia (prawdziwy Postgres) ─────────────────────────────────


async def _manual_doc(world: dict, *, created_by: int) -> int:
    async with AsyncSessionLocal() as db:
        row = CvGeneratedDocument(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            client_id=world["client_id"],
            candidate_name="Ręczne CV",
            language="pl",
            mode="new",
            content_mode="polished",
            filename="manual.docx",
            status="ready",
            render_payload={"name": "Ręczne CV"},
            created_by=created_by,
            origin="manual",
            stage_id=world["stage_id"],
        )
        db.add(row)
        await db.commit()
        return row.id


async def _outsider() -> int:
    import uuid

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"cv-outsider-{uuid.uuid4().hex[:8]}@example.com",
            name="Spoza zespołu",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def test_manual_document_of_an_outsider_becomes_the_stage_draft(monkeypatch):
    world = await _world()
    csv_id = await _stage_cv(world)
    outsider = await _outsider()
    doc_id = await _manual_doc(world, created_by=outsider)
    calls = _fake_attach(monkeypatch)

    await api._attach_manual_stage_draft(
        stage_id=world["stage_id"], user_id=outsider, generated_id=doc_id
    )
    assert calls == [
        {"action": "branded_cv_attached_after_generation", "user_id": outsider}
    ]
    async with AsyncSessionLocal() as db:
        csv = await db.get(CandidateStageCV, csv_id)
        assert csv.generated_document_id == doc_id
        assert csv.branded_status == "draft"  # nigdy zatwierdzenie


async def test_existing_stage_draft_is_never_overwritten(monkeypatch):
    world = await _world()
    await _stage_cv(world, status="draft")
    doc_id = await _manual_doc(world, created_by=world["user_id"])
    calls = _fake_attach(monkeypatch)
    assert (
        await auto.attach_as_stage_draft(
            stage_id=world["stage_id"],
            user_id=world["user_id"],
            generated_id=doc_id,
            activity_action="branded_cv_attached_after_generation",
        )
        is False
    )
    assert calls == []


# ── upload z etapem ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_with_stage_records_it_and_attaches_in_the_worker(
    pv_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    seen = _stub_generation(monkeypatch, world)
    response = await pv_client.post(
        "/api/cv-generator/generate-upload",
        headers=_headers(world["user_id"]),
        data={
            "candidate_id": str(world["candidate_id"]),
            "stage_id": str(world["stage_id"]),
            # Dawne pola kafelków — przyjmowane i ignorowane.
            "must_requirements": "Python",
            "nice_requirements": "Go",
        },
        files={
            "cv_file": (
                "plik.docx",
                _docx(),
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 202, response.text
    [row] = await _documents(world)
    assert (row.mode, row.stage_id, row.job_id) == (
        "upload",
        world["stage_id"],
        world["job_id"],
    )
    [job] = seen["persisted"]
    assert job["inputs"]["attach_stage_id"] == world["stage_id"]
    payload = job["inputs"]["payload"]
    assert (payload.must_requirements, payload.nice_requirements) == ("", "")


@pytest.mark.asyncio
async def test_upload_without_stage_has_no_attach(pv_client: AsyncClient, monkeypatch):
    monkeypatch.setattr(api.limiter, "enabled", False)
    world = await _world()
    seen = _stub_generation(monkeypatch, world)
    response = await pv_client.post(
        "/api/cv-generator/generate-upload",
        headers=_headers(world["user_id"]),
        data={"client_id": str(world["client_id"])},
        files={"cv_file": ("plik.docx", _docx(), "application/octet-stream")},
    )
    assert response.status_code == 202, response.text
    [job] = seen["persisted"]
    assert "attach_stage_id" not in job["inputs"]
    assert "languages" not in job["inputs"]
