"""Listy kandydatów „Tylko ja” / „Widzi zespół” (0519) — trasy na żywej bazie.

Baza testowa jest wspólna dla przebiegu i nie jest czyszczona, więc każdy test
zakłada własnych kandydatów i użytkowników. Osoby są zmyślone.
Część czysta: ``test_talent_pool_visibility_rule.py``.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.talent_pool import TalentPool
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _seed_candidate() -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Jan",
            lastname=f"Listowy-{_hex()}",
            email=f"lists-{_hex()}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _headers_for(app_client: AsyncClient, role: UserRole) -> dict[str, str]:
    suffix = _hex()
    email = f"lists-{role.value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Listy {role.value} {suffix}",
                role=role,
                roles=[role.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _private_list(app_client: AsyncClient, owner: dict, candidate_id: int) -> int:
    resp = await app_client.post(
        "/api/talent-pools",
        headers=owner,
        json={
            "name": f"Moja lista {_hex()}",
            "is_personal": True,
            "team_visible": False,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["team_visible"] is False
    pool_id = resp.json()["id"]
    add = await app_client.post(
        f"/api/talent-pools/{pool_id}/add",
        headers=owner,
        json={"candidate_id": candidate_id},
    )
    assert add.status_code == 201, add.text
    return pool_id


async def test_private_list_is_invisible_to_others_and_admin(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    owner = await _headers_for(app_client, UserRole.recruiter)
    other = await _headers_for(app_client, UserRole.recruiter)
    candidate_id = await _seed_candidate()
    pool_id = await _private_list(app_client, owner, candidate_id)

    mine = await app_client.get("/api/talent-pools", headers=owner)
    assert pool_id in {p["id"] for p in mine.json()}

    for viewer in (other, app_auth_headers):
        listed = await app_client.get("/api/talent-pools", headers=viewer)
        assert pool_id not in {p["id"] for p in listed.json()}
        members = await app_client.get(
            f"/api/talent-pools/{pool_id}/candidates", headers=viewer
        )
        assert members.status_code == 404
        add = await app_client.post(
            f"/api/talent-pools/{pool_id}/add",
            headers=viewer,
            json={"candidate_id": candidate_id},
        )
        assert add.status_code == 404
        patch = await app_client.patch(
            f"/api/talent-pools/{pool_id}", headers=viewer, json={"team_visible": True}
        )
        assert patch.status_code == 404
        delete = await app_client.delete(f"/api/talent-pools/{pool_id}", headers=viewer)
        assert delete.status_code == 404
        for_candidate = await app_client.get(
            f"/api/talent-pools/for-candidate/{candidate_id}", headers=viewer
        )
        assert pool_id not in for_candidate.json()["pool_ids"]

    owner_for_candidate = await app_client.get(
        f"/api/talent-pools/for-candidate/{candidate_id}", headers=owner
    )
    assert pool_id in owner_for_candidate.json()["pool_ids"]


async def test_private_list_name_never_rides_on_candidate(
    app_client: AsyncClient,
) -> None:
    owner = await _headers_for(app_client, UserRole.recruiter)
    other = await _headers_for(app_client, UserRole.recruiter)
    candidate_id = await _seed_candidate()
    pool_id = await _private_list(app_client, owner, candidate_id)

    for viewer in (owner, other):
        resp = await app_client.get(f"/api/candidates/{candidate_id}", headers=viewer)
        assert resp.status_code == 200, resp.text
        assert pool_id not in {p["id"] for p in resp.json()["talent_pools"]}


async def test_private_list_filter_returns_nothing_for_others(
    app_client: AsyncClient,
) -> None:
    owner = await _headers_for(app_client, UserRole.recruiter)
    other = await _headers_for(app_client, UserRole.recruiter)
    candidate_id = await _seed_candidate()
    pool_id = await _private_list(app_client, owner, candidate_id)

    own = await app_client.get(
        "/api/candidates", headers=owner, params={"talent_pool_id": pool_id}
    )
    assert own.status_code == 200, own.text
    assert [c["id"] for c in own.json()["items"]] == [candidate_id]

    # Odpada sama cudza lista — filtr nie znika i nie zwraca całej bazy.
    foreign = await app_client.get(
        "/api/candidates", headers=other, params={"talent_pool_id": pool_id}
    )
    assert foreign.status_code == 200, foreign.text
    assert foreign.json()["total"] == 0


async def test_owner_shares_list_with_team_and_only_owner_edits(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    owner = await _headers_for(app_client, UserRole.recruiter)
    other = await _headers_for(app_client, UserRole.recruiter)
    candidate_id = await _seed_candidate()
    pool_id = await _private_list(app_client, owner, candidate_id)

    shared = await app_client.patch(
        f"/api/talent-pools/{pool_id}",
        headers=owner,
        json={"team_visible": True, "name": "  Seniorzy do przepięcia  "},
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["team_visible"] is True
    assert shared.json()["name"] == "Seniorzy do przepięcia"
    assert shared.json()["candidate_count"] == 1

    members = await app_client.get(
        f"/api/talent-pools/{pool_id}/candidates", headers=other
    )
    assert members.status_code == 200
    assert members.json()["pool"]["team_visible"] is True
    assert [c["id"] for c in members.json()["candidates"]] == [candidate_id]

    # Widzi, ale nie zmienia — ani zawartości, ani widoczności (także admin).
    add = await app_client.post(
        f"/api/talent-pools/{pool_id}/add",
        headers=other,
        json={"candidate_id": candidate_id},
    )
    assert add.status_code == 403
    for viewer in (other, app_auth_headers):
        patch = await app_client.patch(
            f"/api/talent-pools/{pool_id}", headers=viewer, json={"team_visible": False}
        )
        assert patch.status_code == 403

    blank = await app_client.patch(
        f"/api/talent-pools/{pool_id}", headers=owner, json={"name": "   "}
    )
    assert blank.status_code == 422


async def test_company_pool_cannot_be_patched(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    async with AsyncSessionLocal() as db:
        pool = TalentPool(name=f"Firmowa {_hex()}", criteria={})
        db.add(pool)
        await db.commit()
        await db.refresh(pool)
        pool_id = pool.id
    resp = await app_client.patch(
        f"/api/talent-pools/{pool_id}", headers=app_auth_headers, json={"name": "Nowa"}
    )
    assert resp.status_code == 409


async def test_legacy_personal_pool_stays_team_visible(
    app_client: AsyncClient,
) -> None:
    # Pula osobista z /talents bez pola widoczności = jak przed 0519.
    owner = await _headers_for(app_client, UserRole.recruiter)
    other = await _headers_for(app_client, UserRole.recruiter)
    resp = await app_client.post(
        "/api/talent-pools",
        headers=owner,
        json={"name": f"Stara {_hex()}", "is_personal": True},
    )
    assert resp.status_code == 201
    assert resp.json()["team_visible"] is True
    listed = await app_client.get("/api/talent-pools", headers=other)
    assert resp.json()["id"] in {p["id"] for p in listed.json()}
