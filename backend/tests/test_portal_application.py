"""Aplikacja z formularza JustJoin.IT → karta w „Nowi” rekrutacji ogłoszenia (06.11.2026).

Import z panelu pracodawcy znał tylko tytuł ogłoszenia, więc 1 690 z 2 159
aplikacji z 30 dni zostało bez karty. ``services/portal_application`` wyznacza
rekrutację po id ogłoszenia z publikacji przez API albo po slugu z linku
„Oznacz jako opublikowane” i zakłada kartę bramkami ``add_candidates_to_job``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services import portal_application
from app.services.job_portals import jjit_payload
from tests.test_pipeline_membership_gate import (
    _seed_candidate,
    _seed_job,
    _seed_recruiter,
)

SLUG = "b2bnetwork-data-engineer-k-m-x--warszawa-data"


def _unique_slug() -> str:
    """Baza testów jest wspólna: żywa publikacja jednego testu znalazłaby się w drugim."""
    return f"b2bnetwork-data-engineer-{uuid.uuid4().hex[:8]}--warszawa-data"


# ── bez bazy ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        (f"https://justjoin.it/job-offer/{SLUG}", SLUG),
        (f"https://justjoin.it/job-offer/{SLUG}/?utm_source=x#top", SLUG),
        (f"https://justjoin.it/job-offer/{SLUG.upper()}", SLUG),
        ("https://justjoin.it/", None),
        ("", None),
        (None, None),
    ],
)
def test_slug_from_url(url, slug):
    assert portal_application.slug_from_url(url) == slug


def test_normalize_slug_accepts_slug_or_link_and_rejects_garbage():
    assert portal_application.normalize_slug(SLUG) == SLUG
    assert portal_application.normalize_slug(f" {SLUG} ") == SLUG
    assert (
        portal_application.normalize_slug(f"https://justjoin.it/job-offer/{SLUG}")
        == SLUG
    )
    assert portal_application.normalize_slug("%' OR 1=1 --") is None
    assert portal_application.normalize_slug("ab") is None
    assert portal_application.normalize_slug(None) is None


def test_apply_method_defaults_to_career_page(monkeypatch):
    monkeypatch.setattr(jjit_payload.settings, "JJIT_APPLY_EMAIL", "")
    assert jjit_payload.apply_method("https://nexus/r/x") == {
        "url": "https://nexus/r/x",
        "email": None,
    }


def test_apply_method_uses_portal_form_when_email_set(monkeypatch):
    """1EP: dokładnie jedno z ``url`` / ``email``; ``email`` = formularz portalu."""
    monkeypatch.setattr(
        jjit_payload.settings, "JJIT_APPLY_EMAIL", " rekrutacja@example.com "
    )
    assert jjit_payload.apply_method("https://nexus/r/x") == {
        "url": None,
        "email": "rekrutacja@example.com",
    }


# ── z bazą (CI) ─────────────────────────────────────────────────────────


async def _posting(job_id: int, ad_id: str) -> None:
    from app.models.job_posting import JobPosting, Portal, PostingStatus

    async with AsyncSessionLocal() as db:
        db.add(
            JobPosting(
                job_id=job_id,
                portal=Portal.justjoinit,
                external_id=ad_id,
                status=PostingStatus.published,
            )
        )
        await db.commit()


async def _publication(job_id: int, url: str, removed: bool = False) -> None:
    from app.models.job_ad_publication import JobAdPublication

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            JobAdPublication(
                job_id=job_id,
                portal="jjit",
                url=url,
                content_hash="0" * 64,
                published_at=now,
                removed_at=now if removed else None,
            )
        )
        await db.commit()


async def _place(candidate_id: int, **kwargs):
    async with AsyncSessionLocal() as db:
        result = await portal_application.place_application(
            db, candidate_id=candidate_id, portal="justjoinit", **kwargs
        )
        await db.commit()
        return result


async def _stage(candidate_id: int, job_id: int):
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
        )


@pytest.mark.asyncio
async def test_api_ad_id_lands_card_in_new_with_application_evidence(app_client):
    from app.models.candidate_source_event import CandidateSourceEvent
    from app.services.integration_intake import candidates_with_application_evidence

    _, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=uid)
    cand = await _seed_candidate()
    ad_id = str(uuid.uuid4())
    await _posting(job_id, ad_id)

    result = await _place(cand, ad_id=ad_id, ad_title="Data Engineer")

    assert result.outcome == "added"
    assert result.job_id == job_id
    stage = await _stage(cand, job_id)
    assert stage is not None
    assert stage.stage.value == "new"
    async with AsyncSessionLocal() as db:
        events = (
            (
                await db.execute(
                    select(CandidateSourceEvent).where(
                        CandidateSourceEvent.candidate_id == cand
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [(e.job_id, e.channel.value) for e in events] == [(job_id, "posting")]
        assert await candidates_with_application_evidence(
            db, job_id=job_id, candidate_ids=[cand]
        ) == {cand}


@pytest.mark.asyncio
async def test_manual_ad_found_by_slug_of_marked_link(app_client):
    _, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=uid)
    cand = await _seed_candidate()
    slug = _unique_slug()
    await _publication(job_id, f"https://justjoin.it/job-offer/{slug}")

    result = await _place(cand, ad_id=str(uuid.uuid4()), ad_slug=slug)

    assert (result.outcome, result.job_id) == ("added", job_id)


@pytest.mark.asyncio
async def test_slug_must_match_whole_last_segment_and_live_publication(app_client):
    _, uid = await _seed_recruiter(app_client)
    longer_job, _ = await _seed_job(owner_id=uid)
    removed_job, _ = await _seed_job(owner_id=uid)
    cand = await _seed_candidate()
    slug = _unique_slug()
    await _publication(longer_job, f"https://justjoin.it/job-offer/{slug}-senior")
    await _publication(removed_job, f"https://justjoin.it/job-offer/{slug}", True)

    result = await _place(cand, ad_id=str(uuid.uuid4()), ad_slug=slug)

    assert result.outcome == "no_job"
    assert await _stage(cand, longer_job) is None
    assert await _stage(cand, removed_job) is None


@pytest.mark.asyncio
async def test_closed_job_keeps_source_but_no_card(app_client):
    from app.models.job import Job, JobStatus

    _, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=uid)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.status = JobStatus.closed
        await db.commit()
    cand = await _seed_candidate()
    ad_id = str(uuid.uuid4())
    await _posting(job_id, ad_id)

    result = await _place(cand, ad_id=ad_id)

    assert (result.outcome, result.job_id) == ("job_not_open", job_id)
    assert await _stage(cand, job_id) is None


@pytest.mark.asyncio
async def test_second_application_is_already_in_job(app_client):
    _, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=uid)
    cand = await _seed_candidate()
    ad_id = str(uuid.uuid4())
    await _posting(job_id, ad_id)

    assert (await _place(cand, ad_id=ad_id)).outcome == "added"
    assert (await _place(cand, ad_id=ad_id)).outcome == "already_in_job"


@pytest.mark.asyncio
async def test_blacklisted_candidate_is_skipped_by_shared_gates(app_client):
    _, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=uid)
    cand = await _seed_candidate(status="blacklisted")
    ad_id = str(uuid.uuid4())
    await _posting(job_id, ad_id)

    result = await _place(cand, ad_id=ad_id)

    assert result.outcome == "skipped"
    assert await _stage(cand, job_id) is None


@pytest.mark.asyncio
async def test_route_refuses_human_token(app_client):
    headers, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=uid)
    cand = await _seed_candidate()
    ad_id = str(uuid.uuid4())
    await _posting(job_id, ad_id)

    resp = await app_client.post(
        f"/api/candidates/{cand}/portal-application",
        json={"portal": "justjoinit", "ad_id": ad_id},
        headers=headers,
    )

    assert resp.status_code == 403
    assert await _stage(cand, job_id) is None
