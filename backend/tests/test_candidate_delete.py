"""Tests for `DELETE /api/candidates/{candidate_id}` — hard delete from the DB.

Removing a candidate is a permanent hard delete (no soft-delete column). It must
succeed atomically even when the candidate has related rows in tables whose FK to
``candidates.id`` previously lacked an ``ON DELETE`` rule (contracts, screening
notes, talent-pool memberships, match history) — migration ``0141`` added the
cascade so the delete no longer fails with a foreign-key violation. Notes and
other ORM-cascade children are removed too.

Guard: only ``admin`` / ``delivery_lead`` (``DeliveryLeadPlus``).

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures from conftest
(real postgres in CI).
"""

from __future__ import annotations

import uuid
from datetime import date

from httpx import AsyncClient
from sqlalchemy import func, select


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Del",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"del-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_note(candidate_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note

    async with AsyncSessionLocal() as db:
        note = Note(candidate_id=candidate_id, content="zostanie usunięta z kandydatem")
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return note.id


async def _seed_contract(candidate_id: int) -> int:
    """A contract is a previously-blocking relation (FK had no ON DELETE)."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"DelClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        contract = Contract(
            candidate_id=candidate_id,
            client_id=cli.id,
            start_date=date(2026, 1, 1),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _count(model, **filters) -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        stmt = select(func.count()).select_from(model)
        for col, val in filters.items():
            stmt = stmt.where(getattr(model, col) == val)
        return int(await db.scalar(stmt) or 0)


async def test_delete_candidate_requires_auth(app_client: AsyncClient):
    r = await app_client.delete("/api/candidates/1")
    # FastAPI HTTPBearer returns 403 when the Authorization header is missing.
    assert r.status_code in (401, 403)


async def test_delete_candidate_404_when_missing(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.delete("/api/candidates/999000111", headers=app_auth_headers)
    assert r.status_code == 404


async def test_delete_candidate_hard_deletes_with_related_rows(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.candidate import Candidate
    from app.models.contract import Contract
    from app.models.note import Note

    candidate_id = await _seed_candidate()
    await _seed_note(candidate_id)
    await _seed_contract(candidate_id)

    # Preconditions: the candidate exists and has the related rows.
    assert await _count(Candidate, id=candidate_id) == 1
    assert await _count(Note, candidate_id=candidate_id) == 1
    assert await _count(Contract, candidate_id=candidate_id) == 1

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 204, r.text

    # Candidate and ALL related rows are gone (DB cascade + ORM cascade).
    assert await _count(Candidate, id=candidate_id) == 0
    assert await _count(Note, candidate_id=candidate_id) == 0
    assert await _count(Contract, candidate_id=candidate_id) == 0

    # GET now 404s.
    r2 = await app_client.get(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r2.status_code == 404

    # A second delete is also a 404 (nothing left).
    r3 = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r3.status_code == 404


async def test_delete_candidate_forbidden_for_recruiter(app_client: AsyncClient):
    """A recruiter (below delivery_lead) may not delete candidates."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"pytest-recruiter-{unique}@example.com"
    password = f"T3st_{unique}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Pytest Recruiter",
                role=UserRole.recruiter,
                is_active=True,
            )
        )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    candidate_id = await _seed_candidate()
    r = await app_client.delete(f"/api/candidates/{candidate_id}", headers=headers)
    assert r.status_code == 403

    # Candidate survives the forbidden attempt.
    from app.models.candidate import Candidate

    assert await _count(Candidate, id=candidate_id) == 1
