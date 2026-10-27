"""Pracuj.pl mailem do opiekuna (27.10.2026) — trasy z bazą.

- podgląd i wysyłka: DL rekrutacji i Head of Recruitment tak, rekruter nie;
- bez podłączonej skrzynki — 412 z prośbą o podłączenie, nic nie wychodzi;
- wysyłka idzie do opiekuna z Ustawień, ze stawką, i zostawia jeden wpis
  w Historii zdarzeń także przy ponowieniu; kanał Pracuj.pl czeka;
- stawka odwrócona, stara wersja ogłoszenia, ogłoszenie już wiszące — odmowa;
- opiekun zapisuje się w stałych częściach i zostaje przy zapisie bez niego.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.job import Job
from app.models.m365 import M365Connection
from app.models.user import User, UserRole
from app.services.job_ad import fixed_blocks, pracuj_mail
from app.services.m365 import sender as m365_sender
from tests.test_career_links_api import _login, _owner_with_job
from tests.test_job_ads_api import _client_name, _generated, _seed_role_user

pytestmark = pytest.mark.asyncio

RATES = {"rate_from": 110, "rate_to": 125}


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


@pytest_asyncio.fixture(autouse=True)
async def _default_fixed_blocks():
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == fixed_blocks.BLOCKS_KEY)
        )
        await db.commit()


async def _user_id(email: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).where(User.email == email))


async def _job_with_lead(api: AsyncClient, monkeypatch):
    """Rekrutacja z ogłoszeniem i Delivery Leadem; (rekruter, DL, id DL-a, job)."""
    _, recruiter, job_id = await _owner_with_job(api)
    await _generated(api, recruiter, job_id, monkeypatch)
    email, password = await _seed_role_user(UserRole.delivery_lead)
    lead_id = await _user_id(email)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.delivery_lead_id = lead_id
        await db.commit()
    return recruiter, await _login(api, email, password), lead_id, job_id


async def _connect_mailbox(user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            M365Connection(
                user_id=user_id,
                tenant_id="t",
                mailbox_upn=f"dl-{uuid.uuid4().hex[:6]}@example.com",
                access_token_ct="a",
                refresh_token_ct="r",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                is_active=True,
            )
        )
        await db.commit()


def _fake_sender(monkeypatch) -> list[dict]:
    """Graph zaślepiony: ten sam klucz żądania = ten sam wiersz maila."""
    calls: list[dict] = []
    rows: dict[str, SimpleNamespace] = {}

    async def send_new(db, connection, **kwargs):
        calls.append(kwargs)
        key = kwargs.get("client_request_id") or uuid.uuid4().hex
        rows.setdefault(key, SimpleNamespace(id=900_000 + len(rows)))
        return rows[key]

    monkeypatch.setattr(m365_sender, "send_new", send_new)
    return calls


async def _version(api: AsyncClient, headers, job_id: int) -> str:
    ad = (await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)).json()
    return ad["ad"]["updated_at"]


async def _requests_logged(job_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).where(
                Activity.entity_type == "job",
                Activity.entity_id == job_id,
                Activity.action == pracuj_mail.ACTION,
            )
        )


async def test_only_the_lead_hor_and_admin_may_send(api: AsyncClient, monkeypatch):
    recruiter, lead, _lead_id, job_id = await _job_with_lead(api, monkeypatch)
    preview = f"/api/jobs/{job_id}/portal-ad/pracuj-mail/preview"
    send = f"/api/jobs/{job_id}/portal-ad/pracuj-mail"
    assert (await api.post(preview, json=RATES, headers=recruiter)).status_code == 403
    full = {**RATES, "expected_updated_at": None}
    assert (await api.post(send, json=full, headers=recruiter)).status_code == 403
    assert (await api.post(preview, json=RATES, headers=lead)).status_code == 200
    hor = await _login(api, *await _seed_role_user(UserRole.head_of_recruitment))
    assert (await api.post(preview, json=RATES, headers=hor)).status_code == 200


async def test_preview_composes_the_mail_without_client_and_marks_a_missing_rate(
    api: AsyncClient, monkeypatch
):
    _recruiter, lead, _lead_id, job_id = await _job_with_lead(api, monkeypatch)
    url = f"/api/jobs/{job_id}/portal-ad/pracuj-mail/preview"

    empty = (await api.post(url, json={}, headers=lead)).json()
    assert empty["rate_error"] == "Wpisz stawkę dla kandydata."
    assert "Stawka: …" in empty["body_text"]
    assert empty["mailbox"] == "missing" and empty["from_address"] is None
    assert empty["to_email"] == "ogloszenia@pracuj.pl"
    assert empty["body_text"].startswith("Dzień dobry,\n")

    full = (await api.post(url, json=RATES, headers=lead)).json()
    assert full["rate_error"] is None
    assert "Stawka: 110–125 zł/h netto (B2B)" in full["body_text"]
    assert full["subject"].startswith("Prośba o publikację ogłoszenia: ")
    client = await _client_name(job_id)
    assert client not in full["body_text"] and client not in full["subject"]
    # Budżet klienta i stawka z Championa nie przeciekają do maila.
    assert "180" not in full["body_text"] and "175" not in full["body_text"]

    reversed_rate = (
        await api.post(url, json={"rate_from": 190, "rate_to": 170}, headers=lead)
    ).json()
    assert "niższa" in reversed_rate["rate_error"]


async def test_without_a_mailbox_nothing_is_sent(api: AsyncClient, monkeypatch):
    _recruiter, lead, _lead_id, job_id = await _job_with_lead(api, monkeypatch)
    calls = _fake_sender(monkeypatch)
    version = await _version(api, lead, job_id)
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/pracuj-mail",
        json={**RATES, "expected_updated_at": version},
        headers=lead,
    )
    assert resp.status_code == 412
    assert resp.json()["detail"]["code"] == "mailbox_missing"
    assert calls == [] and await _requests_logged(job_id) == 0


async def test_send_goes_to_the_caretaker_once_and_pracuj_waits(
    api: AsyncClient, monkeypatch
):
    _recruiter, lead, lead_id, job_id = await _job_with_lead(api, monkeypatch)
    await _connect_mailbox(lead_id)
    admin = await _login(api, *await _seed_role_user(UserRole.admin))
    blocks = {
        **fixed_blocks.DEFAULTS.as_dict(),
        "pracuj_caretaker": {"name": "Nicola", "email": "opiekun@pracuj.pl"},
    }
    saved = await api.put("/api/job-ads/fixed-blocks", json=blocks, headers=admin)
    assert saved.status_code == 200, saved.text

    calls = _fake_sender(monkeypatch)
    body = {
        **RATES,
        "expected_updated_at": await _version(api, lead, job_id),
        "client_request_id": "req-1",
    }
    url = f"/api/jobs/{job_id}/portal-ad/pracuj-mail"
    resp = await api.post(url, json=body, headers=lead)
    assert resp.status_code == 200, resp.text
    assert len(calls) == 1
    assert calls[0]["to"] == ["opiekun@pracuj.pl"]
    assert "<p>Dzień dobry Nicola,</p>" in calls[0]["body_html"]
    assert "110–125 zł/h netto (B2B)" in calls[0]["body_html"]

    reply = resp.json()
    assert reply["pracuj_request"]["waiting"] is True
    assert reply["pracuj_request"]["to"] == "opiekun@pracuj.pl"
    assert reply["pracuj_request"]["sent_by_name"]
    pracuj = next(c for c in reply["reminders"]["channels"] if c["channel"] == "pracuj")
    assert pracuj["state"] == "requested"

    # Ponowienie tego samego żądania: ten sam mail, jeden wpis w Historii.
    again = await api.post(url, json=body, headers=lead)
    assert again.status_code == 200, again.text
    assert await _requests_logged(job_id) == 1


async def test_send_refuses_bad_rate_stale_ad_and_live_ad(
    api: AsyncClient, monkeypatch
):
    recruiter, lead, lead_id, job_id = await _job_with_lead(api, monkeypatch)
    await _connect_mailbox(lead_id)
    calls = _fake_sender(monkeypatch)
    url = f"/api/jobs/{job_id}/portal-ad/pracuj-mail"
    version = await _version(api, lead, job_id)

    bad = await api.post(
        url,
        json={"rate_from": 190, "rate_to": 170, "expected_updated_at": version},
        headers=lead,
    )
    assert bad.status_code == 422
    unversioned = await api.post(url, json=RATES, headers=lead)
    assert unversioned.status_code == 422
    stale = await api.post(
        url,
        json={**RATES, "expected_updated_at": "2020-01-01T00:00:00+00:00"},
        headers=lead,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "job_ad_changed"

    marked = await api.put(
        f"/api/jobs/{job_id}/portal-ad/publications/pracuj",
        json={"url": None},
        headers=recruiter,
    )
    assert marked.status_code == 200, marked.text
    live = await api.post(
        url, json={**RATES, "expected_updated_at": version}, headers=lead
    )
    assert live.status_code == 409
    assert live.json()["detail"]["code"] == "pracuj_live"
    assert calls == [] and await _requests_logged(job_id) == 0


async def test_unknown_send_outcome_still_leaves_a_trace(api: AsyncClient, monkeypatch):
    """Graph nie odpowiedział na /send — mail mógł wyjść; Pracuj.pl czeka."""
    _recruiter, lead, lead_id, job_id = await _job_with_lead(api, monkeypatch)
    await _connect_mailbox(lead_id)

    async def send_new(db, connection, **kwargs):
        raise m365_sender.EmailSendConflict(
            m365_sender.SEND_STATE_UNCERTAIN, 900_777, first_attempt=True
        )

    monkeypatch.setattr(m365_sender, "send_new", send_new)
    body = {**RATES, "expected_updated_at": await _version(api, lead, job_id)}
    url = f"/api/jobs/{job_id}/portal-ad/pracuj-mail"
    for _ in range(2):
        resp = await api.post(url, json=body, headers=lead)
        assert resp.status_code == 409
    assert await _requests_logged(job_id) == 1
    state = (await api.get(f"/api/jobs/{job_id}/portal-ad", headers=lead)).json()
    assert state["pracuj_request"]["waiting"] is True


async def test_caretaker_is_saved_and_kept_by_an_older_window(api: AsyncClient):
    hor = await _login(api, *await _seed_role_user(UserRole.head_of_recruitment))
    url = "/api/job-ads/fixed-blocks"
    base = fixed_blocks.DEFAULTS.as_dict()

    bad = await api.put(
        url,
        json={**base, "pracuj_caretaker": {"name": "N", "email": "a@b"}},
        headers=hor,
    )
    assert bad.status_code == 422
    ok = await api.put(
        url,
        json={**base, "pracuj_caretaker": {"name": "Nicola", "email": "o@pracuj.pl"}},
        headers=hor,
    )
    assert ok.status_code == 200, ok.text

    older = {k: v for k, v in base.items() if k != "pracuj_caretaker"}
    kept = await api.put(url, json=older, headers=hor)
    assert kept.status_code == 200, kept.text
    assert kept.json()["pracuj_caretaker"] == {"name": "Nicola", "email": "o@pracuj.pl"}
