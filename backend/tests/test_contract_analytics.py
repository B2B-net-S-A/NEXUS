"""Tests for Phase 9 B4 — contract analytics endpoints."""

import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from tests._ranking_anchor import anchor_contract, ranking_anchor

#: Ile wierszy zwracają rankowane endpointy analityki BEZ `?limit=`
#: (`limit: int = Query(20, ge=1, le=100)`). Kotwica musi być liczona na tym
#: samym oknie, o które pyta test — patrz `tests/_ranking_anchor`.
_DEFAULT_RANKED_LIMIT = 20


async def test_margin_by_contractor_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contract-analytics/margin-by-contractor", headers=app_auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for row in data:
        assert {
            "candidate_id",
            "candidate_name",
            "active_contracts",
            "total_monthly_margin",
            "total_monthly_revenue",
            "margin_pct",
        } <= set(row.keys())


async def test_margin_by_client_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/margin-by-client", headers=app_auth_headers
    )
    assert resp.status_code == 200
    for row in resp.json():
        assert "client_id" in row
        assert "total_monthly_margin" in row


async def test_utilization_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/utilization", headers=app_auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {
        "total_candidates",
        "candidates_active",
        "active_contracts",
        "candidates_on_bench",
        "utilization_pct",
        "avg_bench_days",
    } == set(body.keys())
    assert body["total_candidates"] >= body["candidates_active"]
    assert body["active_contracts"] >= body["candidates_active"]


async def test_revenue_forecast_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/revenue-forecast?horizon_months=6",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["horizon_months"] == 6
    assert len(body["months"]) == 6
    for m in body["months"]:
        assert {"month", "month_label", "revenue", "margin", "active_count"} <= set(
            m.keys()
        )


