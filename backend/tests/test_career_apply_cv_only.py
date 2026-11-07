"""Strona kariery: kandydat dołącza samo CV (decyzja Artura z 07.11.2026).

Imię, nazwisko, e-mail i telefon czyta ten sam odczyt co `/from-cv`
(`public_apply.identity_from_cv` → `parse_cv`). Bez e-maila w CV formularz
prosi o niego — 422 na polu ``email``, bez zapisu.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services import public_apply
from tests import test_career_links_api as links
from tests.test_career_links_api import (
    _approve,
    _create_job_link,
    _cv,
    _owner_with_job,
)

# Te same przygotowania co testy linków kariery: klient bez limitów i bez
# zadań w tle po zgłoszeniu.
api = links.api
_stub_background = links._stub_background


def _cv_only(link_slug: str) -> dict:
    return {"link_slug": link_slug, "consent": "true"}


@pytest.mark.asyncio
async def test_cv_only_takes_person_from_cv(api, monkeypatch):
    from app.models.candidate import Candidate

    email = f"z-cv-{uuid.uuid4().hex[:8]}@example.com"

    async def _found(db, content, filename):
        return {
            "first_name": "Ola",
            "last_name": "Zcv",
            "email": email,
            "phone": "+48 600 100 200",
        }

    monkeypatch.setattr(public_apply, "identity_from_cv", _found)
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200

    resp = await api.post(
        "/api/public/career/apply", data=_cv_only(link["slug"]), files=_cv()
    )

    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        person = await db.scalar(select(Candidate).where(Candidate.email == email))
    assert person is not None
    assert (person.name, person.lastname, person.phone) == (
        "Ola",
        "Zcv",
        "+48 600 100 200",
    )


@pytest.mark.asyncio
async def test_cv_without_email_asks_for_it(api, monkeypatch):
    async def _nothing(db, content, filename):
        return {"first_name": "Ola", "last_name": None, "email": None, "phone": None}

    monkeypatch.setattr(public_apply, "identity_from_cv", _nothing)
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200

    resp = await api.post(
        "/api/public/career/apply", data=_cv_only(link["slug"]), files=_cv()
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail[0]["loc"] == ["body", "email"]
    assert "nie znaleźliśmy adresu e-mail" in detail[0]["msg"]


@pytest.mark.asyncio
async def test_typed_email_wins_and_skips_cv_read_when_complete(api, monkeypatch):
    calls = []

    async def _spy(db, content, filename):
        calls.append(filename)
        return {}

    monkeypatch.setattr(public_apply, "identity_from_cv", _spy)
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    form = {
        **_cv_only(link["slug"]),
        "first_name": "Jan",
        "last_name": "Pełny",
        "email": f"pelny-{uuid.uuid4().hex[:8]}@example.com",
    }

    resp = await api.post("/api/public/career/apply", data=form, files=_cv())

    assert resp.status_code == 201, resp.text
    assert calls == []


@pytest.mark.asyncio
async def test_bad_typed_email_is_refused(api):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200

    resp = await api.post(
        "/api/public/career/apply",
        data={**_cv_only(link["slug"]), "email": "to-nie-adres"},
        files=_cv(),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "email"]
