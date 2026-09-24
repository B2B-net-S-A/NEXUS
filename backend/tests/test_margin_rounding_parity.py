"""UAT M06-B04: ta sama marża klienta na profilu, w Analityce, w Radzie i u admina.

Profil sumuje ZAOKRĄGLONE wiersze tabeli konsultantów (`schemas/money.py`),
a pozostałe agregaty sumowały surowe kwoty i zaokrąglały raz — kontrakty
z groszowymi marżami dawały różnicę o złotówki między ekranami.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.core.scheduling import business_today


@pytest.mark.asyncio
async def test_client_margin_is_the_same_on_every_surface(
    app_client: AsyncClient, app_auth_headers: dict
):
    marker = uuid.uuid4().hex[:8]
    ids: dict[str, list[int]] = {"contracts": [], "candidates": [], "clients": []}
    try:
        async with AsyncSessionLocal() as db:
            client = Client(name=f"Parity Client {marker}")
            candidates = [
                Candidate(name="Parity", lastname=f"One{marker}"),
                Candidate(name="Parity", lastname=f"Two{marker}"),
            ]
            db.add_all([client, *candidates])
            await db.flush()
            # Dwie marże po 0,50 zł: suma zaokrągleń = 2, zaokrąglenie sumy = 1.
            contracts = [
                Contract(
                    candidate_id=candidate.id,
                    client_id=client.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=business_today() - timedelta(days=30),
                    rate_unit=RateUnit.monthly,
                    currency="PLN",
                    rate_client_currency="PLN",
                    rate_candidate_currency="PLN",
                    rate_client=Decimal("100.500"),
                    rate_candidate=Decimal("100.000"),
                )
                for candidate in candidates
            ]
            # Kontrakt z PRZYSZŁYM startem: planowany, nie obecny — nie wchodzi
            # do marży na ŻADNEJ powierzchni (B46 + przegląd adwersarialny
            # PR 2: profil go wyłączał, a Analityka/Rada/admin nadal liczyły).
            planned = Contract(
                candidate_id=candidates[0].id,
                client_id=client.id,
                contract_type=ContractType.b2b,
                status=ContractStatus.active,
                start_date=business_today() + timedelta(days=20),
                rate_unit=RateUnit.monthly,
                currency="PLN",
                rate_client_currency="PLN",
                rate_candidate_currency="PLN",
                rate_client=Decimal("5000.000"),
                rate_candidate=Decimal("1000.000"),
            )
            contracts.append(planned)
            db.add_all(contracts)
            await db.commit()
            ids["contracts"] = [c.id for c in contracts]
            ids["candidates"] = [c.id for c in candidates]
            ids["clients"] = [client.id]

        client_id = ids["clients"][0]
        profile = await app_client.get(
            f"/api/clients/{client_id}/profile", headers=app_auth_headers
        )
        assert profile.status_code == 200, profile.text
        profile_mrr = profile.json()["summary"]["active_mrr"]
        assert profile_mrr == 2

        dashboard = await app_client.get(
            f"/api/my-clients/{client_id}/dashboard", headers=app_auth_headers
        )
        assert dashboard.status_code == 200, dashboard.text
        assert Decimal(str(dashboard.json()["monthly_margin_total"])) == profile_mrr

        await cache_invalidate("insights:clients:")
        ranking = await app_client.get(
            "/api/insights/clients/ranking", headers=app_auth_headers
        )
        assert ranking.status_code == 200, ranking.text
        row = next(r for r in ranking.json()["clients"] if r["client_id"] == client_id)
        assert row["monthly_margin_total"] == profile_mrr

        overview = await app_client.get(
            "/api/admin/clients-overview", headers=app_auth_headers
        )
        assert overview.status_code == 200, overview.text
        admin_row = next(r for r in overview.json() if r["client_id"] == client_id)
        assert admin_row["monthly_margin_total"] == profile_mrr

        # Kafel „Marża / mc" Rady (i tabele rok-do-roku) liczy ta sama funkcja
        # co kokpit — musi zaokrąglać składniki jak ranking na tej zakładce.
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.services.contract_rates import RATE_SCHEDULE_LOADS
        from app.services.insights_board_money import fold_money

        async with AsyncSessionLocal() as db:
            # Kokpit Rady filtruje w SQL `start_date IS NOT NULL AND start_date
            # <= koniec okna` (`insights_board.py`) — ten sam warunek co
            # `is_current_contract`; test odtwarza go, bo woła `fold_money`
            # na surowych wierszach.
            loaded = (
                await db.scalars(
                    select(Contract)
                    .where(
                        Contract.id.in_(ids["contracts"]),
                        Contract.start_date.is_not(None),
                        Contract.start_date <= business_today(),
                    )
                    .options(selectinload(Contract.candidate), *RATE_SCHEDULE_LOADS)
                )
            ).all()
            assert len(loaded) == 2, "planowany kontrakt nie wchodzi do kokpitu"
            fold = fold_money(loaded, business_today(), {"PLN": Decimal("1")})
        assert fold.margin == profile_mrr
        assert fold.revenue == row["monthly_revenue_total"]
    finally:
        from sqlalchemy import delete

        async with AsyncSessionLocal() as db:
            if ids["contracts"]:
                await db.execute(
                    delete(Contract).where(Contract.id.in_(ids["contracts"]))
                )
            if ids["candidates"]:
                await db.execute(
                    delete(Candidate).where(Candidate.id.in_(ids["candidates"]))
                )
            if ids["clients"]:
                await db.execute(delete(Client).where(Client.id.in_(ids["clients"])))
            await db.commit()
