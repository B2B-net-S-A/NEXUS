"""Pakiet „Ochrona wejścia” na trasach zgłoszeń (z bazą): ClamAV + ALTCHA.

* plik z EICAR odpada przed zapisem kandydata (strona kariery; serwer strony WWW
  w ``test_public_website_applications.py``);
* clamd niedostępny = 503 na publicznym formularzu, bez zapisu;
* rozwiązana zagadka przechodzi raz, powtórka tego samego rozwiązania — 400,
  także między procesami web (tabela ``altcha_spent_challenges``).

Reguła: ``docs/claude/podstawy/skan-plikow-i-altcha.md``.
"""

from __future__ import annotations

import io
import socket
import uuid

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.services import altcha, public_apply
from tests import test_career_links_api as links
from tests._clamd_fake import eicar_docx, fake_clamd
from tests.test_altcha import solve
from tests.test_career_links_api import _approve, _create_job_link, _owner_with_job

api = links.api
_stub_background = links._stub_background

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _eicar_cv():
    return {"cv": ("cv.docx", io.BytesIO(eicar_docx()), _DOCX)}


def _clean_cv():
    return {"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4 czyste cv"), "application/pdf")}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _point_clamd(monkeypatch, port: int) -> None:
    monkeypatch.setattr(settings, "CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "CLAMAV_PORT", port)
    monkeypatch.setattr(settings, "CLAMAV_TIMEOUT_SECONDS", 5.0)


def _person(monkeypatch, email: str) -> None:
    async def _found(db, content, filename):
        return {"first_name": "Ola", "last_name": "Skan", "email": email, "phone": None}

    monkeypatch.setattr(public_apply, "identity_from_cv", _found)


async def _candidate(email: str):
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Candidate).where(Candidate.email == email))


async def _career_link(api_client) -> str:
    _, headers, job_id = await _owner_with_job(api_client)
    link = await _create_job_link(api_client, headers, job_id)
    assert (await _approve(api_client, headers, job_id)).status_code == 200
    return link["slug"]


@pytest.mark.asyncio
async def test_career_apply_rejects_eicar_before_saving(api, monkeypatch):
    email = f"eicar-{uuid.uuid4().hex[:8]}@example.com"
    _person(monkeypatch, email)
    slug = await _career_link(api)

    async with fake_clamd() as port:
        _point_clamd(monkeypatch, port)
        resp = await api.post(
            "/api/public/career/apply",
            data={"link_slug": slug, "consent": "true"},
            files=_eicar_cv(),
        )

    assert resp.status_code == 422, resp.text
    (error,) = resp.json()["detail"]
    assert error["loc"] == ["body", "cv"]
    assert error["msg"] == (
        "Nie udało się przyjąć pliku. Wyślij CV ponownie w PDF albo DOCX."
    )
    assert await _candidate(email) is None


@pytest.mark.asyncio
async def test_career_apply_is_fail_closed_without_clamd(api, monkeypatch):
    email = f"noclam-{uuid.uuid4().hex[:8]}@example.com"
    _person(monkeypatch, email)
    slug = await _career_link(api)
    _point_clamd(monkeypatch, _free_port())

    resp = await api.post(
        "/api/public/career/apply",
        data={"link_slug": slug, "consent": "true"},
        files=_clean_cv(),
    )

    assert resp.status_code == 503, resp.text
    assert "Spróbuj ponownie" in resp.json()["detail"]
    assert await _candidate(email) is None


@pytest.mark.asyncio
async def test_clean_cv_with_clamd_is_accepted(api, monkeypatch):
    email = f"czyste-{uuid.uuid4().hex[:8]}@example.com"
    _person(monkeypatch, email)
    slug = await _career_link(api)

    async with fake_clamd() as port:
        _point_clamd(monkeypatch, port)
        resp = await api.post(
            "/api/public/career/apply",
            data={"link_slug": slug, "consent": "true"},
            files=_clean_cv(),
        )

    assert resp.status_code == 201, resp.text
    assert await _candidate(email) is not None


@pytest.mark.asyncio
async def test_challenge_route_is_not_cached(api):
    resp = await api.get("/api/public/career/challenge")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["algorithm"] == "SHA-256"
    assert set(body) == {"algorithm", "challenge", "maxnumber", "salt", "signature"}


@pytest.mark.asyncio
async def test_altcha_solution_works_once_then_replay_is_rejected(api, monkeypatch):
    monkeypatch.setattr(settings, "ALTCHA_REQUIRED", True)
    monkeypatch.setattr(settings, "ALTCHA_MAX_NUMBER", 500)
    slug = await _career_link(api)
    payload = solve((await api.get("/api/public/career/challenge")).json())

    first = f"altcha-a-{uuid.uuid4().hex[:8]}@example.com"
    _person(monkeypatch, first)
    resp = await api.post(
        "/api/public/career/apply",
        data={"link_slug": slug, "consent": "true", "altcha": payload},
        files=_clean_cv(),
    )
    assert resp.status_code == 201, resp.text

    second = f"altcha-b-{uuid.uuid4().hex[:8]}@example.com"
    _person(monkeypatch, second)
    replay = await api.post(
        "/api/public/career/apply",
        data={"link_slug": slug, "consent": "true", "altcha": payload},
        files=_clean_cv(),
    )
    assert replay.status_code == 400, replay.text
    assert replay.json()["detail"] == altcha.MSG_FAILED
    assert await _candidate(second) is None


@pytest.mark.asyncio
async def test_failed_application_does_not_spend_the_solution(api, monkeypatch):
    """Zgłoszenie, które padło dalej (brak zgody), nie zużywa zagadki."""
    monkeypatch.setattr(settings, "ALTCHA_REQUIRED", True)
    monkeypatch.setattr(settings, "ALTCHA_MAX_NUMBER", 500)
    slug = await _career_link(api)
    challenge = (await api.get("/api/public/career/challenge")).json()
    payload = solve(challenge)
    email = f"altcha-c-{uuid.uuid4().hex[:8]}@example.com"
    _person(monkeypatch, email)

    no_consent = await api.post(
        "/api/public/career/apply",
        data={"link_slug": slug, "altcha": payload},
        files=_clean_cv(),
    )
    assert no_consent.status_code == 422, no_consent.text
    async with AsyncSessionLocal() as db:
        spent = await db.scalar(
            text("SELECT count(*) FROM altcha_spent_challenges WHERE challenge = :c"),
            {"c": challenge["challenge"]},
        )
    assert spent == 0

    retry = await api.post(
        "/api/public/career/apply",
        data={"link_slug": slug, "consent": "true", "altcha": payload},
        files=_clean_cv(),
    )
    assert retry.status_code == 201, retry.text


@pytest.mark.asyncio
async def test_missing_altcha_is_rejected_after_rollout(api, monkeypatch):
    monkeypatch.setattr(settings, "ALTCHA_REQUIRED", True)
    after = altcha.MISSING_ALLOWED_UNTIL.timestamp() + 60
    monkeypatch.setattr(altcha.time, "time", lambda: after)
    slug = await _career_link(api)
    email = f"altcha-d-{uuid.uuid4().hex[:8]}@example.com"
    _person(monkeypatch, email)

    resp = await api.post(
        "/api/public/career/apply",
        data={"link_slug": slug, "consent": "true"},
        files=_clean_cv(),
    )

    assert resp.status_code == 400, resp.text
    assert await _candidate(email) is None
