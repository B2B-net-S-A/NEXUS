"""Explicit upload association is authorized before quota and survives parsing."""

from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock
from io import BytesIO
from docx import Document

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.api import cv_generator_b2b as api, recruitment_access
from app.models.user import User, UserRole


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context,non_member,expected",
    [
        ({"candidate_id": 2, "stage_id": 3}, False, 202),
        ({"candidate_id": 2, "client_id": 5}, False, 202),
        ({"client_id": 5}, False, 202),
        # Generator v3: bez rekrutacji klient jest wymagany (jak `/generate`).
        ({"candidate_id": 2}, False, 422),
        ({}, False, 422),
        ({"stage_id": 3}, False, 422),
        ({"candidate_id": 99, "stage_id": 3}, False, 404),
        ({"candidate_id": 2, "stage_id": 3, "client_id": 9}, False, 422),
        # „Wszyscy mogą” (10.09.2026): osoba spoza zespołu rekrutacji też wiąże
        # upload z rekrutacją — członkostwo nie jest w ogóle sprawdzane.
        ({"candidate_id": 2, "stage_id": 3}, True, 202),
    ],
)
async def test_upload_context_precedes_quota(
    monkeypatch, context, non_member, expected
):
    app = FastAPI()
    app.include_router(api.router)
    app.state.limiter = api.limiter
    db = AsyncMock()

    async def get(model, ident):
        if model is api.CandidateStage:
            return SimpleNamespace(id=3, candidate_id=2, job_id=4)
        if model is api.Job:
            return SimpleNamespace(id=4, client_id=5)
        if model is api.Client:
            return SimpleNamespace(id=5, cv_content_mode_cap=None)
        return SimpleNamespace(id=ident)

    db.get.side_effect = get
    app.dependency_overrides[api.get_db] = lambda: db
    role = UserRole.recruiter if non_member else UserRole.admin
    app.dependency_overrides[get_args(api.CandidateWriteAccess)[1].dependency] = (
        lambda: User(id=7, role=role, roles=[role.value])
    )
    membership = AsyncMock(return_value=False)
    monkeypatch.setattr(recruitment_access, "is_member_of_job", membership)
    monkeypatch.setattr(api, "resolve_client_rule", AsyncMock(return_value=None))
    charge = AsyncMock(return_value=None)
    pending = AsyncMock(return_value=11)
    monkeypatch.setattr(api, "_charge_cv_generation_quota", charge)
    monkeypatch.setattr(api, "_create_pending_row", pending)
    worker = AsyncMock()
    from app.services.cv_generator_b2b import durable_jobs

    async def persist(*args, **kwargs):
        await kwargs["charge"]()
        return 21

    persisted = AsyncMock(side_effect=persist)
    monkeypatch.setattr(durable_jobs, "persist_job", persisted)
    monkeypatch.setattr(durable_jobs, "execute_job", worker)
    source = BytesIO()
    document = Document()
    document.add_paragraph("Audyt Testowy. Programista Python.")
    document.save(source)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/cv-generator/generate-upload",
            data=context,
            files={
                "cv_file": (
                    "synthetic.docx",
                    source.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    assert response.status_code == expected, response.text
    membership.assert_not_awaited()
    if expected != 202:
        charge.assert_not_awaited()
        pending.assert_not_awaited()
        worker.assert_not_awaited()
    else:
        kwargs = pending.call_args.kwargs
        assert kwargs["candidate_id"] == context.get("candidate_id")
        assert kwargs["job_id"] == (4 if context.get("stage_id") else None)
        assert kwargs["client_id"] == 5
        worker.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_finalize_retains_authorized_context():
    row = SimpleNamespace(job_id=4, candidate_id=2, client_id=5)
    result = SimpleNamespace(
        docx_bytes=b"synthetic-docx",
        render_payload={"name": "Synthetic"},
        candidate_name="Synthetic",
        job_id=None,
        filename="cv.docx",
        warnings=[],
    )
    await api._finalize_success(
        SimpleNamespace(get=AsyncMock(return_value=row)), 11, result=result
    )
    assert (row.candidate_id, row.job_id, row.client_id) == (2, 4, 5)
