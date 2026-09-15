"""F02 (audyt 14.09.2026) przez HTTP: odebrana sekcja zamyka też API.

``test_section_ceiling_contract.py`` sprawdza strukturę (każda trasa ma bramkę).
Ten plik sprawdza zachowanie na prawdziwej sesji: recruiter z nadpisaniem
sekcji na ``none`` (albo ``read`` przy zapisie) dostaje 403
``section_access_denied`` na trasach, które do 09.2026 sprawdzały same role —
a ten sam recruiter bez nadpisania przez bramkę sekcji przechodzi.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.section_permission import UserSectionOverride
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


async def _recruiter(overrides: dict[str, str]) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"section-revoke-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Revoke"),
            name=f"Section revoke {tag}",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        for section, access in overrides.items():
            db.add(UserSectionOverride(user_id=user.id, section=section, access=access))
        await db.commit()
        user_id = user.id
    return {"Authorization": f"Bearer {create_access_token(user_id, 'recruiter')}"}


def _is_section_denial(resp) -> bool:
    if resp.status_code != 403:
        return False
    detail = resp.json().get("detail")
    return isinstance(detail, dict) and detail.get("code") == "section_access_denied"


_CASES = [
    ("GET", "/api/kpis/me/today", {"insights": "none"}),
    ("GET", "/api/cortex/skills", {"insights": "none"}),
    ("GET", "/api/rejection-emails/by-candidate/1", {"pipeline": "none"}),
    ("GET", "/api/dashboard/v2/my-work", {"pipeline": "none"}),
    ("GET", "/api/priority-work/mine", {"pipeline": "none"}),
    (
        "GET",
        "/api/presence/candidate/1/viewers",
        {"sourcing": "none", "pipeline": "none"},
    ),
    (
        "GET",
        "/api/activities/feed",
        {"sourcing": "none", "pipeline": "none", "delivery": "none"},
    ),
    (
        "GET",
        "/api/jobs-lookup",
        {"sourcing": "none", "pipeline": "none", "insights": "none"},
    ),
]


@pytest.mark.parametrize(
    ("method", "path", "overrides"), _CASES, ids=[c[1] for c in _CASES]
)
async def test_revoked_section_closes_formerly_role_only_route(
    app_client: AsyncClient, method: str, path: str, overrides: dict[str, str]
):
    revoked = await _recruiter(overrides)
    resp = await app_client.request(method, path, headers=revoked)
    assert _is_section_denial(resp), (resp.status_code, resp.text)

    granted = await _recruiter({})
    resp = await app_client.request(method, path, headers=granted)
    assert not _is_section_denial(resp), (resp.status_code, resp.text)


async def test_read_only_sourcing_cannot_trigger_fireflies_sync(
    app_client: AsyncClient,
):
    """Synchronizacja zapisuje notatki: sam odczyt Sourcing nie wystarcza."""
    headers = await _recruiter({"sourcing": "read"})
    resp = await app_client.post("/api/fireflies/sync", headers=headers)
    assert _is_section_denial(resp), (resp.status_code, resp.text)
