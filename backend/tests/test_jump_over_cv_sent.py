"""Przeskok ponad „CV wysłane” zamknięty (decyzja Artura 24.11.2026).

Ruch z kolumny przed wysyłką od razu na „Rozmowę u klienta”, „Umowę” albo
„Zatrudnionego” przechodzi te same bramki co wejście na „CV wysłane”: wysyła
osoba z `recruitment_manage` ze stawką do klienta, QC CV liczy się tak samo,
u Nordei reguły Cpro — także `/bulk-move`. Osoby w testach są fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from tests.test_pipeline_v4_claim_and_rules import (
    _add,
    _cleanup,
    _login,
    _seed_candidate,
    _seed_job,
    _seed_user,
)

pytestmark = pytest.mark.asyncio


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


async def _to_verified(api_client, headers, job_id: int, cand_id: int) -> None:
    await _add(api_client, headers, job_id, cand_id, "manual_search")
    moved = await api_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={"candidate_id": cand_id, "job_id": job_id, "stage": "verified"},
    )
    assert moved.status_code == 200, moved.text


@pytest.mark.parametrize("target", ["client_interview", "acceptance"])
async def test_recruiter_cannot_jump_over_cv_sent(api_client, target):
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(rec_id)
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    try:
        await _to_verified(api_client, rec_h, job_id, cand_id)
        jump = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": target,
            },
        )
        assert jump.status_code == 403, jump.text
    finally:
        await _cleanup([cand_id], job_id)


async def test_recruiter_cannot_jump_to_hired(api_client):
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(rec_id)
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    try:
        await _to_verified(api_client, rec_h, job_id, cand_id)
        jump = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "hired"},
        )
        assert jump.status_code in (403, 409), jump.text
        async with AsyncSessionLocal() as db:
            stages = (
                await db.scalars(
                    select(CandidateStage.stage).where(
                        CandidateStage.candidate_id == cand_id,
                        CandidateStage.job_id == job_id,
                    )
                )
            ).all()
        assert PipelineStage.hired not in stages
    finally:
        await _cleanup([cand_id], job_id)


async def test_bulk_move_cannot_jump_over_cv_sent(api_client):
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(rec_id)
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    try:
        await _to_verified(api_client, rec_h, job_id, cand_id)
        jump = await api_client.post(
            "/api/pipeline/bulk-move",
            headers=rec_h,
            json={
                "candidate_ids": [cand_id],
                "job_id": job_id,
                "stage": "client_interview",
            },
        )
        assert jump.status_code == 403, jump.text
    finally:
        await _cleanup([cand_id], job_id)


async def test_delivery_lead_jumps_only_with_client_rate(api_client):
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, _ = await _seed_job(rec_id, collaborator_ids=(dl_id,))
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    dl_h = await _login(api_client, dl_email, dl_pw)
    move = {"candidate_id": cand_id, "job_id": job_id, "stage": "client_interview"}
    try:
        await _to_verified(api_client, rec_h, job_id, cand_id)
        no_rate = await api_client.post("/api/pipeline/move", headers=dl_h, json=move)
        assert no_rate.status_code == 422, no_rate.text
        sent = await api_client.post(
            "/api/pipeline/move",
            headers=dl_h,
            json={**move, "client_rate_value": "175", "client_rate_unit": "hourly"},
        )
        assert sent.status_code == 200, sent.text
        assert Decimal(str(sent.json()["client_rate_value"])) == Decimal("175")
        # Dalej od „Rozmowy u klienta” to już nie wysyłka — rekruter przesuwa.
        back = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={**move, "stage": "cv_sent"},
        )
        assert back.status_code == 200, back.text
        again = await api_client.post("/api/pipeline/move", headers=rec_h, json=move)
        assert again.status_code == 200, again.text
    finally:
        await _cleanup([cand_id], job_id)


async def test_jump_over_cv_sent_runs_cv_qc(api_client, monkeypatch):
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", False)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, _ = await _seed_job(rec_id, collaborator_ids=(dl_id,))
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    dl_h = await _login(api_client, dl_email, dl_pw)
    try:
        await _to_verified(api_client, rec_h, job_id, cand_id)
        jump = await api_client.post(
            "/api/pipeline/move",
            headers=dl_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "client_interview",
                "client_rate_value": "175",
                "client_rate_unit": "hourly",
            },
        )
        assert jump.status_code == 409, jump.text
        assert jump.json()["detail"]["code"] == "CV_QC_FAILED"
    finally:
        await _cleanup([cand_id], job_id)


async def test_jump_over_cv_sent_at_nordea_needs_the_delivery_lead(
    api_client, monkeypatch
):
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    job_id, client_id = await _seed_job(rec_id)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(client_id))
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    try:
        await _to_verified(api_client, rec_h, job_id, cand_id)
        jump = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "client_interview",
            },
        )
        assert jump.status_code == 403, jump.text
    finally:
        await _cleanup([cand_id], job_id)
