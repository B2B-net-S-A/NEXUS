"""Ogłoszenie gotowe zaraz po „Utwórz” (23.11.2026).

Kontrakt ``docs/claude/rekrutacja-tworzenie/ogloszenie-przy-utworzeniu.md``:

- utworzenie rekrutacji zostawia treść ogłoszenia, gdy model odpowiedział
  (efekt po commicie, nic w transakcji tworzenia);
- awaria albo brak modelu nie psuje tworzenia i nie zapisuje złożenia z pól —
  zostaje noc i „Przygotuj”;
- język: „English …” w „Języku pracy” = EN, reszta po polsku;
- krok „Ogłoszenie” zaznacza kanały z większości ostatnich rekrutacji klienta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.job import Job
from app.models.job_ad import JobAd
from app.models.job_ad_publication import JobAdPublication
from app.models.job_public_profile import JobPublicProfile
from app.services.job_ad import material, on_create, pracuj_mail
from app.services.job_ad_schema import SOURCE_AI
from tests.test_job_ads_api import _MODEL_REPLY, _model, _no_model


# ── Język ogłoszenia (bez bazy) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("language", "lang"),
    [
        ("English", "en"),
        ("Fluent in English", "en"),
        ("English — professional proficiency", "en"),
        ("English B2 lub wyższy", "en"),
        ("angielski B2", "pl"),
        ("Angielski: komunikatywny", "pl"),
        ("PL, EN B2", "pl"),
        ("polski + angielski do dokumentacji", "pl"),
        ("Polish and English", "pl"),
        ("EN", "pl"),
        (None, "pl"),
    ],
)
def test_ad_language_follows_the_working_language(language, lang):
    mat = SimpleNamespace(language=language)
    assert material.ad_lang(mat) == lang


# ── Z bazą (Postgres, CI) ───────────────────────────────────────────────────


async def _job(client_id: int | None = None, language: str | None = None) -> Job:
    from tests.test_career_links_api import _seed_job, _seed_user

    uid, _email, _password = await _seed_user("oncreate")
    job_id = await _seed_job(uid)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if client_id is not None:
            job.client_id = client_id
        if language is not None:
            job.champion_profile = {
                **job.champion_profile,
                "basics": {**job.champion_profile["basics"], "language": language},
            }
        await db.commit()
        await db.refresh(job)
        return job


async def _ad(job_id: int) -> JobAd | None:
    async with AsyncSessionLocal() as db:
        return await db.get(JobAd, job_id)


@pytest.mark.asyncio
async def test_ad_is_written_after_create_with_the_model(monkeypatch):
    calls = _model(monkeypatch)
    job = await _job()

    await on_create.prepare_after_create(job.id, None)

    ad = await _ad(job.id)
    assert ad is not None
    assert ad.lang == "pl"
    assert ad.source == SOURCE_AI
    assert ad.content["lead"] == _MODEL_REPLY["lead"]
    assert ad.generated_by is None  # przygotował NEXUS, nie osoba
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_english_recruitment_gets_an_english_ad(monkeypatch):
    reply = {
        **_MODEL_REPLY,
        "start": "October 2026",
        "duration": "12+ months",
        "language": "English",
    }
    _model(monkeypatch, reply=reply)
    job = await _job(language="Fluent in English")

    await on_create.prepare_after_create(job.id, None)

    ad = await _ad(job.id)
    assert ad is not None and ad.lang == "en"


@pytest.mark.asyncio
async def test_no_model_writes_nothing_and_leaves_the_night(monkeypatch):
    _no_model(monkeypatch)
    job = await _job()

    await on_create.prepare_after_create(job.id, None)

    # Bez modelu żadnego złożenia z pól: zostaje noc i „Przygotuj” w oknie.
    assert await _ad(job.id) is None


@pytest.mark.asyncio
async def test_model_error_never_escapes(monkeypatch):
    _model(monkeypatch, error=RuntimeError("529 overloaded_error"))
    job = await _job()

    await on_create.prepare_after_create(job.id, None)  # bez wyjątku

    assert await _ad(job.id) is None


@pytest.mark.asyncio
async def test_unexpected_failure_is_swallowed(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("baza padła")

    monkeypatch.setattr(on_create.prepare, "prepare_one", boom)
    await on_create.prepare_after_create(10**9, None)  # bez wyjątku


@pytest.mark.asyncio
async def test_existing_ad_is_never_replaced(monkeypatch):
    _model(monkeypatch)
    job = await _job()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            JobAd(
                job_id=job.id,
                lang="pl",
                content={"lead": "Poprawione przez DL-a"},
                tech=[],
                source=SOURCE_AI,
                material_hash="x",
                generated_at=now,
                updated_at=now,
            )
        )
        await db.commit()

    await on_create.prepare_after_create(job.id, None)

    ad = await _ad(job.id)
    assert ad.content["lead"] == "Poprawione przez DL-a"


@pytest.mark.asyncio
async def test_create_queues_the_ad_after_commit_and_survives_a_failure(
    app_client, app_auth_headers, monkeypatch
):
    """`POST /api/jobs`: ogłoszenie powstaje po commicie; awaria modelu = 201."""
    from tests._job_factory import complete_job_payload
    from tests.test_job_no_drafts import _client

    from app.services import canonical_fit, embedding_service

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)

    _model(monkeypatch)
    resp = await app_client.post(
        "/api/jobs",
        json=await complete_job_payload(await _client("OnCreate")),
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    ad = await _ad(resp.json()["id"])
    assert ad is not None and ad.source == SOURCE_AI

    _model(monkeypatch, error=RuntimeError("529 overloaded_error"))
    resp = await app_client.post(
        "/api/jobs",
        json=await complete_job_payload(await _client("OnCreateDown")),
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, resp.json()["id"])
        assert job is not None and job.status.value == "published"
    assert await _ad(resp.json()["id"]) is None


@pytest.mark.asyncio
async def test_channels_follow_most_recent_client_jobs():
    first = await _job()
    client_id = first.client_id
    now = datetime.now(timezone.utc)
    # Pięć starszych rekrutacji: strona kariery i JJIT w 3, Pracuj w 1.
    older = [await _job(client_id) for _ in range(5)]
    async with AsyncSessionLocal() as db:
        for index, job in enumerate(older):
            row = await db.get(Job, job.id)
            row.created_at = now - timedelta(days=10 - index)
            if index < 3:
                db.add(JobPublicProfile(job_id=job.id, approved_at=now))
                db.add(
                    JobAdPublication(
                        job_id=job.id, portal="jjit", content_hash="x", published_at=now
                    )
                )
            else:
                db.add(
                    JobAdPublication(
                        job_id=job.id,
                        portal="pracuj",
                        content_hash="x",
                        published_at=now,
                    )
                )
        await db.commit()
        target = await db.get(Job, first.id)
        found = await on_create.recent_channels(db, target)

    assert found.jobs == 5
    assert found.channels == ["kariera", "jjit"]


@pytest.mark.asyncio
async def test_pracuj_mail_counts_and_client_without_history_gets_all():
    alone = await _job()
    async with AsyncSessionLocal() as db:
        found = await on_create.recent_channels(db, await db.get(Job, alone.id))
    assert found.jobs == 0
    assert found.channels == ["kariera", "jjit", "pracuj"]

    other = await _job(alone.client_id)
    async with AsyncSessionLocal() as db:
        db.add(
            Activity(
                entity_type="job",
                entity_id=other.id,
                action=pracuj_mail.ACTION,
                details={"to": "opiekun@example.com"},
            )
        )
        await db.commit()
        found = await on_create.recent_channels(db, await db.get(Job, alone.id))
    assert found.jobs == 1
    assert found.channels == ["pracuj"]


@pytest.mark.asyncio
async def test_portal_ad_response_carries_recent_channels():
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from tests.test_career_links_api import _owner_with_job

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as api:
        _uid, headers, job_id = await _owner_with_job(api)
        resp = await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["recent_channels"] == {
        "channels": ["kariera", "jjit", "pracuj"],
        "jobs": 0,
        "jjit_category": None,
    }
