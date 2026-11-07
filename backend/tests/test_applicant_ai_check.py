"""„Sprawdź w CV” przy zgłoszeniu z brakiem „musi mieć” (07.11.2026).

Kolumna „Nowi” zwija zgłoszenia, którym brakuje słowa krytycznego w CV
(rekrutacja 789196: 11 z 12, głównie „Agentic AI” i „RAG”). Trasa ocenia
zgłoszenie tą samą regułą co przegląd AI i zapisuje wynik przy karcie pod
``entry_meta.ai_check``, nie gubiąc rodzaju wejścia (portal, link).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services import application_screening as screening
from tests.test_pipeline_membership_gate import (
    _seed_candidate,
    _seed_job,
    _seed_recruiter,
)
from tests.test_portal_application import _place, _posting


async def _fits(db, *, job, candidate, cv_text, use_model):
    return screening.ScreeningResult(
        verdict=screening.VERDICT_FITS,
        must_found=2,
        must_total=2,
        reasons=[{"text": "Budował agentów LLM", "quote": "agent LLM"}],
        model="test-model",
    )


@pytest.mark.asyncio
async def test_check_keeps_portal_and_marks_fits(app_client, monkeypatch):
    from app.models.recruitment_process import RecruitmentProcess

    monkeypatch.setattr(screening, "assess", _fits)
    headers, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=uid)
    cand = await _seed_candidate()
    ad_id = str(uuid.uuid4())
    await _posting(job_id, ad_id)
    assert (await _place(cand, ad_id=ad_id)).outcome == "added"

    resp = await app_client.post(
        f"/api/jobs/{job_id}/applicants/{cand}/ai-check", headers=headers
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["badge"]["verdict"] == "fits"
    assert body["reasons"][0]["quote"] == "agent LLM"
    async with AsyncSessionLocal() as db:
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == cand,
                RecruitmentProcess.job_id == job_id,
            )
        )
        assert process.entry_meta["kind"] == "portal_application"
        assert process.entry_meta["portal"] == "justjoinit"
        assert process.entry_meta["ai_check"]["verdict"] == "fits"


@pytest.mark.asyncio
async def test_check_refuses_person_who_did_not_apply(app_client, monkeypatch):
    monkeypatch.setattr(screening, "assess", _fits)
    headers, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=uid)
    cand = await _seed_candidate()

    resp = await app_client.post(
        f"/api/jobs/{job_id}/applicants/{cand}/ai-check", headers=headers
    )

    assert resp.status_code == 404


def test_badge_reads_nested_check_but_not_garbage():
    from app.services.process_entry_meta import application_screening_badge

    check = screening.entry_meta(
        screening.ScreeningResult(verdict="fits", must_found=1, must_total=1, model="m")
    )
    assert (
        application_screening_badge({"kind": "portal_application", "ai_check": check})[
            "verdict"
        ]
        == "fits"
    )
    assert application_screening_badge({"kind": "portal_application"}) is None
    assert (
        application_screening_badge({"kind": "portal_application", "ai_check": "x"})
        is None
    )
