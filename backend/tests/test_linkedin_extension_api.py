"""Wtyczka LinkedIn (28.10.2026) — trasy ``/api/extension/*`` na bazie.

Ścieżka z makiet: połączenie kontem → sprawdzenie osoby → dodanie do bazy
i rekrutacji → osoba „jest w NEXUSIE” z procesem i kontaktem → limit dzienny
→ odłączenie. Off-limits pyta tak jak NEXUS. Dane fikcyjne.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage
from app.services import client_off_limits

EXT_ID = "abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture(autouse=True)
def _extension_allowed(monkeypatch):
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_IDS", EXT_ID)
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_ENABLED", True)
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_DAILY_READ_LIMIT", 150)


@pytest.fixture(autouse=True)
def _no_semantic_search(monkeypatch):
    async def _empty(*args, **kwargs):  # noqa: ARG001
        return []

    monkeypatch.setattr("app.services.embedding_service.search_jobs_semantic", _empty)


@pytest_asyncio.fixture
async def open_job(app_auth_headers) -> int:  # noqa: ARG001 — admin istnieje
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Testowy {time.time_ns()}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Java Developer (pytest {time.time_ns()})",
            status=JobStatus.published,
            client_id=client.id,
            is_open=True,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _connect(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    resp = await client.post(
        "/api/extension/connect",
        headers=headers,
        json={"extension_id": EXT_ID, "extension_version": "1.0.0"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key"].startswith("nxe_v1_")
    return {"X-Extension-Key": body["key"]}


def _profile(slug: str, **extra) -> dict:
    return {
        "page_kind": "profile",
        "page_url": f"https://www.linkedin.com/in/{slug}/",
        "public_url": f"https://www.linkedin.com/in/{slug}/",
        "full_name": "Jan Testowy",
        "headline": "Java Developer · Spring",
        "location": "Kraków, Małopolskie, Polska",
        "current_company": extra.pop("company", "Firma Przykładowa"),
        "current_title": "Java Developer",
        "experience": [
            {"title": "Java Developer", "company": "Firma Przykładowa", "start": "2021-03", "current": True},
            {"title": "Junior Developer", "company": "Inna Firma", "start": "2018-06", "end": "2021-02"},
        ],
        "skills": ["Java", "Spring Boot", "Kafka"],
        **extra,
    }


@pytest.mark.asyncio
async def test_connect_refuses_unknown_extension(app_client, app_auth_headers) -> None:
    resp = await app_client.post(
        "/api/extension/connect",
        headers=app_auth_headers,
        json={"extension_id": "pppppppppppppppppppppppppppppppp"},
    )
    assert resp.status_code == 403
    assert "nie jest wtyczką NEXUSA" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_key_works_only_on_extension_routes(app_client, app_auth_headers) -> None:
    key = await _connect(app_client, app_auth_headers)
    me = await app_client.get("/api/extension/me", headers=key)
    assert me.status_code == 200, me.text
    assert me.json()["usage"]["reads_limit"] == 150

    # Klucz wtyczki nie otwiera reszty API…
    other = await app_client.get("/api/candidates", headers=key)
    assert other.status_code == 401
    # …a JWT nie otwiera tras wtyczki.
    jwt_only = await app_client.get("/api/extension/me", headers=app_auth_headers)
    assert jwt_only.status_code == 401
    assert jwt_only.json()["detail"] == "extension_key_invalid"


@pytest.mark.asyncio
async def test_full_path_lookup_add_contact(app_client, app_auth_headers, open_job) -> None:
    key = await _connect(app_client, app_auth_headers)
    slug = f"jan-testowy-{time.time_ns()}"

    first = await app_client.post("/api/extension/lookup", headers=key, json=_profile(slug))
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "not_found"
    assert first.json()["usage"]["reads_today"] >= 1

    added = await app_client.post(
        "/api/extension/candidates",
        headers=key,
        json={"profile": _profile(slug), "job_ids": [open_job]},
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["created"] is True
    assert body["assigned_job_ids"] == [open_job]
    candidate_id = body["candidate_id"]

    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert candidate.source == "linkedin_extension"
        assert candidate.linkedin_current_company == "Firma Przykładowa"
        assert candidate.linkedin.endswith(slug)
        stage = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == candidate_id, CandidateStage.job_id == open_job
            )
        )
        assert stage is not None

    again = await app_client.post(
        "/api/extension/candidates",
        headers=key,
        json={"profile": _profile(slug), "job_ids": []},
    )
    assert again.status_code == 200
    assert again.json() == {**again.json(), "candidate_id": candidate_id, "created": False}

    contact = await app_client.post(
        f"/api/extension/candidates/{candidate_id}/contacts",
        headers=key,
        json={"channel": "inmail", "job_id": open_job, "note": "Odpisze w piątek", "remind_in_days": 3},
    )
    assert contact.status_code == 200, contact.text
    assert contact.json()["reminder_id"] is not None

    found = await app_client.post(
        "/api/extension/lookup",
        headers=key,
        json=_profile(slug, company="Nowa Firma Testowa"),
    )
    data = found.json()
    assert data["status"] == "found"
    assert data["matched_by"] == "linkedin"
    assert data["candidate"]["id"] == candidate_id
    assert [p["job_id"] for p in data["processes"]] == [open_job]
    assert data["contacts"][0]["channel_label"] == "InMail"
    assert data["job_change"] == {"page_company": "Nowa Firma Testowa", "nexus_company": "Firma Przykładowa"}

    refreshed = await app_client.post(
        f"/api/extension/candidates/{candidate_id}/refresh",
        headers=key,
        json={"profile": _profile(slug, company="Nowa Firma Testowa")},
    )
    assert "current_company" in refreshed.json()["updated"]

    async with AsyncSessionLocal() as db:
        note = await db.scalar(
            select(Note).where(
                Note.candidate_id == candidate_id, Note.source_ref == "linkedin_extension:inmail"
            )
        )
        assert note is not None and note.kind == "contact_attempt"
        reminder = await db.get(CalendarEvent, contact.json()["reminder_id"])
        assert reminder.candidate_id == candidate_id


@pytest.mark.asyncio
async def test_recruiter_profile_without_link_matches_by_name_and_company(
    app_client, app_auth_headers
) -> None:
    key = await _connect(app_client, app_auth_headers)
    company = f"Firma Unikalna {time.time_ns()}"
    slug = f"jan-testowy-rec-{time.time_ns()}"
    added = await app_client.post(
        "/api/extension/candidates", headers=key, json={"profile": _profile(slug, company=company)}
    )
    assert added.status_code == 201, added.text

    recruiter_view = _profile(slug, company=company)
    recruiter_view.update(
        page_kind="recruiter_profile",
        page_url="https://www.linkedin.com/talent/profile/AEMAATESTOWY",
        public_url=None,
    )
    resp = await app_client.post("/api/extension/lookup", headers=key, json=recruiter_view)
    data = resp.json()
    if data["status"] == "found":
        assert data["matched_by"] == "name_company"
        assert data["candidate"]["id"] == added.json()["candidate_id"]
    else:
        # Inny „Jan Testowy” z tą samą firmą w bazie testowej = niepewność, nie błąd.
        assert data["status"] == "ambiguous"


@pytest.mark.asyncio
async def test_off_limits_asks_then_accepts_answer(
    app_client, app_auth_headers, open_job, monkeypatch
) -> None:
    async def _labels(db):  # noqa: ARG001
        return [("bank testowy", 999_999, "Bank Testowy")]

    monkeypatch.setattr(client_off_limits, "off_limits_labels", _labels)
    key = await _connect(app_client, app_auth_headers)
    slug = f"jan-testowy-ol-{time.time_ns()}"
    profile = _profile(slug, company="Bank Testowy S.A.")

    seen = await app_client.post("/api/extension/lookup", headers=key, json=profile)
    assert seen.json()["off_limits"] == {"client_name": "Bank Testowy", "company": "Bank Testowy S.A."}

    asked = await app_client.post(
        "/api/extension/candidates", headers=key, json={"profile": profile, "job_ids": [open_job]}
    )
    assert asked.status_code == 409
    assert asked.json()["detail"]["code"] == "off_limits_confirmation_required"
    async with AsyncSessionLocal() as db:
        # Rollback całego żądania — osoby nie ma.
        assert await db.scalar(select(Candidate).where(Candidate.linkedin.ilike(f"%{slug}%"))) is None

    declined = await app_client.post(
        "/api/extension/candidates",
        headers=key,
        json={"profile": profile, "job_ids": [open_job], "off_limits_how": "skip"},
    )
    assert declined.status_code == 201
    assert declined.json()["assigned_job_ids"] == []
    assert declined.json()["skipped"][0]["job_id"] == open_job

    confirmed = await app_client.post(
        f"/api/extension/candidates/{declined.json()['candidate_id']}/jobs",
        headers=key,
        json={"job_ids": [open_job], "off_limits_how": "linkedin_inbound"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["assigned_job_ids"] == [open_job]


@pytest.mark.asyncio
async def test_daily_limit_then_revoke(app_client, app_auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_DAILY_READ_LIMIT", 1)
    key = await _connect(app_client, app_auth_headers)
    slug = f"jan-testowy-limit-{time.time_ns()}"
    ok = await app_client.post("/api/extension/lookup", headers=key, json=_profile(slug))
    assert ok.status_code == 200
    blocked = await app_client.post("/api/extension/lookup", headers=key, json=_profile(slug))
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "extension_daily_limit"

    listing = await app_client.get("/api/extension/connections", headers=app_auth_headers)
    assert listing.status_code == 200
    mine = [c for c in listing.json()["items"] if c["reads_today"] == 1]
    assert mine
    revoked = await app_client.post(
        f"/api/extension/connections/{mine[0]['key_id']}/revoke", headers=app_auth_headers
    )
    assert revoked.status_code == 204
    after = await app_client.get("/api/extension/me", headers=key)
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_new_connection_replaces_previous(app_client, app_auth_headers) -> None:
    old = await _connect(app_client, app_auth_headers)
    new = await _connect(app_client, app_auth_headers)
    assert (await app_client.get("/api/extension/me", headers=old)).status_code == 401
    assert (await app_client.get("/api/extension/me", headers=new)).status_code == 200


@pytest.mark.asyncio
async def test_draft_message_falls_back_without_ai(
    app_client, app_auth_headers, open_job, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.services.linkedin_message_draft.api_key_configured", lambda model: False
    )
    key = await _connect(app_client, app_auth_headers)
    resp = await app_client.post(
        "/api/extension/draft-message",
        headers=key,
        json={"job_id": open_job, "kind": "invitation", "profile": _profile("jan-testowy-draft")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ai"] is False
    assert resp.json()["text"].startswith("Cześć Jan,")
    assert len(resp.json()["text"]) <= 300
