"""GET /api/pipeline/candidates/{candidate_id}/jobs/{job_id}/cv-share-tokens.

Link dla klienta leży na etapie SPRZED ruchu na „CV Wysłane", więc widok osoby
na późniejszym etapie pytał o listę per etap i dostawał pustkę, choć klient
miał działający link. Ta trasa zbiera linki ze WSZYSTKICH etapów pary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.cv_share_token import CVShareToken
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services.candidate_stage_cv_service import create_original_cv_snapshot
from tests._jarvis_helpers import make_user

_URL = "/api/pipeline/candidates/{c}/jobs/{j}/cv-share-tokens"


async def _seed() -> dict[str, int | str]:
    """Para (kandydat, rekrutacja) z dwoma etapami; linki leżą na PIERWSZYM."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Klient linki {unique}")
        db.add(cli)
        await db.flush()
        cand = Candidate(
            name="Linka",
            lastname=f"Test{unique}",
            email=f"linki-{unique}@example.com",
            cv_filename="cv.pdf",
            cv_file_content=b"%PDF-1.4 fake",
        )
        other = Candidate(
            name="Inna", lastname=f"Osoba{unique}", email=f"inna-{unique}@example.com"
        )
        db.add_all([cand, other])
        await db.flush()
        job = Job(title=f"Rekrutacja linki {unique}", client_id=cli.id, description="x")
        db.add(job)
        await db.flush()

        verified = CandidateStage(
            candidate_id=cand.id, job_id=job.id, stage=PipelineStage.verified
        )
        db.add(verified)
        await db.flush()
        await create_original_cv_snapshot(db, verified)
        sent = CandidateStage(
            candidate_id=cand.id, job_id=job.id, stage=PipelineStage.cv_sent
        )
        db.add(sent)
        await db.flush()

        csv_id = await db.scalar(
            select(CandidateStageCV.id).where(
                CandidateStageCV.candidate_stage_id == verified.id
            )
        )
        assert csv_id is not None
        now = datetime.now(timezone.utc)
        legacy_secret = f"legacy-secret-{unique}"
        db.add_all(
            [
                CVShareToken(
                    token=f"v2${unique}aa",
                    token_sha256=(unique * 8)[:64],
                    candidate_stage_cv_id=csv_id,
                    expires_at=now + timedelta(days=14),
                    created_at=now,
                ),
                CVShareToken(
                    token=legacy_secret,
                    candidate_stage_cv_id=csv_id,
                    expires_at=now + timedelta(days=14),
                    created_at=now - timedelta(days=1),
                    revoked=True,
                ),
            ]
        )
        await db.commit()
        return {
            "candidate_id": cand.id,
            "other_candidate_id": other.id,
            "job_id": job.id,
            "verified_stage_id": verified.id,
            "sent_stage_id": sent.id,
            "legacy_secret": legacy_secret,
        }


async def _headers_for(role: UserRole) -> dict[str, str]:
    _user_id, headers = await make_user(role)
    return headers


@pytest.mark.asyncio
async def test_lists_links_from_every_stage_row_without_secrets(
    app_client: AsyncClient, app_auth_headers: dict
):
    seeded = await _seed()
    res = await app_client.get(
        _URL.format(c=seeded["candidate_id"], j=seeded["job_id"]),
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    items = body["items"]
    assert len(items) == 2
    # Linki leżą na etapie SPRZED ruchu — nie na bieżącym „CV Wysłane".
    assert {i["stage_id"] for i in items} == {seeded["verified_stage_id"]}
    assert all(i["stage_name"] for i in items)
    # Najnowszy pierwszy; te same pola co lista per etap.
    assert items[0]["is_v2"] is True and items[0]["revoked"] is False
    assert items[1]["is_v2"] is False and items[1]["revoked"] is True
    for field in ("token_preview", "expires_at", "view_count", "created_at"):
        assert field in items[0]
    # Nigdy sekret: także dla linku legacy, którego klucz główny JEST sekretem.
    assert str(seeded["legacy_secret"]) not in res.text
    assert all(i["share_url_suffix"] is None for i in items)
    # Para bez CV firmowego: jawne „none", nie brak pola.
    assert body["branded_cv"] == {
        "status": "none",
        "stage_id": None,
        "stage_name": None,
        "finalized_at": None,
    }


async def _set_branded(stage_id: int, status: str) -> None:
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )
        if csv is None:
            # Etap po ruchu nie ma wiersza CV — zakłada go dopiero odczyt.
            stage = await db.get(CandidateStage, stage_id)
            assert stage is not None
            csv = CandidateStageCV(
                candidate_stage_id=stage_id,
                candidate_id=stage.candidate_id,
                job_id=stage.job_id,
            )
            db.add(csv)
        csv.branded_status = status
        csv.branded_draft_html = "<p>cv</p>"
        csv.branded_finalized_at = (
            datetime.now(timezone.utc) if status == "finalized" else None
        )
        await db.commit()


