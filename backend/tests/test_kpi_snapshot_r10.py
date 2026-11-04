"""Runda 10 (R10-N8-11): snapshot opsowy liczy aktywnych klientów regułą katalogu.

„Aktywny klient” = klient z kontraktem `active`/`ending`, który obowiązuje dziś
(`current_contract_clause` — także kontrakt BEZ daty startu). Umowa
unieważniona (`void`) bez daty końca nie czyni klienta aktywnym.

Baza jest wspólna, więc test mierzy PRZYROST licznika po własnych danych.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


@needs_db
@pytest.mark.asyncio
async def test_active_clients_follow_the_current_contract_rule(app_client):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType
    from app.services.dashboard_metrics import compute_kpi_snapshot

    async with AsyncSessionLocal() as db:
        before = (await compute_kpi_snapshot(db))["clients"]["active"]

    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        voided = Client(name=f"KpiVoid {marker}")
        undated = Client(name=f"KpiUndated {marker}")
        person = Candidate(name="Kpi", lastname=f"Snap-{marker}")
        db.add_all([voided, undated, person])
        await db.flush()
        db.add_all(
            [
                Contract(
                    candidate_id=person.id,
                    client_id=voided.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.void,
                    start_date=business_today() - timedelta(days=1),
                ),
                Contract(
                    candidate_id=person.id,
                    client_id=undated.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=None,
                ),
            ]
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        after = (await compute_kpi_snapshot(db))["clients"]["active"]

    assert after - before == 1
