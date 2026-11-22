"""Przełącznik układu CV etapu i PDF w układzie „Nowe CV” (22.11.2026).

- GET niesie układ, flagę i domyślny układ z reguły klienta,
- PATCH …/cv/layout przełącza układ bez generowania od nowa; zatwierdzona,
  niewysłana wersja przełącza się razem z CV; po „CV wysłane” 409,
- PDF szkicu i wersji idzie z renderu nowego CV, gdy układ to „Nowe CV”.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client_cv_rule import ClientCvRule
from app.models.cv_document_version import CvDocumentVersion
from app.models.job import Job
from app.services.cv_new_pdf import NewCvPdf
from tests.test_candidate_stage_cv_branded import _seed_draft, _seed_full_stage

HTML = (
    "<h1>Tester – Jan Przykładowy</h1><hr>"
    '<h2 data-cv-section="why_points">Dlaczego nasz kandydat?</h2>'
    "<ul><li>Ponad 8 lat w QA.</li></ul>"
    '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie danych.</p>'
)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)


async def _csv(sid: int) -> CandidateStageCV:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )


@pytest.mark.asyncio
async def test_flag_off_hides_layout_and_refuses_switch(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    got = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    assert got.status_code == 200
    assert got.json()["new_layout_enabled"] is False
    assert got.json()["cv_layout"] == "classic"
    res = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "new"},
        headers=app_auth_headers,
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_client_rule_sets_default_layout_for_the_generator(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid, _, job_id = await _seed_full_stage()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        db.add(
            ClientCvRule(
                client_id=job.client_id,
                confirmed_at=datetime.now(timezone.utc),
                cv_layout="new",
            )
        )
        await db.commit()
    got = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "none"
    assert body["new_layout_enabled"] is True
    assert body["default_layout"] == "new"


@pytest.mark.asyncio
async def test_switch_layout_keeps_content_and_logs_activity(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    before = await _csv(sid)
    res = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "new"},
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["cv_layout"] == "new"
    after = await _csv(sid)
    assert after.cv_layout == "new"
    assert after.branded_draft_html == before.branded_draft_html
    assert after.edit_revision == before.edit_revision
    async with AsyncSessionLocal() as db:
        logged = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate_stage_cv",
                Activity.entity_id == after.id,
                Activity.action == "cv_layout_changed",
            )
        )
    assert logged is not None
    assert logged.details["from"] == "classic"
    assert logged.details["to"] == "new"


@pytest.mark.asyncio
async def test_switch_on_empty_stage_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    res = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "new"},
        headers=app_auth_headers,
    )
    assert res.status_code in (404, 409)


@pytest.mark.asyncio
async def test_switch_after_send_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, monkeypatch
):
    from app.services import new_cv_company_cv

    async def sent(db, csv):
        return True

    monkeypatch.setattr(new_cv_company_cv, "locked_after_send", sent)
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    res = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "new"},
        headers=app_auth_headers,
    )
    assert res.status_code == 409
    assert "u klienta" in res.json()["detail"]
    assert (await _csv(sid)).cv_layout == "classic"


@pytest.mark.asyncio
async def test_approved_unsent_version_switches_with_the_cv(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        csv.branded_status = "finalized"
        csv.branded_finalized_at = datetime.now(timezone.utc)
        db.add(
            CvDocumentVersion(
                candidate_stage_cv_id=csv.id,
                version=csv.branded_version,
                content_html=HTML,
                content_sha256="0" * 64,
                template="standard",
                language="pl",
                cv_layout="classic",
                approved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    res = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "new"},
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    async with AsyncSessionLocal() as db:
        version = await db.scalar(
            select(CvDocumentVersion).where(
                CvDocumentVersion.candidate_stage_cv_id == (await _csv(sid)).id
            )
        )
    assert version.cv_layout == "new"


@pytest.mark.asyncio
async def test_draft_pdf_uses_new_layout_render(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, monkeypatch
):
    from app.api import cv_pdf_preview

    seen: dict = {}

    async def fake_render(content_html, **kwargs):
        seen["html"] = content_html
        seen.update(kwargs)
        return NewCvPdf(b"%PDF-new", True, 10.0, (), ())

    async def classic_must_not_run(*args, **kwargs):
        raise AssertionError("klasyczny PDF przy układzie Nowe CV")

    monkeypatch.setattr(cv_pdf_preview, "render_new_cv_pdf", fake_render)
    monkeypatch.setattr(cv_pdf_preview, "pdf_from_docx", classic_must_not_run)
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "new"},
        headers=app_auth_headers,
    )
    csv = await _csv(sid)
    res = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/branded/preview-pdf",
        json={"expected_revision": csv.edit_revision, "content_html": HTML},
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    assert res.content == b"%PDF-new"
    assert res.headers["x-cv-layout"] == "new"
    assert res.headers["x-cv-page1-font"] == "10"
    assert "Wyrażam zgodę" in seen["html"]
    assert seen["language"] == "pl"
