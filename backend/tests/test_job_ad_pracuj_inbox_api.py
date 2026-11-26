"""Link do Pracuj.pl z maila Pracuj.pl (26.11.2026) — pętla i trasy z bazą.

- pewne dopasowanie oznacza Pracuj.pl samo, raz, z publicznym linkiem;
- „To nie to ogłoszenie” zdejmuje oznaczenie z maila i mail nie wraca;
- dwie rekrutacje z tym samym tytułem = propozycja, „To ta rekrutacja”
  oznacza jedną, a druga nie dostaje tego samego linku;
- mail bez prośby z NEXUSA tej osoby niczego nie rusza;
- wklejony link z panelu pracodawcy zapisuje się jako publiczny.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.job import Job, JobStatus
from app.models.job_ad import JobAd
from app.models.m365 import Email, EmailDirection
from app.services.job_ad import pracuj_inbox, pracuj_mail
from app.tasks import pracuj_mail_links
from tests.test_job_ad_pracuj_mail_api import _job_with_lead

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


def _gid() -> str:
    return str(uuid.uuid4())


async def _open_with_request(job_id: int, lead_id: int, *, hours_ago: int = 30) -> str:
    """Rekrutacja otwarta, z prośbą DL-a do opiekuna; zwraca tytuł ogłoszenia."""
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.status = JobStatus.published
        ad = await db.get(JobAd, job_id)
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action=pracuj_mail.ACTION,
                user_id=lead_id,
                details={"to": "opiekun@example.com", "email_id": 1},
                created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
            )
        )
        await db.commit()
        return (ad.content or {}).get("title") or job.title


async def _pracuj_mail(user_id: int, title: str, gid: str) -> int:
    async with AsyncSessionLocal() as db:
        row = Email(
            user_id=user_id,
            m365_message_id=f"pracuj-{uuid.uuid4().hex}",
            m365_conversation_id="c",
            from_address=pracuj_inbox.SENDER,
            subject=f"Publikacja ogłoszenia na {title} (k/m/x)",
            body_html=(
                '<p>Twoje ogłoszenie jest już aktywne.</p><a href="https://www.pracuj.pl/'
                f'praca?groupId={gid}">Zobacz ogłoszenie</a>'
            ),
            received_at=datetime.now(timezone.utc) - timedelta(hours=2),
            direction=EmailDirection.received,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _state(api: AsyncClient, headers, job_id: int) -> dict:
    resp = await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _pracuj(state: dict) -> dict | None:
    return next(
        (
            p
            for p in state["publications"]
            if p["portal"] == "pracuj" and not p["removed_at"]
        ),
        None,
    )


async def _linked_count(job_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).where(
                Activity.entity_type == "job",
                Activity.entity_id == job_id,
                Activity.action == pracuj_inbox.LINKED,
            )
        )


async def test_a_sure_match_marks_pracuj_once_with_the_public_link(
    api: AsyncClient, monkeypatch
):
    _recruiter, lead, lead_id, job_id = await _job_with_lead(api, monkeypatch)
    title = await _open_with_request(job_id, lead_id)
    gid = _gid()
    email_id = await _pracuj_mail(lead_id, title, gid)

    assert await pracuj_mail_links.run_once() >= 1
    # Drugi przebieg niczego nie dubluje.
    await pracuj_mail_links.run_once()

    state = await _state(api, lead, job_id)
    marked = _pracuj(state)
    assert marked is not None
    assert marked["url"] == f"https://www.pracuj.pl/praca?groupId={gid}"
    assert marked["from_mail"]["email_id"] == email_id
    assert marked["from_mail"]["subject"].startswith("Publikacja ogłoszenia na")
    assert state["pracuj_mail_suggestions"] == []
    assert await _linked_count(job_id) == 1


async def test_not_this_ad_removes_the_mark_and_the_mail_does_not_return(
    api: AsyncClient, monkeypatch
):
    recruiter, lead, lead_id, job_id = await _job_with_lead(api, monkeypatch)
    title = await _open_with_request(job_id, lead_id)
    email_id = await _pracuj_mail(lead_id, title, _gid())
    await pracuj_mail_links.run_once()
    path = f"/api/jobs/{job_id}/portal-ad/pracuj-mail-links/{email_id}"

    assert (await api.delete(path, headers=recruiter)).status_code == 403
    resp = await api.delete(path, headers=lead)
    assert resp.status_code == 200, resp.text
    assert _pracuj(resp.json()) is None

    await pracuj_mail_links.run_once()
    state = await _state(api, lead, job_id)
    assert _pracuj(state) is None
    assert state["pracuj_mail_suggestions"] == []


async def test_two_recruitments_with_one_title_are_asked_about(
    api: AsyncClient, monkeypatch
):
    _r1, lead, lead_id, first = await _job_with_lead(api, monkeypatch)
    title = await _open_with_request(first, lead_id)
    # Druga rekrutacja tego DL-a z tym samym tytułem ogłoszenia.
    _r2, _lead2, _lead2_id, second = await _job_with_lead(api, monkeypatch)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, second)
        job.delivery_lead_id = lead_id
        ad = await db.get(JobAd, second)
        ad.content = {**(ad.content or {}), "title": title}
        await db.commit()
    await _open_with_request(second, lead_id)
    email_id = await _pracuj_mail(lead_id, title, _gid())

    await pracuj_mail_links.run_once()
    for job_id in (first, second):
        state = await _state(api, lead, job_id)
        assert _pracuj(state) is None
        assert [s["email_id"] for s in state["pracuj_mail_suggestions"]] == [email_id]

    resp = await api.put(
        f"/api/jobs/{second}/portal-ad/pracuj-mail-links/{email_id}", headers=lead
    )
    assert resp.status_code == 200, resp.text
    assert _pracuj(resp.json())["from_mail"]["email_id"] == email_id

    # Ten sam link nie trafia do pierwszej rekrutacji.
    await pracuj_mail_links.run_once()
    state = await _state(api, lead, first)
    assert _pracuj(state) is None
    assert state["pracuj_mail_suggestions"] == []
    again = await api.put(
        f"/api/jobs/{first}/portal-ad/pracuj-mail-links/{email_id}", headers=lead
    )
    assert again.status_code == 404


async def test_a_mail_without_a_request_from_this_person_changes_nothing(
    api: AsyncClient, monkeypatch
):
    _recruiter, lead, lead_id, job_id = await _job_with_lead(api, monkeypatch)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.status = JobStatus.published
        title = ((await db.get(JobAd, job_id)).content or {}).get("title") or job.title
        await db.commit()
    await _pracuj_mail(lead_id, title, _gid())

    await pracuj_mail_links.run_once()
    state = await _state(api, lead, job_id)
    assert _pracuj(state) is None
    assert state["pracuj_mail_suggestions"] == []


async def test_a_pasted_panel_link_is_saved_as_the_public_one(
    api: AsyncClient, monkeypatch
):
    _recruiter, lead, _lead_id, job_id = await _job_with_lead(api, monkeypatch)
    gid = _gid()
    resp = await api.put(
        f"/api/jobs/{job_id}/portal-ad/publications/pracuj",
        json={"url": f"https://publikacja.pracuj.pl/showjoboffer/{gid}"},
        headers=lead,
    )
    assert resp.status_code == 200, resp.text
    assert _pracuj(resp.json())["url"] == f"https://www.pracuj.pl/praca?groupId={gid}"

    refused = await api.put(
        f"/api/jobs/{job_id}/portal-ad/publications/pracuj",
        json={"url": "https://strefa.pracuj.pl/apps/kandydaci/123"},
        headers=lead,
    )
    assert refused.status_code == 422
    assert "panelu pracodawcy" in refused.text


async def test_the_0793_data_fix_rewrites_panel_links(api: AsyncClient, monkeypatch):
    from sqlalchemy import text

    from app.models.job_ad_publication import JobAdPublication
    from app.services import job_ad_publication_schema as schema

    ids = []
    for _ in range(4):
        _r, _lead, _lead_id, job_id = await _job_with_lead(api, monkeypatch)
        ids.append(job_id)
    gid = _gid()
    urls = [
        f"https://publikacja.pracuj.pl/showjoboffer/{gid.upper()}",
        "https://strefa.pracuj.pl/apps/kandydaci/123",
        "https://publikacja.pracuj.pl/oidc-auth?code=abc&state=def",
        "https://www.pracuj.pl/praca/java,oferta,1004",
    ]
    async with AsyncSessionLocal() as db:
        for job_id, url in zip(ids, urls):
            db.add(
                JobAdPublication(
                    job_id=job_id,
                    portal="pracuj",
                    url=url,
                    content_hash="x" * 64,
                    published_at=datetime.now(timezone.utc),
                )
            )
        await db.commit()
        for _ in range(2):  # co deploy: drugi przebieg niczego nie rusza
            for statement in schema.PRACUJ_PANEL_LINKS_DML:
                await db.execute(text(statement))
        await db.commit()
        after = {
            row.job_id: row.url
            for row in await db.scalars(
                select(JobAdPublication).where(JobAdPublication.job_id.in_(ids))
            )
        }
    assert after[ids[0]] == f"https://www.pracuj.pl/praca?groupId={gid}"
    assert after[ids[1]] is None
    assert after[ids[2]] is None
    assert after[ids[3]] == urls[3]
