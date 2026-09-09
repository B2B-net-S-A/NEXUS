"""Explicit upload association is authorized before quota and survives parsing."""

from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from app.api import cv_generator_b2b as api
from app.models.user import User, UserRole


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context,denied,expected",
    [
        ({"candidate_id": 2, "stage_id": 3}, False, 202),
        ({"candidate_id": 2}, False, 202),
        ({}, False, 202),
        ({"stage_id": 3}, False, 422),
        ({"candidate_id": 99, "stage_id": 3}, False, 404),
        ({"candidate_id": 2, "stage_id": 3, "client_id": 9}, False, 422),
        ({"candidate_id": 2, "stage_id": 3}, True, 403),
    ],
)
async def test_upload_context_precedes_quota(monkeypatch, context, denied, expected):
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
    app.dependency_overrides[get_args(api.CandidateWriteAccess)[1].dependency] = (
        lambda: User(id=7, role=UserRole.admin)
    )
    guard = AsyncMock(side_effect=HTTPException(403) if denied else None)
    monkeypatch.setattr(api, "ensure_job_membership", guard)
    monkeypatch.setattr(api, "resolve_client_rule", AsyncMock(return_value=None))
    charge = AsyncMock(return_value=None)
    pending = AsyncMock(return_value=11)
    monkeypatch.setattr(api, "_charge_cv_generation_quota", charge)
    monkeypatch.setattr(api, "_create_pending_row", pending)
    worker = AsyncMock()
    monkeypatch.setattr(api, "_run_declared", worker)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/cv-generator/generate-upload",
            data=context,
            files={"cv_file": ("synthetic.pdf", b"fake CV", "application/pdf")},
        )
    assert response.status_code == expected, response.text
    if expected != 202:
        charge.assert_not_awaited()
        pending.assert_not_awaited()
        worker.assert_not_awaited()
    else:
        kwargs = pending.call_args.kwargs
        assert kwargs["candidate_id"] == context.get("candidate_id")
        assert kwargs["job_id"] == (4 if context.get("stage_id") else None)
        assert kwargs["client_id"] == (5 if context.get("stage_id") else None)
        worker.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_finalize_retains_authorized_context():
    row = SimpleNamespace(job_id=4, candidate_id=2, client_id=5)
    result = SimpleNamespace(
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
