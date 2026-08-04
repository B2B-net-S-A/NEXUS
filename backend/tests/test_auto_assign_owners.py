"""Unit tests for `resolve_default_owners` — the pure client→(TAC,DL) resolver."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client import Client
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole
from app.services.auto_assign_owners import (
    ResolvedOwners,
    resolve_default_owners,
)


pytestmark = pytest.mark.asyncio


async def _new_user(db, *, role: UserRole, is_active: bool = True) -> User:
    suffix = uuid.uuid4().hex[:8]
    u = User(
        email=f"resolver-{role.value}-{suffix}@example.com",
        password_hash=hash_password("P@ssw0rd"),
        name=f"Resolver {role.value} {suffix}",
        role=role,
        is_active=is_active,
    )
    db.add(u)
    await db.flush()
    return u


async def _new_client(db) -> Client:
    suffix = uuid.uuid4().hex[:8]
    c = Client(name=f"Resolver Client {suffix}")
    db.add(c)
    await db.flush()
    return c


@pytest_asyncio.fixture
async def seeded_client_with_team():
    async with AsyncSessionLocal() as db:
        client = await _new_client(db)
        tac_primary = await _new_user(db, role=UserRole.tac)
        tac_backup = await _new_user(db, role=UserRole.tac)
        dl_head = await _new_user(db, role=UserRole.delivery_lead)
        dl_aux = await _new_user(db, role=UserRole.delivery_lead)

        db.add_all(
            [
                ClientTacAssignment(
                    tac_user_id=tac_primary.id,
                    client_id=client.id,
                    is_primary=True,
                ),
                ClientTacAssignment(
                    tac_user_id=tac_backup.id,
                    client_id=client.id,
                    is_primary=False,
                ),
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=dl_head.id,
                    client_id=client.id,
                    is_head=True,
                ),
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=dl_aux.id,
                    client_id=client.id,
                    is_head=False,
                ),
            ]
        )
        await db.commit()

        yield {
            "client_id": client.id,
            "tac_primary_id": tac_primary.id,
            "tac_backup_id": tac_backup.id,
            "dl_head_id": dl_head.id,
            "dl_aux_id": dl_aux.id,
        }

        # Cleanup — cascade on client deletes both assignment tables.
        await db.execute(
            ClientTacAssignment.__table__.delete().where(
                ClientTacAssignment.client_id == client.id
            )
        )
        await db.execute(
            DeliveryLeadClientAssignment.__table__.delete().where(
                DeliveryLeadClientAssignment.client_id == client.id
            )
        )
        await db.delete(client)
        for u in (tac_primary, tac_backup, dl_head, dl_aux):
            await db.delete(u)
        await db.commit()


@pytest.mark.unit
async def test_resolve_refuses_legacy_primary_when_multiple_tacs(
    seeded_client_with_team,
):
    data = seeded_client_with_team
    async with AsyncSessionLocal() as db:
        resolved = await resolve_default_owners(db, data["client_id"])
    assert isinstance(resolved, ResolvedOwners)
    assert resolved.tac_id is None
    assert resolved.delivery_lead_id == data["dl_head_id"]
    assert resolved.tac_selection_required is True


@pytest.mark.unit
async def test_resolve_none_client_id_no_sql():
    async with AsyncSessionLocal() as db:
        resolved = await resolve_default_owners(db, None)
    assert resolved == ResolvedOwners(tac_id=None, delivery_lead_id=None)


@pytest.mark.unit
async def test_resolve_returns_sole_active_tac_regardless_of_legacy_primary():
    async with AsyncSessionLocal() as db:
        client = await _new_client(db)
        # Legacy client-primary is unrelated to safe Job ownership.
        tac = await _new_user(db, role=UserRole.tac)
        db.add(
            ClientTacAssignment(
                tac_user_id=tac.id, client_id=client.id, is_primary=False
            )
        )
        await db.commit()

        resolved = await resolve_default_owners(db, client.id)
        assert resolved.tac_id == tac.id
        assert resolved.delivery_lead_id is None
        assert resolved.tac_selection_required is False

        # Cleanup
        await db.execute(
            ClientTacAssignment.__table__.delete().where(
                ClientTacAssignment.client_id == client.id
            )
        )
        await db.delete(client)
        await db.delete(tac)
        await db.commit()


@pytest.mark.unit
async def test_resolve_skips_inactive_primary_tac():
    async with AsyncSessionLocal() as db:
        client = await _new_client(db)
        inactive = await _new_user(db, role=UserRole.tac, is_active=False)
        db.add(
            ClientTacAssignment(
                tac_user_id=inactive.id,
                client_id=client.id,
                is_primary=True,
            )
        )
        await db.commit()

        resolved = await resolve_default_owners(db, client.id)
        assert resolved.tac_id is None

        # Cleanup
        await db.execute(
            ClientTacAssignment.__table__.delete().where(
                ClientTacAssignment.client_id == client.id
            )
        )
        await db.delete(client)
        await db.delete(inactive)
        await db.commit()


@pytest.mark.unit
async def test_partial_unique_index_blocks_two_primary_tacs():
    """Belt-and-suspenders: DB constraint must reject a second primary TAC."""
    import sqlalchemy.exc

    async with AsyncSessionLocal() as db:
        client = await _new_client(db)
        a = await _new_user(db, role=UserRole.tac)
        b = await _new_user(db, role=UserRole.tac)

        db.add(
            ClientTacAssignment(tac_user_id=a.id, client_id=client.id, is_primary=True)
        )
        await db.commit()

        # Attempting a second primary row should violate uq_client_primary_tac.
        # Use a fresh session so the first commit is fully settled in DB before
        # we try to insert a conflicting row.
        async with AsyncSessionLocal() as db2:
            db2.add(
                ClientTacAssignment(
                    tac_user_id=b.id, client_id=client.id, is_primary=True
                )
            )
            with pytest.raises(sqlalchemy.exc.IntegrityError):
                await db2.commit()
            await db2.rollback()

        # Cleanup
        await db.execute(
            ClientTacAssignment.__table__.delete().where(
                ClientTacAssignment.client_id == client.id
            )
        )
        await db.delete(client)
        await db.delete(a)
        await db.delete(b)
        await db.commit()
