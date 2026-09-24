"""Audyt modułu Klienci 24.09.2026 (blok E) — analityka, profil, reguła „obecny".

Testy bazodanowe idą przez in-process ``app_client`` i własne dane; testy
czystych funkcji nie dotykają bazy.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus
from app.services.contractor_identity import (
    current_contracts,
    representative_start,
)
from app.services.order_revenue import MdLineValueInput, md_group_contract_value


# ── czyste funkcje ──────────────────────────────────────────────────────────


def _line(id_, *, status="active", md=None, rate=None, pred=None, used="0"):
    return MdLineValueInput(
        id=id_,
        status=status,
        md_total=Decimal(md) if md is not None else None,
        md_optional_total=None,
        md_rate_revenue=Decimal(rate) if rate is not None else None,
        predecessor_order_id=pred,
        md_used=Decimal(used),
    )


def test_md_group_value_sums_positions_times_rate() -> None:
    lines = [_line(1, md="10", rate="1000"), _line(2, md="5", rate="800")]
    assert md_group_contract_value(lines, swapped_or_taken_over_ids=set()) == Decimal(
        "14000"
    )


def test_md_group_value_counts_swapped_predecessor_only_by_usage() -> None:
    # Zamiana: poprzednik zużył 4 MD, następca przejął pozostałość (6 MD).
    lines = [
        _line(1, status="completed", md="10", rate="1000", used="4"),
        _line(2, md="6", rate="1000", pred=1),
    ]
    assert md_group_contract_value(lines, swapped_or_taken_over_ids={1}) == Decimal(
        "10000"
    )


def test_md_group_value_skips_cancelled_and_scheduled_successor() -> None:
    lines = [
        _line(1, md="10", rate="100"),
        _line(2, status="draft", md="10", rate="100", pred=1),
        _line(3, status="cancelled", md="99", rate="100"),
    ]
    # Poprzednik zaplanowanego następcy jeszcze pracuje: wnosi cały budżet.
    assert md_group_contract_value(lines, swapped_or_taken_over_ids=set()) == Decimal(
        "1000"
    )


def test_representative_start_mirrors_representative_order() -> None:
    today = business_today()
    week = today + timedelta(days=7)
    assert representative_start([week], today) == week
    assert representative_start([today - timedelta(days=3), week], today) == (
        today - timedelta(days=3)
    )
    assert representative_start([None, week], today) is None
    assert representative_start([], today) is None


def test_current_contracts_uses_fallback_start_for_undated_contract() -> None:
    today = business_today()
    undated = SimpleNamespace(id=1, start_date=None)
    assert current_contracts([undated], today) == [undated]
    assert (
        current_contracts(
            [undated],
            today,
            fallback_start_by_contract={1: today + timedelta(days=7)},
        )
        == []
    )


# ── dane ────────────────────────────────────────────────────────────────────


async def _client() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Audyt E {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        return client.id


async def _candidate() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(name=f"Audyt{suffix}", lastname=f"Klient{suffix}")
        db.add(cand)
        await db.commit()
        return cand.id


async def _contract(client_id: int, candidate_id: int | None, **kw) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            client_id=client_id,
            candidate_id=candidate_id,
            status=kw.pop("status", ContractStatus.active),
            start_date=kw.pop("start_date", business_today() - timedelta(days=60)),
            rate_client=kw.pop("rate_client", 15000),
            rate_candidate=kw.pop("rate_candidate", 12000),
            **kw,
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def _cleanup(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
        )
        await db.execute(
            ClientOrderGroup.__table__.delete().where(
                ClientOrderGroup.client_id == client_id
            )
        )
        await db.execute(
            ClientFrameworkContract.__table__.delete().where(
                ClientFrameworkContract.client_id == client_id
            )
        )
        await db.execute(
            Contract.__table__.delete().where(Contract.client_id == client_id)
        )
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.commit()


# ── W1: wartość i liczba zamówień w Analityce ──────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_counts_group_orders_once_and_values_them(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id = await _client()
    today = business_today()
    try:
        contract_ids = [
            await _contract(client_id, await _candidate()) for _ in range(3)
        ]
        async with AsyncSessionLocal() as db:
            cost = ClientOrderGroup(
                client_id=client_id,
                order_number=f"KOSZT-{client_id}",
                start_date=today - timedelta(days=10),
                status="active",
                order_type="cost",
                is_cost_based=True,
                is_md_budget_based=False,
                budget_amount=Decimal("100000"),
                budget_remaining=Decimal("100000"),
            )
            md = ClientOrderGroup(
                client_id=client_id,
                order_number=f"MD-{client_id}",
                start_date=today - timedelta(days=10),
                status="active",
                order_type="md",
                is_cost_based=False,
                is_md_budget_based=False,
            )
            draft = ClientOrderGroup(
                client_id=client_id,
                order_number=f"SZKIC-{client_id}",
                start_date=today,
                status="draft",
                order_type="cost",
                is_cost_based=True,
                is_md_budget_based=False,
                budget_amount=Decimal("999999"),
                budget_remaining=Decimal("999999"),
            )
            db.add_all([cost, md, draft])
            await db.flush()
            for contract_id in contract_ids[:2]:
                db.add(
                    ClientOrder(
                        client_id=client_id,
                        contract_id=contract_id,
                        order_group_id=md.id,
                        title="linia MD",
                        status=ClientOrderStatus.active,
                        start_date=today - timedelta(days=10),
                        md_total=Decimal("10"),
                        md_remaining=Decimal("10"),
                        md_input_mode="md",
                        md_input_value=Decimal("10"),
                        md_rate_revenue=Decimal("1000"),
                    )
                )
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_ids[2],
                    order_group_id=cost.id,
                    title="linia kosztowa",
                    status=ClientOrderStatus.active,
                    start_date=today - timedelta(days=10),
                )
            )
            # Szkic samodzielnego zamówienia — nie jest zamówieniem aktywnym
            # ani nie wnosi wartości.
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_ids[2],
                    title="szkic",
                    status=ClientOrderStatus.draft,
                    start_date=today,
                    total_value=Decimal("555555"),
                    currency="PLN",
                )
            )
            await db.commit()

        resp = await app_client.get(
            f"/api/my-clients/{client_id}/dashboard", headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Dwa zamówienia (kosztowe + MD), nie trzy osoby na liniach.
        assert body["active_orders_count"] == 2
        # 100 000 (kosztowe) + 2 × 10 MD × 1000 zł (MD); bez szkiców.
        assert Decimal(str(body["total_revenue_all_time"])) == Decimal("120000")
        assert Decimal(str(body["active_revenue"])) == Decimal("120000")
    finally:
        await _cleanup(client_id)


# ── S5: jedna reguła „obecny" na wszystkich powierzchniach ─────────────────


@pytest.mark.asyncio
async def test_undated_contract_with_future_order_is_planned_everywhere(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.api.client_directory import _active_consultants_subquery

    client_id = await _client()
    today = business_today()
    try:
        contract_id = await _contract(client_id, await _candidate(), start_date=None)
        async with AsyncSessionLocal() as db:
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_id,
                    title="start za tydzień",
                    status=ClientOrderStatus.active,
                    start_date=today + timedelta(days=7),
                )
            )
            await db.commit()

        profile = (
            await app_client.get(
                f"/api/clients/{client_id}/profile", headers=app_auth_headers
            )
        ).json()
        assert [r["contract_id"] for r in profile["planned_consultants"]] == [
            contract_id
        ]
        assert profile["summary"]["active_contracts"] == 0

        dashboard = await app_client.get(
            f"/api/my-clients/{client_id}/dashboard", headers=app_auth_headers
        )
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["active_contracts"] == 0

        subquery = _active_consultants_subquery(today)
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(subquery.c.active_contracts).where(
                        subquery.c.client_id == client_id
                    )
                )
            ).first()
        assert row is None
    finally:
        await _cleanup(client_id)


# ── S6/S7: kontrakt bez kandydata i licznik archiwum ───────────────────────


@pytest.mark.asyncio
async def test_profile_keeps_erased_candidate_contract_as_row(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id = await _client()
    try:
        contract_id = await _contract(client_id, None)
        await _contract(client_id, None, status=ContractStatus.ended)
        resp = await app_client.get(
            f"/api/clients/{client_id}/profile", headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        row = next(
            r for r in body["active_consultants"] if r["contract_id"] == contract_id
        )
        assert row["candidate"]["id"] is None
        assert row["candidate"]["name"] == "Konsultant usunięty (RODO)"
        # „Aktywne MRR” = suma kolumny „Marża” pod nim.
        assert body["summary"]["active_mrr"] == sum(
            r["monthly_margin"] for r in body["active_consultants"]
        )
        assert body["historical"]["placements_total"] == 1
        assert len(body["historical"]["placements"]) == 1
    finally:
        await _cleanup(client_id)


# ── N12: umowy ramowe kończące się w ciągu 30 dni ───────────────────────────


@pytest.mark.asyncio
async def test_expiring_soon_counts_only_window_not_expired(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id = await _client()
    today = business_today()
    try:
        async with AsyncSessionLocal() as db:
            for offset in (-5, 10, 90):
                db.add(
                    ClientFrameworkContract(
                        client_id=client_id,
                        name=f"Ramowa {offset}",
                        status=FrameworkContractStatus.active,
                        expiry_date=today + timedelta(days=offset),
                    )
                )
            await db.commit()
        resp = await app_client.get("/api/my-clients", headers=app_auth_headers)
        assert resp.status_code == 200, resp.text
        row = next(r for r in resp.json() if r["client_id"] == client_id)
        assert row["expiring_soon_count"] == 1
    finally:
        await _cleanup(client_id)


# ── W3: szkic umowy ramowej z zależnościami ────────────────────────────────


@pytest.mark.asyncio
async def test_deleting_draft_framework_contract_in_use_is_409(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id = await _client()
    try:
        contract_id = await _contract(client_id, await _candidate())
        async with AsyncSessionLocal() as db:
            fc = ClientFrameworkContract(
                client_id=client_id,
                name="Szkic w użyciu",
                status=FrameworkContractStatus.draft,
            )
            db.add(fc)
            await db.flush()
            fc_id = fc.id
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_id,
                    framework_contract_id=fc_id,
                    title="pod szkicem",
                    status=ClientOrderStatus.active,
                    start_date=business_today(),
                )
            )
            await db.commit()
        resp = await app_client.delete(
            f"/api/clients/{client_id}/framework-contracts/{fc_id}",
            headers=app_auth_headers,
        )
        assert resp.status_code == 409, resp.text
        assert "zamówienia: 1" in resp.text
        async with AsyncSessionLocal() as db:
            assert await db.get(ClientFrameworkContract, fc_id) is not None
    finally:
        await _cleanup(client_id)


# ── S1: zapis na usuniętym kliencie ────────────────────────────────────────


@pytest.mark.asyncio
async def test_writes_on_deleted_client_are_404(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from datetime import datetime, timezone

    client_id = await _client()
    try:
        async with AsyncSessionLocal() as db:
            client = await db.get(Client, client_id)
            client.deleted_at = datetime.now(timezone.utc)
            await db.commit()
        base = f"/api/clients/{client_id}"
        attempts = [
            app_client.patch(base, json={"industry": "IT"}, headers=app_auth_headers),
            app_client.post(
                f"{base}/knowledge",
                json={"category": "general", "content": "x"},
                headers=app_auth_headers,
            ),
            app_client.post(
                f"{base}/framework-contracts",
                data={"name": "MSA"},
                headers=app_auth_headers,
            ),
            app_client.put(
                f"{base}/contract-terms",
                json={"payment_net_days": 30},
                headers=app_auth_headers,
            ),
        ]
        for attempt in attempts:
            resp = await attempt
            assert resp.status_code == 404, resp.text
    finally:
        await _cleanup(client_id)


# ── S3 / N10: czytelne 422 zamiast 500 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_null_and_bad_references_are_422(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id = await _client()
    other_id = await _client()
    try:
        resp = await app_client.patch(
            f"/api/clients/{client_id}",
            json={"status": None},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text

        async with AsyncSessionLocal() as db:
            foreign = ClientFrameworkContract(
                client_id=other_id,
                name="Cudza",
                status=FrameworkContractStatus.active,
            )
            db.add(foreign)
            await db.commit()
            foreign_id = foreign.id
        resp = await app_client.post(
            f"/api/clients/{client_id}/framework-contracts",
            data={"name": "Nowa", "parent_contract_id": str(foreign_id)},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        resp = await app_client.post(
            f"/api/clients/{client_id}/framework-contracts",
            data={"name": "x" * 300},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        resp = await app_client.post(
            f"/api/clients/{client_id}/framework-contracts",
            data={"name": "Ok"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        resp = await app_client.patch(
            f"/api/clients/{client_id}/framework-contracts/{resp.json()['id']}",
            json={"name": None},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        resp = await app_client.put(
            f"/api/clients/{client_id}/contract-terms",
            json={"payment_currency": "ZŁOTY"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
    finally:
        await _cleanup(client_id)
        await _cleanup(other_id)


@pytest.mark.asyncio
async def test_merge_into_deleted_client_is_422(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from datetime import datetime, timezone

    source_id = await _client()
    target_id = await _client()
    try:
        async with AsyncSessionLocal() as db:
            target = await db.get(Client, target_id)
            target.deleted_at = datetime.now(timezone.utc)
            await db.commit()
        resp = await app_client.post(
            f"/api/clients/{source_id}/merge-into/{target_id}",
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
    finally:
        await _cleanup(source_id)
        await _cleanup(target_id)
