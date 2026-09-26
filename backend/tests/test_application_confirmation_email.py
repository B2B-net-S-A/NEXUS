"""Mail potwierdzenia aplikacji (PR2, rodzaj ``application_confirmation``).

Pokrywa:

- domyślnie WYŁĄCZONY: zgłoszenie bez włączonej polityki nie wysyła maila
  i nie rezerwuje dedupu;
- treść IDENTYCZNA w obu gałęziach ``submit_application`` (nowy e-mail /
  e-mail już w bazie) — mail nie może zdradzić, że osoba była w bazie;
- jeden mail na (adres, link) w 24 h, nieudana wysyłka zwalnia rezerwację;
- tytuł rekrutacji tylko z zatwierdzonego opisu publicznego.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.application_confirmation_send import ApplicationConfirmationSend
from app.models.candidate import Candidate
from app.services import application_confirmation_email as confirmation
from app.services import notification_delivery as delivery
from tests.test_career_links_api import (
    _approve,
    _create_job_link,
    _cv,
    _form,
    _owner_with_job,
    _seed_job,
    _seed_user,
)

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


@pytest.fixture(autouse=True)
def _stub_background(monkeypatch):
    async def _noop_embed(candidate_id, db):
        return True

    async def _noop_task(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.embedding_service.embed_candidate", _noop_embed)
    monkeypatch.setattr("app.api.public_share._invite_post_apply_task", _noop_task)


def _enabled_policy() -> delivery.DeliveryPolicy:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return delivery.DeliveryPolicy.from_value(
        {
            "enabled": True,
            "send_not_before": cutoff,
            "types": {
                confirmation.KIND: {"email_enabled": True, "send_not_before": cutoff}
            },
        }
    )


@pytest.fixture
def sent(monkeypatch):
    """Przechwycony nadawca; zwraca listę wysłanych maili."""
    outbox: list[dict] = []

    def fake_send(to, subject, text_body, html_body=None):
        outbox.append(
            {"to": to, "subject": subject, "text": text_body, "html": html_body}
        )
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send)
    return outbox


@pytest.fixture
def enabled(monkeypatch):
    policy = _enabled_policy()

    async def _load(_db):
        return policy

    monkeypatch.setattr(delivery, "load_policy", _load)
    monkeypatch.setattr(
        delivery,
        "is_delivery_allowed_sync",
        lambda kind, event_at: policy.allows(kind, event_at),
    )
    return policy


async def _claims(email: str) -> int:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(ApplicationConfirmationSend.id).where(
                ApplicationConfirmationSend.email_key == confirmation.email_key(email)
            )
        )
        return len(list(rows))


async def _recruiter_slug(api, headers) -> str:
    slug = f"conf-{uuid.uuid4().hex[:6]}"
    resp = await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)
    assert resp.status_code == 200, resp.text
    return slug


# ── Katalog ────────────────────────────────────────────────────────────────


async def test_kind_is_in_catalog_and_off_without_policy():
    assert confirmation.KIND in delivery.ROUTINE_KINDS
    assert not delivery.DeliveryPolicy.from_value(None).kind_enabled(confirmation.KIND)
    # Włączenie INNYCH rodzajów nie włącza potwierdzeń.
    other = delivery.DeliveryPolicy.from_value(
        {
            "enabled": True,
            "send_not_before": datetime.now(timezone.utc).isoformat(),
            "types": {
                "mentions": {
                    "email_enabled": True,
                    "send_not_before": datetime.now(timezone.utc).isoformat(),
                }
            },
        }
    )
    assert not other.kind_enabled(confirmation.KIND)


async def test_render_is_pure_and_escapes_html():
    a = confirmation.render_confirmation(
        to=" jan@example.com ",
        first_name="<Jan>",
        public_job_title="Java & Kafka",
        rodo_url="https://kariera.example/rodo",
    )
    b = confirmation.render_confirmation(
        to="jan@example.com",
        first_name="<Jan>",
        public_job_title="Java & Kafka",
        rodo_url="https://kariera.example/rodo",
    )
    assert a == b
    assert a.to == "jan@example.com"
    # R8-N4-9: imię z anonimowego formularza nie trafia do maila w ogóle.
    assert "Jan" not in a.html_body and "Jan" not in a.text_body
    assert a.text_body.startswith("Dzień dobry,")
    assert "Java &amp; Kafka" in a.html_body
    assert a.subject == "Potwierdzenie zgłoszenia: Java & Kafka"
    generic = confirmation.render_confirmation(
        to="x@example.com", first_name="", public_job_title=None, rodo_url="u"
    )
    assert generic.subject == "Potwierdzenie zgłoszenia"
    assert generic.text_body.startswith("Dzień dobry,")


# ── Zgłoszenia ─────────────────────────────────────────────────────────────


async def test_off_by_default_sends_nothing_and_claims_nothing(api, sent):
    _uid, headers, _job = await _owner_with_job(api)
    slug = await _recruiter_slug(api, headers)
    email = f"conf-off-{uuid.uuid4().hex[:6]}@example.com"

    resp = await api.post(
        "/api/public/career/apply", data=_form(slug, email), files=_cv()
    )

    assert resp.status_code == 201, resp.text
    assert sent == []
    assert await _claims(email) == 0


async def test_same_content_for_new_and_existing_email(api, sent, enabled):
    _uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    email = f"conf-same-{uuid.uuid4().hex[:6]}@example.com"

    first = await api.post(
        "/api/public/career/apply", data=_form(link["slug"], email), files=_cv()
    )
    assert first.status_code == 201, first.text
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(Candidate.id).where(Candidate.email == email))
        # Zdejmujemy dedup, żeby drugie zgłoszenie (gałąź „już w bazie”)
        # też wysłało mail — porównujemy treść, nie okno 24 h.
        await db.execute(
            delete(ApplicationConfirmationSend).where(
                ApplicationConfirmationSend.email_key == confirmation.email_key(email)
            )
        )
        await db.commit()

    second = await api.post(
        "/api/public/career/apply", data=_form(link["slug"], email), files=_cv()
    )
    assert second.status_code == 201, second.text

    assert len(sent) == 2
    assert sent[0] == sent[1]
    assert sent[0]["to"] == email
    # Tytuł z zatwierdzonego opisu publicznego, nie wewnętrzny z nazwą klienta.
    assert "Potwierdzenie zgłoszenia: " in sent[0]["subject"]
    assert "Kwarcowy Bank" not in sent[0]["subject"] + sent[0]["text"]
    assert "już w bazie" not in sent[0]["text"]


async def test_one_mail_per_email_and_link_within_24h(api, sent, enabled):
    _uid, headers, _job = await _owner_with_job(api)
    slug = await _recruiter_slug(api, headers)
    email = f"conf-dedup-{uuid.uuid4().hex[:6]}@example.com"

    for _ in range(2):
        resp = await api.post(
            "/api/public/career/apply", data=_form(slug, email), files=_cv()
        )
        assert resp.status_code == 201, resp.text

    assert len(sent) == 1
    assert await _claims(email) == 1

    # Po upływie 24 h ta sama para dostaje kolejny mail.
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(ApplicationConfirmationSend).where(
                ApplicationConfirmationSend.email_key == confirmation.email_key(email)
            )
        )
        row.sent_at = datetime.now(timezone.utc) - timedelta(hours=25)
        await db.commit()
    resp = await api.post(
        "/api/public/career/apply", data=_form(slug, email), files=_cv()
    )
    assert resp.status_code == 201
    assert len(sent) == 2


async def test_failed_send_releases_the_claim(api, enabled, monkeypatch):
    monkeypatch.setattr("app.services.email.send_email", lambda *args, **kwargs: False)
    _uid, headers, _job = await _owner_with_job(api)
    slug = await _recruiter_slug(api, headers)
    email = f"conf-fail-{uuid.uuid4().hex[:6]}@example.com"

    resp = await api.post(
        "/api/public/career/apply", data=_form(slug, email), files=_cv()
    )

    assert resp.status_code == 201, resp.text
    assert await _claims(email) == 0


async def test_policy_rechecked_before_sender(api, sent, enabled, monkeypatch):
    """Admin wyłączył rodzaj między zgłoszeniem a wysyłką → brak maila."""
    monkeypatch.setattr(delivery, "is_delivery_allowed_sync", lambda *a: False)
    _uid, headers, _job = await _owner_with_job(api)
    slug = await _recruiter_slug(api, headers)
    email = f"conf-recheck-{uuid.uuid4().hex[:6]}@example.com"

    resp = await api.post(
        "/api/public/career/apply", data=_form(slug, email), files=_cv()
    )

    assert resp.status_code == 201
    assert sent == []


async def test_title_only_from_approved_public_profile():
    uid, _, _ = await _seed_user("conf-title")
    job_id = await _seed_job(uid)
    async with AsyncSessionLocal() as db:
        assert await confirmation.public_job_title(db, job_id) is None
        assert await confirmation.public_job_title(db, None) is None
