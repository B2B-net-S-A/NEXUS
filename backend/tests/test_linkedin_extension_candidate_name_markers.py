"""External LinkedIn creates retain the shared D6 name-marker cleanup policy."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate

EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture(autouse=True)
def _isolated_extension(monkeypatch):
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_IDS", EXTENSION_ID)
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_ENABLED", True)

    async def _no_external_calls(*args, **kwargs):  # noqa: ARG001
        return None

    monkeypatch.setattr(
        "app.services.index_outbox_service.schedule_or_embed_candidate",
        _no_external_calls,
    )
    monkeypatch.setattr(
        "app.services.teams_notifications.notify_teams", _no_external_calls
    )


async def _connect(client, headers):
    response = await client.post(
        "/api/extension/connect",
        headers=headers,
        json={"extension_id": EXTENSION_ID, "extension_version": "1.0.1"},
    )
    assert response.status_code == 200, response.text
    return {"X-Extension-Key": response.json()["key"]}


def _profile(full_name):
    slug = f"synthetic-name-marker-{uuid.uuid4().hex}"
    return {
        "full_name": full_name,
        "public_url": f"https://www.linkedin.com/in/{slug}/",
        "page_url": f"https://www.linkedin.com/in/{slug}/",
    }


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("[ACTIVE] Jan Kowalski", ("Jan", "Kowalski")),
        ("Jan Kowalski [ACTIVE]", ("Jan", "Kowalski")),
        ("Łukasz Żółć-Ćwiek", ("Łukasz", "Żółć-Ćwiek")),
    ],
)
async def test_extension_create_silently_cleans_markers_and_preserves_polish_name(
    app_client, app_auth_headers, full_name, expected
):
    headers = await _connect(app_client, app_auth_headers)
    profile = _profile(full_name)

    response = await app_client.post(
        "/api/extension/candidates", headers=headers, json={"profile": profile}
    )

    assert response.status_code == 201, response.text
    assert response.json()["created"] is True
    assert response.json()["assigned_job_ids"] == []
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, response.json()["candidate_id"])
        assert (candidate.name, candidate.lastname) == expected


@pytest.mark.parametrize("full_name", ["[ACTIVE]", "[ACTIVE] [PASSIVE]"])
async def test_extension_marker_only_name_returns_422_without_creating_a_stub(
    app_client, app_auth_headers, full_name
):
    headers = await _connect(app_client, app_auth_headers)
    profile = _profile(full_name)
    slug = profile["public_url"].rstrip("/").rsplit("/", 1)[1]

    response = await app_client.post(
        "/api/extension/candidates", headers=headers, json={"profile": profile}
    )

    assert response.status_code == 422, response.text
    assert "Wpisz imię i nazwisko" in response.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(Candidate.id).where(Candidate.linkedin.ilike(f"%{slug}%"))
            )
            is None
        )


async def test_extension_known_link_keeps_the_existing_candidate_identity(
    app_client, app_auth_headers
):
    profile = _profile("[ACTIVE] Jan Kowalski")
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Anna", lastname="Przykładowa", linkedin=profile["public_url"]
        )
        db.add(candidate)
        await db.commit()
        candidate_id = candidate.id
    headers = await _connect(app_client, app_auth_headers)

    response = await app_client.post(
        "/api/extension/candidates", headers=headers, json={"profile": profile}
    )

    assert response.status_code == 200, response.text
    assert response.json()["created"] is False
    assert response.json()["candidate_id"] == candidate_id
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert (candidate.name, candidate.lastname) == ("Anna", "Przykładowa")
