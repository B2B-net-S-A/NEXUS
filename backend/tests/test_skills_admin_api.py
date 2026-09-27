"""`/api/skills-admin` — Słownik umiejętności (kuracja przeniesiona z Cortexa, 23.09.2026).

Kontrakt: admin i Head of Recruitment (``HeadOfRecruitmentPlus``) z zapisem
sekcji Sourcing; rekruter dostaje 403. Zapis odświeża aliasy scoringu, więc
nowy alias od razu rozpoznaje ``scoring_service.ALIAS_MAP`` (autouse fixture
``_isolate_skill_taxonomy`` przywraca taksonomię po teście).

In-process ``app_client``; baza wspólna i nieczyszczona — nazwy z uuid.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal

pytestmark = pytest.mark.asyncio


async def _login_as(app_client: AsyncClient, role) -> dict[str, str]:
    from app.core.security import hash_password
    from app.models.user import User

    unique = uuid.uuid4().hex[:8]
    email = f"skills-admin-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Skl"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Skills admin {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_term(term: str) -> int:
    from app.models.cortex import CortexUnmatchedTerm

    async with AsyncSessionLocal() as db:
        row = CortexUnmatchedTerm(term=term, occurrences=3, status="new")
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def test_recruiter_cannot_read_or_write_the_dictionary(app_client: AsyncClient):
    from app.models.user import UserRole

    headers = await _login_as(app_client, UserRole.recruiter)
    assert (
        await app_client.get("/api/skills-admin/skills", headers=headers)
    ).status_code == 403
    resp = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Nope {uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_head_of_recruitment_creates_skill_and_alias(app_client: AsyncClient):
    from app.models.user import UserRole
    from app.services import scoring_service

    headers = await _login_as(app_client, UserRole.head_of_recruitment)
    name = f"Skilltest {uuid.uuid4().hex[:8]}"
    created = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": name, "aliases": ["  Alias-A  "]},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    skill_id = created.json()["id"]

    alias = f"alias-{uuid.uuid4().hex[:8]}"
    added = await app_client.post(
        f"/api/skills-admin/skills/{skill_id}/aliases",
        json={"alias": alias.upper()},
        headers=headers,
    )
    assert added.status_code == 200, added.text
    assert added.json() == {"skill_id": skill_id, "alias": alias, "inserted": True}
    # Zapis odświeża aliasy scoringu — nowy alias działa od razu.
    assert alias in scoring_service.ALIAS_MAP

    listed = await app_client.get(
        "/api/skills-admin/skills", params={"q": alias}, headers=headers
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == name
    assert alias in body["items"][0]["aliases"]

    duplicate = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": name.upper()},
        headers=headers,
    )
    assert duplicate.status_code == 400


async def test_admin_maps_and_ignores_unmatched_terms(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    name = f"Maptarget {uuid.uuid4().hex[:8]}"
    created = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": name},
        headers=app_auth_headers,
    )
    skill_id = created.json()["id"]
    mapped_term = f"term-{uuid.uuid4().hex[:8]}"
    ignored_term = f"term-{uuid.uuid4().hex[:8]}"
    mapped_id = await _seed_term(mapped_term)
    ignored_id = await _seed_term(ignored_term)

    queue = await app_client.get(
        "/api/skills-admin/unmatched-terms",
        params={"status": "new", "limit": 500},
        headers=app_auth_headers,
    )
    assert queue.status_code == 200, queue.text
    assert {mapped_id, ignored_id} <= {row["id"] for row in queue.json()}

    resp = await app_client.post(
        f"/api/skills-admin/unmatched-terms/{mapped_id}/map",
        json={"skill_id": skill_id},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "mapped"

    resp = await app_client.post(
        f"/api/skills-admin/unmatched-terms/{ignored_id}/ignore",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    listed = await app_client.get(
        "/api/skills-admin/skills", params={"q": name}, headers=app_auth_headers
    )
    assert mapped_term in listed.json()["items"][0]["aliases"]

    missing = await app_client.post(
        "/api/skills-admin/unmatched-terms/2000000000/ignore",
        headers=app_auth_headers,
    )
    assert missing.status_code == 400


async def test_alias_equal_to_another_skills_name_is_refused(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """R9-N13-3: alias „java” dopisany do JavaScriptu przepinał Javę w scoringu
    (alias wygrywa z nazwą kanoniczną w ALIAS_MAP)."""
    from app.services import scoring_service

    suffix = uuid.uuid4().hex[:8]
    first = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Langa {suffix}"},
        headers=app_auth_headers,
    )
    second = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Langb {suffix}"},
        headers=app_auth_headers,
    )
    assert first.status_code == 200 and second.status_code == 200
    second_id = second.json()["id"]

    resp = await app_client.post(
        f"/api/skills-admin/skills/{second_id}/aliases",
        json={"alias": f"LANGA {suffix}"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "nazwa innej umiejętności" in resp.json()["detail"]
    assert scoring_service.ALIAS_MAP.get(f"langa {suffix}") != f"Langb {suffix}"

    # Nowa umiejętność z aliasem równym nazwie istniejącej — odmowa, nic nie powstaje.
    third = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Langc {suffix}", "aliases": [f"langa {suffix}"]},
        headers=app_auth_headers,
    )
    assert third.status_code == 409, third.text
    listed = await app_client.get(
        "/api/skills-admin/skills",
        params={"q": f"langc {suffix}"},
        headers=app_auth_headers,
    )
    assert listed.json()["total"] == 0


async def test_skill_name_equal_to_existing_alias_is_refused(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """R9-N13-3: umiejętność o nazwie równej istniejącemu aliasowi byłaby
    nieosiągalna — mapa scoringu kieruje ten tekst na właściciela aliasu."""
    suffix = uuid.uuid4().hex[:8]
    owner = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Owner {suffix}", "aliases": [f"shared-{suffix}"]},
        headers=app_auth_headers,
    )
    assert owner.status_code == 200, owner.text

    resp = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Shared-{suffix.upper()}"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "aliasem" in resp.json()["detail"]


async def test_term_owned_by_another_skill_is_not_marked_mapped(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """R9-N13-3: gdy termin jest już aliasem INNEJ umiejętności, mapowanie
    nie dodaje aliasu — więc termin nie może dostać statusu „mapped”."""
    from app.models.cortex import CortexUnmatchedTerm

    suffix = uuid.uuid4().hex[:8]
    term = f"dup-{suffix}"
    owner = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Tfirst {suffix}", "aliases": [term]},
        headers=app_auth_headers,
    )
    other = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Tsecond {suffix}"},
        headers=app_auth_headers,
    )
    assert owner.status_code == 200 and other.status_code == 200
    term_id = await _seed_term(term)

    resp = await app_client.post(
        f"/api/skills-admin/unmatched-terms/{term_id}/map",
        json={"skill_id": other.json()["id"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text

    created = await app_client.post(
        "/api/skills-admin/skills",
        json={"canonical_name": f"Tthird {suffix}", "from_term_id": term_id},
        headers=app_auth_headers,
    )
    assert created.status_code == 409, created.text

    async with AsyncSessionLocal() as db:
        row = await db.get(CortexUnmatchedTerm, term_id)
        assert row.status == "new"

    # Mapowanie na właściciela aliasu jest w porządku.
    ok = await app_client.post(
        f"/api/skills-admin/unmatched-terms/{term_id}/map",
        json={"skill_id": owner.json()["id"]},
        headers=app_auth_headers,
    )
    assert ok.status_code == 200, ok.text