@pytest.mark.asyncio
async def test_branded_cv_summary_points_at_the_stage_that_holds_it(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Po „CV Wysłane" bieżący etap nie ma CV firmowego — sfinalizowane leży wcześniej."""
    seeded = await _seed()
    await _set_branded(int(seeded["verified_stage_id"]), "finalized")
    res = await app_client.get(
        _URL.format(c=seeded["candidate_id"], j=seeded["job_id"]),
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    branded = res.json()["branded_cv"]
    assert branded["status"] == "finalized"
    assert branded["stage_id"] == seeded["verified_stage_id"]
    assert branded["stage_name"]
    assert branded["finalized_at"] is not None


@pytest.mark.asyncio
async def test_auto_draft_on_a_later_stage_does_not_hide_the_finalized_cv(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`GET …/cv/branded` zakłada szkic przy odczycie — nie może przykryć wysłanego CV."""
    seeded = await _seed()
    await _set_branded(int(seeded["verified_stage_id"]), "finalized")
    await _set_branded(int(seeded["sent_stage_id"]), "draft")
    res = await app_client.get(
        _URL.format(c=seeded["candidate_id"], j=seeded["job_id"]),
        headers=app_auth_headers,
    )
    branded = res.json()["branded_cv"]
    assert branded["status"] == "finalized"
    assert branded["stage_id"] == seeded["verified_stage_id"]


@pytest.mark.asyncio
async def test_draft_only_pair_reports_a_draft_without_a_finalized_date(
    app_client: AsyncClient, app_auth_headers: dict
):
    seeded = await _seed()
    await _set_branded(int(seeded["sent_stage_id"]), "draft")
    res = await app_client.get(
        _URL.format(c=seeded["candidate_id"], j=seeded["job_id"]),
        headers=app_auth_headers,
    )
    branded = res.json()["branded_cv"]
    assert branded["status"] == "draft"
    assert branded["stage_id"] == seeded["sent_stage_id"]
    assert branded["finalized_at"] is None


@pytest.mark.asyncio
async def test_per_stage_list_of_the_current_stage_is_empty(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Dowód, po co jest ta trasa: bieżący etap nie ma CV ani linków."""
    seeded = await _seed()
    res = await app_client.get(
        f"/api/candidates/stages/{seeded['sent_stage_id']}/cv/share-tokens",
        headers=app_auth_headers,
    )
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        assert res.json() == []


@pytest.mark.asyncio
async def test_candidate_outside_the_recruitment_is_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    seeded = await _seed()
    res = await app_client.get(
        _URL.format(c=seeded["other_candidate_id"], j=seeded["job_id"]),
        headers=app_auth_headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_requires_authentication(app_client: AsyncClient):
    seeded = await _seed()
    res = await app_client.get(
        _URL.format(c=seeded["candidate_id"], j=seeded["job_id"])
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_same_gate_as_the_per_stage_list(app_client: AsyncClient):
    """Obie listy mają tę samą bramkę — i od 23.09.2026 rekruter spoza zespołu
    przechodzi ją na obu (decyzja Artura: rekrutację widzi każdy). Stara rola
    podglądu ``user`` dostaje tę samą odmowę na obu."""
    seeded = await _seed()
    headers = await _headers_for(UserRole.recruiter)
    per_stage = await app_client.get(
        f"/api/candidates/stages/{seeded['verified_stage_id']}/cv/share-tokens",
        headers=headers,
    )
    job_wide = await app_client.get(
        _URL.format(c=seeded["candidate_id"], j=seeded["job_id"]), headers=headers
    )
    assert per_stage.status_code == 200, per_stage.text
    assert job_wide.status_code == 200, job_wide.text
    assert len(job_wide.json()["items"]) == 2
    assert str(seeded["legacy_secret"]) not in job_wide.text

    viewer = await _headers_for(UserRole.user)
    viewer_per_stage = await app_client.get(
        f"/api/candidates/stages/{seeded['verified_stage_id']}/cv/share-tokens",
        headers=viewer,
    )
    viewer_job_wide = await app_client.get(
        _URL.format(c=seeded["candidate_id"], j=seeded["job_id"]), headers=viewer
    )
    assert viewer_per_stage.status_code in (403, 404)
    assert viewer_job_wide.status_code == viewer_per_stage.status_code
    assert str(seeded["legacy_secret"]) not in viewer_job_wide.text


def test_route_shares_the_scope_guard_with_the_per_stage_list() -> None:
    import inspect

    from app.api import candidate_stage_cv as module

    source = inspect.getsource(module.list_cv_share_tokens_for_recruitment)
    assert "ensure_job_read_access" in source
    assert "CandidateDocumentAccess" in source
