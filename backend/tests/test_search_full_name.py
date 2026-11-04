"""Wyszukiwanie po imieniu i nazwisku razem (Jarvis, 27.10.2026).

`GET /api/search/global` (narzędzie Jarvisa `global_search`) i `GET /api/search/`
porównywały całą frazę „Imię Nazwisko” osobno z ``name`` i ``lastname`` —
żadna kolumna nie zawiera spacji, więc osoba wpisana razem z imieniem „nie
istniała”. Na produkcji 7 osób z 30 dni rozmów było w bazie, a Jarvis
odpowiadał „nie ma”. Osoby są zmyślone; baza testowa nie jest czyszczona,
więc nazwiska niosą losowy przyrostek.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate, CandidateStatus
from app.models.user import User, UserRole


async def _seed_candidate() -> tuple[str, str, int]:
    nonce = uuid.uuid4().hex[:8]
    first, last = f"Bożena{nonce}", f"Wąsik{nonce}"
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=first,
            lastname=last,
            email=f"fullname-{nonce}@example.com",
            status=CandidateStatus.active,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return first, last, cand.id


async def _headers_for(app_client: AsyncClient, role: UserRole) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"fullname-{role.value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Szukanie {role.value}",
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


@pytest.mark.asyncio
@pytest.mark.parametrize("order", ["first_last", "last_first"])
async def test_global_search_finds_first_and_last_name_together(
    app_client, app_auth_headers, order
):
    first, last, cand_id = await _seed_candidate()
    q = f"{first} {last}" if order == "first_last" else f"{last} {first}"
    resp = await app_client.get(
        "/api/search/global", params={"q": q}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert cand_id in {c["id"] for c in resp.json()["candidates"]}


@pytest.mark.asyncio
async def test_unified_search_finds_first_and_last_name_together(
    app_client, app_auth_headers
):
    first, last, cand_id = await _seed_candidate()
    resp = await app_client.get(
        "/api/search/",
        params={"q": f"{first} {last}", "entity": "candidates"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert cand_id in {c["id"] for c in resp.json()["results"]["candidates"]}


@pytest.mark.asyncio
async def test_global_search_does_not_glue_unrelated_names(
    app_client, app_auth_headers
):
    """Imię jednej osoby + nazwisko drugiej to nie trafienie."""
    first, _last, _ = await _seed_candidate()
    _first2, last2, _ = await _seed_candidate()
    resp = await app_client.get(
        "/api/search/global",
        params={"q": f"{first} {last2}"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidates"] == []


@pytest.mark.asyncio
async def test_global_search_names_sections_the_role_cannot_see(app_client):
    """Rekruter nie ma sekcji Klienci: pusta kategoria to „nie widzisz”, nie „nie ma”."""
    headers = await _headers_for(app_client, UserRole.recruiter)
    resp = await app_client.get(
        "/api/search/global", params={"q": "zz"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    skipped = {s["category"] for s in resp.json()["skipped"]}
    assert "clients" in skipped
    assert "candidates" not in skipped


@pytest.mark.asyncio
async def test_global_search_admin_skips_nothing(app_client, app_auth_headers):
    resp = await app_client.get(
        "/api/search/global", params={"q": "zz"}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["skipped"] == []
