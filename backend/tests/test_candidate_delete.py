"""Tests for `DELETE /api/candidates/{candidate_id}` — BLOCKED endpoint.

M2 audit PR 1 (M2-PRIV-02): operational hard delete is disabled. The ON
DELETE CASCADE sweep (migrations 0141+0146) silently removed contracts,
notes, stages and audit history while storage/Qdrant artifacts stayed
orphaned. Until the PR 2 privacy executor lands, the endpoint answers 409
(„privacy workflow required”) and the candidate + all related rows survive
byte-identical.

Guard order: ``DeliveryLeadPlus`` still runs first, so roles below
admin/delivery_lead get 403 and never reach the 409 block.

The schema invariant test (every candidate FK has an ON DELETE rule) stays —
the future privacy executor relies on the same DB rules.

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures from conftest
(real postgres in CI).
"""

from __future__ import annotations

import uuid
from datetime import date

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


async def test_delete_candidate_blocked_even_for_admin(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Admin gets an explicit 409 — the endpoint must not run a cascade."""
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
    assert r.status_code == 409, r.text
    assert "workflow" in r.json()["detail"].lower()

    # Candidate and ALL related rows SURVIVE — nothing was cascaded.
    assert await _count(Candidate, id=candidate_id) == 1
    assert await _count(Note, candidate_id=candidate_id) == 1
    assert await _count(Contract, candidate_id=candidate_id) == 1

    # GET still works.
    r2 = await app_client.get(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r2.status_code == 200


async def test_delete_blocked_emits_audit_event(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The blocked attempt leaves an immutable audit row without PII."""
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity

    candidate_id = await _seed_candidate()
    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 409

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(Activity)
            .where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
                Activity.action == "sensitive_operation_blocked",
            )
            .order_by(Activity.id.desc())
            .limit(1)
        )
    assert row is not None
    assert row.details.get("operation") == "hard_delete"
    # No PII in the audit payload.
    assert "@" not in str(row.details)


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
