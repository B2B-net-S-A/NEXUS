"""Tests for `GET /api/team-structure/dl-clients` deduplication (PR4).

Bug context: QA 2026-05-27 noticed every DL appearing twice in DL Hub
"Przypisani Klienci" table. Root cause = post-migration each DL has two
active accounts (legacy @b2bnetwork.pl + new @inframinds.eu). Endpoint
must group by normalized name and merge client lists.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _seed_dl_user(email: str, name: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password("Test_dedup!Pass123"),
            name=name,
            role=UserRole.delivery_lead,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_client(name: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=name)
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _assign(dl_id: int, client_id: int, is_head: bool = False) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.team_structure import DeliveryLeadClientAssignment

    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id,
                client_id=client_id,
                is_head=is_head,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_dl_clients_deduplicates_same_person_two_accounts(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Same display-name across @b2bnetwork.pl + @inframinds.eu → 1 row."""
    suffix = uuid.uuid4().hex[:6]
    name = f"DedupTest {suffix}"
    legacy_id = await _seed_dl_user(f"dedup-legacy-{suffix}@b2bnetwork.pl", name)
    new_id = await _seed_dl_user(f"dedup-new-{suffix}@inframinds.eu", name)

    cli_a = await _seed_client(f"DedupClient-A-{suffix}")
    cli_b = await _seed_client(f"DedupClient-B-{suffix}")
    await _assign(legacy_id, cli_a, is_head=True)
    await _assign(new_id, cli_b, is_head=False)

    resp = await app_client.get(
        "/api/team-structure/dl-clients", headers=app_auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()

    matching = [r for r in body if r["delivery_lead"]["name"] == name]
    assert len(matching) == 1, (
        f"Expected 1 row after dedup, got {len(matching)}: {matching}"
    )
    row = matching[0]
    # Canonical user_id = the one with more clients (tie → higher id =
    # newer @inframinds.eu); both have 1 client → expect new_id (higher).
    assert row["delivery_lead"]["id"] == new_id
    # Clients from both accounts merged
    client_ids = {c["id"] for c in row["clients"]}
    assert client_ids == {cli_a, cli_b}


@pytest.mark.asyncio
async def test_dl_clients_dedup_preserves_is_head_or(
    app_client: AsyncClient, app_auth_headers: dict
):
    """If any sibling has is_head=True for a shared client, merged row keeps it."""
    suffix = uuid.uuid4().hex[:6]
    name = f"HeadFlagTest {suffix}"
    legacy_id = await _seed_dl_user(f"head-legacy-{suffix}@b2bnetwork.pl", name)
    new_id = await _seed_dl_user(f"head-new-{suffix}@inframinds.eu", name)

    cli = await _seed_client(f"SharedClient-{suffix}")
    # Same client assigned to BOTH accounts; head=True only on legacy.
    await _assign(legacy_id, cli, is_head=True)
    await _assign(new_id, cli, is_head=False)

    resp = await app_client.get(
        "/api/team-structure/dl-clients", headers=app_auth_headers
    )
    assert resp.status_code == 200
    matching = [r for r in resp.json() if r["delivery_lead"]["name"] == name]
    assert len(matching) == 1
    clients = matching[0]["clients"]
    assert len(clients) == 1
    assert clients[0]["id"] == cli
    assert clients[0]["is_head"] is True


@pytest.mark.asyncio
async def test_dl_clients_normalizes_diacritics_and_dl_suffix(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`Rosol` and `Rosół (DL)` should collapse into one row."""
    suffix = uuid.uuid4().hex[:6]
    legacy_id = await _seed_dl_user(
        f"diacritic-{suffix}@b2bnetwork.pl", f"TestRosol {suffix}"
    )
    new_id = await _seed_dl_user(
        f"diacritic-{suffix}@inframinds.eu", f"TestRosół {suffix} (DL)"
    )

    cli = await _seed_client(f"DiacClient-{suffix}")
    await _assign(new_id, cli)

    resp = await app_client.get(
        "/api/team-structure/dl-clients", headers=app_auth_headers
    )
    assert resp.status_code == 200
    # Both names should collapse — search for either base form.
    matching = [
        r for r in resp.json() if r["delivery_lead"]["id"] in {legacy_id, new_id}
    ]
    assert len(matching) == 1, (
        f"Expected 1 row after diacritic dedup, got {len(matching)}"
    )
