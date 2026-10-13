"""Ogłoszenie na portale i strona kariery — poprawki po audycie 48 h, trasy z bazą.

- „Przygotuj ogłoszenie” z okna, które nie widziało istniejącego ogłoszenia
  (``expected_updated_at`` puste), dostaje 409 i niczego nie nadpisuje;
- ręczna poprawka zachowuje „3.5 roku”;
- rekrutacji z ogłoszeniem oznaczonym jako wiszące na portalu nie da się
  usunąć (409), po „Zdjęte z portalu” — tak;
- zapis opisu kariery wycina znaki sterujące kierunkiem tekstu (U+202E).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.job_ad_publication import JobAdPublication
from tests.test_career_links_api import _owner_with_job
from tests.test_job_ads_api import _model

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api() -> AsyncClient:
    from app.core.rate_limit import limiter
    from app.main import app

    limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


# ── Pierwsze „Przygotuj” przy istniejącym ogłoszeniu ────────────────────────


async def test_prepare_from_a_window_without_the_ad_does_not_overwrite_it(
    api: AsyncClient, monkeypatch
):
    """Dwie osoby otwierają okno rekrutacji bez ogłoszenia. Pierwsza je
    przygotowuje i poprawia, druga klika „Przygotuj ogłoszenie” — jej okno
    wysyła pustą wersję. Serwer odmawia, zanim zawoła model."""
    _, headers, job_id = await _owner_with_job(api)
    _model(monkeypatch)
    first = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate", json={"lang": "pl"}, headers=headers
    )
    assert first.status_code == 200, first.text
    ad = first.json()["ad"]
    edited = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={
            "content": {**ad["content"], "about": "Poprawka pierwszej osoby."},
            "tech": ad["tech"],
            "expected_updated_at": ad["updated_at"],
        },
        headers=headers,
    )
    assert edited.status_code == 200, edited.text

    calls = _model(monkeypatch)
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate",
        json={"lang": "pl", "expected_updated_at": None},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "job_ad_changed"
    assert "przygotował" in detail["message"]
    assert calls == []

    after = (await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)).json()
    assert after["ad"]["content"]["about"] == "Poprawka pierwszej osoby."


async def test_manual_edit_keeps_a_number_with_a_dot(api: AsyncClient, monkeypatch):
    _, headers, job_id = await _owner_with_job(api)
    _model(monkeypatch)
    ad = (
        await api.post(
            f"/api/jobs/{job_id}/portal-ad/generate",
            json={"lang": "pl"},
            headers=headers,
        )
    ).json()["ad"]
    requirements = ["3.5 roku doświadczenia w Javie", "2.5+ years with Kubernetes"]
    resp = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={
            "content": {**ad["content"], "requirements": requirements},
            "tech": ad["tech"],
            "expected_updated_at": ad["updated_at"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ad"]["content"]["requirements"] == requirements


# ── Usunięcie rekrutacji z ogłoszeniem na portalu ───────────────────────────


async def _seed_deletable_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Ws09DeleteClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Ws09-Delete-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def test_job_with_an_ad_on_a_portal_is_not_deleted(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Kaskada skasowałaby jedyny ślad, gdzie wisi ręcznie wklejone
    ogłoszenie — a NEXUS go z portalu nie zdejmie."""
    job_id = await _seed_deletable_job()
    async with AsyncSessionLocal() as db:
        db.add(
            JobAdPublication(
                job_id=job_id,
                portal="pracuj",
                url=None,
                content_hash="0" * 64,
                published_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    resp = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "job_has_ad_on_portal"
    assert detail["portals"] == ["pracuj"]
    assert "Zdjęte z portalu" in detail["message"]

    async with AsyncSessionLocal() as db:
        row = await db.get(JobAdPublication, (job_id, "pracuj"))
        row.removed_at = datetime.now(timezone.utc)
        await db.commit()

    resp = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert resp.status_code == 204, resp.text


# ── Opis na stronie kariery ─────────────────────────────────────────────────


async def test_career_description_is_saved_without_direction_overrides(
    api: AsyncClient,
):
    """„‮łz 081‬” przeglądarka pokazuje jako „180 zł”, a kontrola
    porównuje tekst bez znaków formatujących („łz 081”) i go przepuszczała."""
    _, headers, job_id = await _owner_with_job(api)
    resp = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={
            "public_title": "Java‮ Developer",
            "subtitle": "Platforma ‮łz 081‬ płatności",
            "about": "Oferujemy ‮łz 081‬ na godzinę.\n\nZespół 6 osób.",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["public_title"] == "Java Developer"
    assert body["subtitle"] == "Platforma łz 081 płatności"
    assert body["about"] == "Oferujemy łz 081 na godzinę.\n\nZespół 6 osób."
