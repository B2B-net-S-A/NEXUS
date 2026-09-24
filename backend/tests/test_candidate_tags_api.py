"""Tagi kandydata: dodaj / usuń jeden tag, podpowiedzi, filtr listy (PR2).

Pokrywa:

- dodanie zachowuje obiekty importu Traffita i nie dubluje tagu (bez
  wielkości liter); usunięcie zdejmuje tylko wskazany napis;
- walidacja (pusty, przecinek, za długi) → 422; nieistniejący kandydat → 404;
- rola bez zapisu kandydatów (viewer ``user``) → 403;
- ``/tags/suggest`` nie wpada w ``/{candidate_id}`` i zlicza tylko napisy;
- filtr listy ``tags=`` znajduje kandydata po dodanym tagu (cały tag).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio

_TRAFFIT_SOURCE = {
    "type": "traffit_source",
    "value": "LinkedIn",
    "domain": "linkedin.com",
    "url": None,
}


async def _seed_candidate(tags) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Tag",
            lastname=f"Test{uuid.uuid4().hex[:6]}",
            email=f"tags-{uuid.uuid4().hex[:8]}@example.com",
            tags=tags,
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _viewer_headers(app_client) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"tags-viewer-{unique}@example.com"
    password = f"T3st_{unique}!Viewer"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Viewer",
                role=UserRole.user,
                is_active=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_add_keeps_import_objects_and_is_idempotent(app_client, app_auth_headers):
    cid = await _seed_candidate(["senior", _TRAFFIT_SOURCE])

    resp = await app_client.post(
        f"/api/candidates/{cid}/tags",
        json={"tag": "  Kafka   Streams "},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changed"] is True
    assert body["tags"] == ["senior", _TRAFFIT_SOURCE, "Kafka Streams"]

    again = await app_client.post(
        f"/api/candidates/{cid}/tags", json={"tag": "SENIOR"}, headers=app_auth_headers
    )
    assert again.status_code == 200
    assert again.json()["changed"] is False
    assert again.json()["tags"] == ["senior", _TRAFFIT_SOURCE, "Kafka Streams"]

    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, cid)
        assert cand.tags == ["senior", _TRAFFIT_SOURCE, "Kafka Streams"]
        logged = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == cid,
                Activity.action == "tags_changed",
            )
        )
        assert logged is not None and logged.details == {"added": "Kafka Streams"}


async def test_remove_only_the_named_string(app_client, app_auth_headers):
    cid = await _seed_candidate(["senior", "Java", _TRAFFIT_SOURCE])

    resp = await app_client.delete(
        f"/api/candidates/{cid}/tags",
        params={"tag": "java"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"tags": ["senior", _TRAFFIT_SOURCE], "changed": True}

    missing = await app_client.delete(
        f"/api/candidates/{cid}/tags",
        params={"tag": "nie-ma"},
        headers=app_auth_headers,
    )
    assert missing.status_code == 200
    assert missing.json()["changed"] is False

    # Obiekt importu nie jest tagiem-napisem — nie da się go zdjąć po nazwie.
    obj = await app_client.delete(
        f"/api/candidates/{cid}/tags",
        params={"tag": "LinkedIn"},
        headers=app_auth_headers,
    )
    assert obj.json()["changed"] is False


@pytest.mark.parametrize("bad", ["", "   ", "a,b", "x" * 65])
async def test_invalid_tag_is_422(app_client, app_auth_headers, bad):
    cid = await _seed_candidate([])
    resp = await app_client.post(
        f"/api/candidates/{cid}/tags", json={"tag": bad}, headers=app_auth_headers
    )
    assert resp.status_code == 422


async def test_unknown_candidate_is_404(app_client, app_auth_headers):
    resp = await app_client.post(
        "/api/candidates/999999999/tags", json={"tag": "x"}, headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_viewer_cannot_edit_tags(app_client):
    cid = await _seed_candidate(["senior"])
    headers = await _viewer_headers(app_client)
    resp = await app_client.post(
        f"/api/candidates/{cid}/tags", json={"tag": "x"}, headers=headers
    )
    assert resp.status_code == 403
    resp = await app_client.delete(
        f"/api/candidates/{cid}/tags", params={"tag": "senior"}, headers=headers
    )
    assert resp.status_code == 403


async def test_suggest_counts_strings_only_and_routes_before_candidate_id(
    app_client, app_auth_headers
):
    prefix = f"zq{uuid.uuid4().hex[:6]}"
    await _seed_candidate([f"{prefix}-alfa", _TRAFFIT_SOURCE])
    await _seed_candidate([f"{prefix}-Alfa", f"{prefix}-beta"])
    await _seed_candidate([f"{prefix}-alfa"])

    resp = await app_client.get(
        "/api/candidates/tags/suggest",
        params={"q": prefix.upper()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {"name": f"{prefix}-alfa", "count": 3},
        {"name": f"{prefix}-beta", "count": 1},
    ]


async def test_list_filter_finds_added_tag(app_client, app_auth_headers):
    tag = f"flt{uuid.uuid4().hex[:6]}"
    cid = await _seed_candidate(["senior"])
    other = await _seed_candidate([f"{tag}x"])
    add = await app_client.post(
        f"/api/candidates/{cid}/tags", json={"tag": tag}, headers=app_auth_headers
    )
    assert add.status_code == 200

    resp = await app_client.get(
        "/api/candidates",
        params={"tags": tag, "semantics_version": 2, "page_size": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()["items"]}
    assert cid in ids
    assert other not in ids  # cały tag, nie podłańcuch
