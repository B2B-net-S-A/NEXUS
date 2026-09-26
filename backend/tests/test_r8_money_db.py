"""Runda 8 audytu (MONEY) — testy na bazie: kwoty i cykl życia kontraktów."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit

pytestmark = pytest.mark.asyncio


async def _seed_dl(*client_ids: int) -> int:
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        dl = User(
            email=f"r8-dl-{suffix}@example.com",
            password_hash=hash_password(f"T3st_{suffix}!P"),
            name=f"R8 DL {suffix}",
            role=UserRole.delivery_lead,
            is_active=True,
            profile_completed=True,
        )
        db.add(dl)
        await db.flush()
        for client_id in client_ids:
            db.add(
                DeliveryLeadClientAssignment(
                    client_id=client_id, delivery_lead_user_id=dl.id
                )
            )
        await db.commit()
        return dl.id


async def test_by_dl_flags_partial_margin_and_keeps_zero_revenue(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """R8-N13-4: wiersz DL z klientem, którego obecny kontrakt nie ma stawki
    klienta, niesie licznik klientów bez wyceny, a DL bez zamówień ma
    przychód 0 — nie „—", który wyglądał jak brak kursu albo redakcja."""
    marker = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        priced = Client(name=f"R8 wyceniony {marker}")
        unpriced = Client(name=f"R8 bez wyceny {marker}")
        person_a = Candidate(name="Wyceniony", lastname=f"R8{marker}")
        person_b = Candidate(name="Bezwyceny", lastname=f"R8{marker}")
        db.add_all([priced, unpriced, person_a, person_b])
        await db.flush()
        db.add_all(
            [
                Contract(
                    candidate_id=person_a.id,
                    client_id=priced.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=30),
                    rate_unit=RateUnit.monthly,
                    rate_client=Decimal("20000"),
                    rate_candidate=Decimal("15000"),
                ),
                Contract(
                    candidate_id=person_b.id,
                    client_id=unpriced.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=30),
                    rate_unit=RateUnit.monthly,
                    rate_client=None,
                    rate_candidate=Decimal("15000"),
                ),
            ]
        )
        await db.commit()
        priced_id, unpriced_id = priced.id, unpriced.id
    dl_id = await _seed_dl(priced_id, unpriced_id)

    resp = await app_client.get(
        "/api/admin/clients-overview/by-dl", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["dl_user_id"] == dl_id)
    assert row["monthly_margin_total"] == 5000
    assert row["monthly_margin_unpriced_clients"] == 1
    # Żadnych zamówień → przychód z zamówień to policzone zero.
    assert row["total_revenue"] is not None
    assert float(row["total_revenue"]) == 0
