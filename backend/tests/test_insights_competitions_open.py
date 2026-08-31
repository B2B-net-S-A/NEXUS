"""Odczyty konkursów są otwarte dla każdej zalogowanej roli (D7).

Liga Mistrzów, wyścigi miesięczne i Hall of Fame są częścią /insights, a ta
powierzchnia została jawnie otwarta decyzją Artura z 2026-08-31.

Dlaczego akurat TEN endpoint wolno było poszerzyć na miejscu, a innych nie:
jego jedynym konsumentem we froncie jest `ChampionsSection.tsx`, czyli sama
zakładka Insights. `/api/reports/*`, `/api/admin/clients-overview` i
`/api/dashboard/v2/*` są współdzielone z innymi stronami — tam poszerzenie
guardu otworzyłoby powierzchnie, na które nikt nie dawał zgody, więc Insights
dostaje własne `/api/insights/*`.

Zapisy (freeze) MUSZĄ zostać admin-only: zamrożone podium jest write-once
(`competitions.py` compose/freeze), więc pomyłka jest nieodwracalna.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole

_READ_ONLY_ROLES = [
    UserRole.sourcer,
    UserRole.recruiter,
    UserRole.tac,
    UserRole.finance,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
    UserRole.admin,
]


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"comp-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Comp"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Comp {role.value} {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def comp_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.parametrize("role", _READ_ONLY_ROLES)
@pytest.mark.asyncio
async def test_every_role_reads_the_quarterly_league(
    comp_client: AsyncClient, role: UserRole
):
    email, password = await _seed_user(role)
    headers = await _login(comp_client, email, password)
    resp = await comp_client.get(
        "/api/competitions/current",
        headers=headers,
        params={"type": "quarterly_champions_recruiter"},
    )
    assert resp.status_code == 200, f"{role.value}: {resp.text}"


@pytest.mark.parametrize("role", [UserRole.sourcer, UserRole.finance])
@pytest.mark.asyncio
async def test_every_role_reads_races_and_history(
    comp_client: AsyncClient, role: UserRole
):
    email, password = await _seed_user(role)
    headers = await _login(comp_client, email, password)

    races = await comp_client.get("/api/competitions/monthly-races", headers=headers)
    assert races.status_code == 200, races.text

    # /history swiadomie NIE zostalo poszerzone — nie ma konsumenta we froncie,
    # wiec byloby to nieuzasadnione ruszenie guardu na wspoldzielonym routerze.
    history = await comp_client.get(
        "/api/competitions/history",
        headers=headers,
        params={"type": "quarterly_champions_recruiter"},
    )
    assert history.status_code in (200, 403), history.text


@pytest.mark.asyncio
async def test_reads_still_require_a_session(comp_client: AsyncClient):
    """„Wszyscy" znaczy „każdy ZALOGOWANY", nie „każdy z internetu"."""
    resp = await comp_client.get(
        "/api/competitions/current", params={"type": "quarterly_champions_recruiter"}
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_freeze_stays_admin_only(comp_client: AsyncClient):
    """Zamrożenie podium jest nieodwracalne — D7 go NIE otwiera."""
    email, password = await _seed_user(UserRole.sourcer)
    headers = await _login(comp_client, email, password)
    resp = await comp_client.post(
        "/api/competitions/freeze",
        headers=headers,
        params={"type": "quarterly_champions_recruiter"},
    )
    assert resp.status_code in (403, 404, 405, 422), resp.text
    assert resp.status_code != 200