async def test_role_client_mix_sigma_deduplicates_person_across_clients(
    app_client: AsyncClient, app_auth_headers: dict
):
    marker = uuid.uuid4().hex[:10]
    role = f"Role-{marker}"
    contract_ids: list[int] = []
    candidate_ids: list[int] = []
    client_ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            candidates = [
                Candidate(
                    name="Piotr",
                    lastname="Klimczak",
                    competence_category=role,
                ),
                Candidate(
                    name="PIOTR",
                    lastname="Klim-czak",
                    competence_category=role,
                ),
            ]
            clients = [
                Client(name=f"Client A {marker}"),
                Client(name=f"Client B {marker}"),
            ]
            db.add_all([*candidates, *clients])
            await db.flush()
            contracts = [
                Contract(
                    candidate_id=candidate.id,
                    client_id=client.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=date.today() - timedelta(days=10),
                    end_date=date.today() + timedelta(days=30),
                )
                for candidate, client in zip(candidates, clients, strict=True)
            ]
            db.add_all(contracts)
            await db.commit()
            contract_ids = [contract.id for contract in contracts]
            candidate_ids = [candidate.id for candidate in candidates]
            client_ids = [client.id for client in clients]

        response = await app_client.get(
            "/api/contract-analytics/role-client-mix",
            headers=app_auth_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        role_rows = [row for row in body["rows"] if row["role"] == role]
        assert len(role_rows) == 2
        assert {row["active_count"] for row in role_rows} == {1}
        assert body["role_totals"][role] == 1
    finally:
        async with AsyncSessionLocal() as db:
            if contract_ids:
                await db.execute(delete(Contract).where(Contract.id.in_(contract_ids)))
            if candidate_ids:
                await db.execute(
                    delete(Candidate).where(Candidate.id.in_(candidate_ids))
                )
            if client_ids:
                await db.execute(delete(Client).where(Client.id.in_(client_ids)))
            await db.commit()


async def test_ending_contracts_count_as_active_in_analytics(
    app_client: AsyncClient, app_auth_headers: dict
):
    """UAT M08-B02: „Kończący się" to nadal pracujący konsultant.

    Rejestr i prognoza liczą ``active`` + ``ending``; kafle i tabele analityki
    liczyły tylko ``active``, więc jeden ekran pokazywał dwie liczby.
    """
    from decimal import Decimal

    from app.models.contract import RateUnit

    marker = uuid.uuid4().hex[:10]
    role = f"Ending-{marker}"
    ids: dict[str, int] = {}
    try:
        # `margin-by-client` i `margin-by-contractor` są tu wołane BEZ `?limit=`,
        # czyli zwracają okno 20 wierszy posortowane po marży malejąco. Marża tej
        # umowy to 20000 - 15000 = 5000 — dokładnie tyle, ile zasiewa kilkadziesiąt
        # innych testów tą samą parą stawek, więc na zapełnionej bazie o wejście
        # do dwudziestki decydowała kolejność przy remisie. Kotwica podnosi
        # KLIENTA i KONSULTANTA ponad próg odcięcia tego okna; jest czysto
        # złotówkowa i bez `job_id`, więc nie zmienia niczego, o co ten test pyta
        # (patrz `tests/_ranking_anchor`).
        anchor = await ranking_anchor(
            app_client, app_auth_headers, limit=_DEFAULT_RANKED_LIMIT
        )

        async with AsyncSessionLocal() as db:
            candidate = Candidate(
                name="Ending", lastname=f"Contractor{marker}", competence_category=role
            )
            client = Client(name=f"Ending Client {marker}")
            db.add_all([candidate, client])
            await db.flush()
            anchor_row = anchor_contract(
                candidate_id=candidate.id, client_id=client.id, margin=anchor
            )
            db.add(anchor_row)
            await db.commit()
            ids = {"candidate": candidate.id, "client": client.id}

        # Baseline PO kotwicy: dzięki temu asercja niżej dalej mierzy dokładnie
        # jedną rzecz — że dołożenie umowy `ending` podbija licznik o jeden.
        baseline = await app_client.get(
            "/api/contract-analytics/utilization", headers=app_auth_headers
        )
        assert baseline.status_code == 200, baseline.text
        before = baseline.json()["active_contracts"]

        async with AsyncSessionLocal() as db:
            contract = Contract(
                candidate_id=ids["candidate"],
                client_id=ids["client"],
                contract_type=ContractType.b2b,
                status=ContractStatus.ending,
                start_date=date.today() - timedelta(days=100),
                end_date=date.today() + timedelta(days=10),
                rate_unit=RateUnit.monthly,
                rate_client=Decimal("20000"),
                rate_candidate=Decimal("15000"),
            )
            db.add(contract)
            await db.commit()
            ids["contract"] = contract.id

        util = await app_client.get(
            "/api/contract-analytics/utilization", headers=app_auth_headers
        )
        assert util.status_code == 200, util.text
        assert util.json()["active_contracts"] == before + 1

        by_client = await app_client.get(
            "/api/contract-analytics/margin-by-client", headers=app_auth_headers
        )
        assert by_client.status_code == 200, by_client.text
        assert ids["client"] in {row["client_id"] for row in by_client.json()}

        by_contractor = await app_client.get(
            "/api/contract-analytics/margin-by-contractor", headers=app_auth_headers
        )
        assert by_contractor.status_code == 200, by_contractor.text
        assert ids["candidate"] in {row["candidate_id"] for row in by_contractor.json()}

        mix = await app_client.get(
            "/api/contract-analytics/role-client-mix", headers=app_auth_headers
        )
        assert mix.status_code == 200, mix.text
        assert mix.json()["role_totals"].get(role) == 1
    finally:
        async with AsyncSessionLocal() as db:
            if ids.get("candidate"):
                # Po `candidate_id`, nie po `contract`: kotwica to DRUGA umowa tej
                # osoby, a ten test jako jeden z niewielu po sobie sprząta —
                # zostawienie jej dołożyłoby cudzym testom kolejny wysokomarżowy
                # wiersz w tym samym oknie top-N.
                await db.execute(
                    delete(Contract).where(Contract.candidate_id == ids["candidate"])
                )
                await db.execute(
                    delete(Candidate).where(Candidate.id == ids["candidate"])
                )
            if ids.get("client"):
                await db.execute(delete(Client).where(Client.id == ids["client"]))
            await db.commit()


async def test_location_distribution_skips_contracts_not_started_yet(
    app_client: AsyncClient, app_auth_headers: dict
):
    """FIX-12 (audyt 22.09 r2): kontrakt z przyszłym startem to jeszcze nie
    pracujący konsultant — ta sama reguła co reszta modułu (``_started_by``)."""
    marker = uuid.uuid4().hex[:10]
    started_hub = f"Started-{marker}"
    future_hub = f"Future-{marker}"
    ids: dict[str, list[int]] = {"contract": [], "candidate": [], "client": []}
    try:
        async with AsyncSessionLocal() as db:
            started = Candidate(
                name="Started", lastname=f"Hub{marker}", hub_city=started_hub
            )
            future = Candidate(
                name="Future", lastname=f"Hub{marker}", hub_city=future_hub
            )
            client = Client(name=f"Location Client {marker}")
            db.add_all([started, future, client])
            await db.flush()
            contracts = [
                Contract(
                    candidate_id=started.id,
                    client_id=client.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=date.today() - timedelta(days=5),
                ),
                Contract(
                    candidate_id=future.id,
                    client_id=client.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=date.today() + timedelta(days=20),
                ),
            ]
            db.add_all(contracts)
            await db.commit()
            ids = {
                "contract": [c.id for c in contracts],
                "candidate": [started.id, future.id],
                "client": [client.id],
            }

        response = await app_client.get(
            "/api/contract-analytics/location-distribution",
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        hubs = {row["hub_city"] for row in response.json()["hubs"]}
        assert started_hub in hubs
        assert future_hub not in hubs
    finally:
        async with AsyncSessionLocal() as db:
            if ids["contract"]:
                await db.execute(
                    delete(Contract).where(Contract.id.in_(ids["contract"]))
                )
            if ids["candidate"]:
                await db.execute(
                    delete(Candidate).where(Candidate.id.in_(ids["candidate"]))
                )
            if ids["client"]:
                await db.execute(delete(Client).where(Client.id.in_(ids["client"])))
            await db.commit()
