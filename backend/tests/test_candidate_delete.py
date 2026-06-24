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
from datetime import date, datetime, timezone

from httpx import AsyncClient
from sqlalchemy import func, select, text


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


async def test_every_candidate_fk_has_on_delete_rule():
    """Schema invariant (the real guard for the prod bug): EVERY foreign key
    referencing ``candidates.id`` must declare an ``ON DELETE`` rule (CASCADE or
    SET NULL).

    A FK left at NO ACTION/RESTRICT blocks the hard delete with an
    ``IntegrityError`` → unhandled 500 → Starlette emits it ABOVE the CORS
    middleware → the browser sees only an opaque "Network Error". Migration
    ``0146`` makes the DB authoritative for every candidate FK; this test fails
    if that migration is reverted or a new uncascaded FK is introduced.

    Postgres-specific: ``pg_constraint.confdeltype`` —
    a=NO ACTION, r=RESTRICT, c=CASCADE, n=SET NULL, d=SET DEFAULT.
    """
    from app.core.database import AsyncSessionLocal

    sql = text(
        """
        SELECT rel.relname AS table_name,
               att.attname AS column_name,
               con.confdeltype::text AS on_delete
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_class frel ON frel.oid = con.confrelid
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
        WHERE con.contype = 'f' AND frel.relname = 'candidates'
        ORDER BY 1, 2
        """
    )
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(sql)).all()

    assert rows, "expected at least one FK referencing candidates"
    offenders = [(t, c, d) for (t, c, d) in rows if d not in ("c", "n")]
    assert not offenders, (
        "FK(s) to candidates without ON DELETE CASCADE/SET NULL — these block "
        f"hard delete and surface as a browser 'Network Error': {offenders}"
    )


async def test_delete_candidate_cascades_membership_and_unlinks_calendar(
    app_client: AsyncClient, app_auth_headers: dict
):
    """End-to-end: a candidate with a talent-pool membership (the confirmed
    prod culprit — that table has NO ORM relationship on ``Candidate``, so it
    relies SOLELY on the DB-level ON DELETE rule) plus a calendar event.

    Delete must 204; the membership is gone (CASCADE), the calendar event
    survives but is unlinked (SET NULL).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.calendar_event import CalendarEvent
    from app.models.candidate import Candidate
    from app.models.talent_pool import TalentPool, TalentPoolMembership

    candidate_id = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        pool = TalentPool(name=f"DelPool-{uuid.uuid4().hex[:6]}")
        db.add(pool)
        await db.commit()
        await db.refresh(pool)
        pool_id = pool.id
        db.add(
            TalentPoolMembership(talent_pool_id=pool_id, candidate_id=candidate_id)
        )
        ev = CalendarEvent(
            title="survives the candidate delete",
            start_time=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            candidate_id=candidate_id,
        )
        db.add(ev)
        await db.commit()
        await db.refresh(ev)
        event_id = ev.id

    assert await _count(TalentPoolMembership, candidate_id=candidate_id) == 1

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 204, r.text

    assert await _count(Candidate, id=candidate_id) == 0
    # CASCADE — membership row removed with the candidate.
    assert await _count(TalentPoolMembership, candidate_id=candidate_id) == 0
    # SET NULL — calendar event survives, just unlinked.
    assert await _count(CalendarEvent, id=event_id) == 1
    async with AsyncSessionLocal() as db:
        ev2 = await db.get(CalendarEvent, event_id)
        assert ev2 is not None and ev2.candidate_id is None
        # cleanup
        await db.delete(ev2)
        pool = await db.get(TalentPool, pool_id)
        if pool is not None:
            await db.delete(pool)
        await db.commit()


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
