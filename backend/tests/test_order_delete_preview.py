"""Dialog usuwania zamówienia pyta serwer, CO naprawdę zniknie.

Obietnica „pozostałe zamówienia i umowa tej osoby nie zmienią się" była
nieprawdą: `ContractClientRate.source_order_id` ma `ondelete=CASCADE`, więc
razem z zamówieniem znika krok harmonogramu stawki klienta, a
`Contract._resolve_scheduled_rate` przy braku kroku obowiązującego sięga po
NAJBLIŻSZY PRZYSZŁY — miesiące historyczne dostają wtedy inną stawkę.

Zmierzone na produkcji 18.09.2026: 99 zamówień ma własny krok stawki,
31 kontraktów ma więcej niż jeden, 5 z różnymi kwotami (kontrakt 167:
usunięcie zamówienia 351 przecenia marzec–sierpień z 185,00 na 178,00 zł/h).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.contract_client_rate import ContractClientRate

TODAY = date.today()


@pytest_asyncio.fixture
async def two_step_contract():
    """Kontrakt z DWOMA krokami stawki: starszym i nowszym, z dwóch zamówień."""
    pytest.importorskip("asyncpg")
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Preview {marker}")
        candidate = Candidate(name="Anna", lastname=f"Preview{marker}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=TODAY - timedelta(days=200),
            rate_unit=RateUnit.hourly,
            rate_client=Decimal("185"),
            rate_candidate=Decimal("150"),
        )
        db.add(contract)
        await db.flush()

        older = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"OLD-{marker}",
            status=ClientOrderStatus.active,
            start_date=TODAY - timedelta(days=200),
            end_date=TODAY - timedelta(days=100),
            rate_client=Decimal("178"),
        )
        newer = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"NEW-{marker}",
            status=ClientOrderStatus.active,
            start_date=TODAY - timedelta(days=99),
            rate_client=Decimal("185"),
        )
        db.add_all([older, newer])
        await db.flush()
        db.add_all(
            [
                ContractClientRate(
                    contract_id=contract.id,
                    rate=Decimal("178"),
                    effective_from=TODAY - timedelta(days=200),
                    source_order_id=older.id,
                ),
                ContractClientRate(
                    contract_id=contract.id,
                    rate=Decimal("185"),
                    effective_from=TODAY - timedelta(days=99),
                    source_order_id=newer.id,
                ),
            ]
        )
        await db.commit()
        return {
            "client": client.id,
            "contract": contract.id,
            "older_order": older.id,
            "newer_order": newer.id,
        }


async def test_preview_names_the_period_that_gets_repriced(
    app_client: AsyncClient, app_auth_headers: dict, two_step_contract
):
    """Usunięcie NOWSZEGO zamówienia cofa stawkę bieżącego okresu do starszej."""
    ids = two_step_contract
    resp = await app_client.get(
        f"/api/clients/{ids['client']}/orders/{ids['newer_order']}/delete-preview",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["deletes_row"] is True
    assert body["blocked_by"] == []
    assert len(body["rate_changes"]) == 1
    change = body["rate_changes"][0]
    assert change["effective_from"] == (TODAY - timedelta(days=99)).isoformat()
    # Brak następnego kroku = okres otwarty do dziś włącznie.
    assert change["effective_until"] is None
    assert float(change["rate"]) == 185.0
    assert float(change["replacement_rate"]) == 178.0
    assert change["changes_amount"] is True


async def test_preview_marks_the_window_of_a_middle_step(
    app_client: AsyncClient, app_auth_headers: dict, two_step_contract
):
    """Usunięcie STARSZEGO kroku przecenia okres, który już się rozliczył.

    To jest najgorszy wariant: miesiące, za które wystawiono już faktury,
    dostają stawkę, której wtedy nie było.
    """
    ids = two_step_contract
    resp = await app_client.get(
        f"/api/clients/{ids['client']}/orders/{ids['older_order']}/delete-preview",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    change = resp.json()["rate_changes"][0]

    assert change["effective_from"] == (TODAY - timedelta(days=200)).isoformat()
    assert change["effective_until"] == (TODAY - timedelta(days=99)).isoformat()
    assert float(change["rate"]) == 178.0
    # Bez kroku obowiązującego model sięga po NAJBLIŻSZY PRZYSZŁY — 185.
    assert float(change["replacement_rate"]) == 185.0
    assert change["changes_amount"] is True


async def test_preview_writes_nothing(
    app_client: AsyncClient, app_auth_headers: dict, two_step_contract
):
    """Podgląd skutków nie może mieć skutków."""
    ids = two_step_contract
    await app_client.get(
        f"/api/clients/{ids['client']}/orders/{ids['newer_order']}/delete-preview",
        headers=app_auth_headers,
    )
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, ids["newer_order"])
        assert order is not None
        steps = (
            await db.execute(
                ContractClientRate.__table__.select().where(
                    ContractClientRate.contract_id == ids["contract"]
                )
            )
        ).all()
        assert len(steps) == 2


async def test_preview_refuses_an_order_of_another_client(
    app_client: AsyncClient, app_auth_headers: dict, two_step_contract
):
    """Nie zdradzamy, czy id należy do innego klienta."""
    ids = two_step_contract
    resp = await app_client.get(
        f"/api/clients/{ids['client'] + 1}/orders/{ids['newer_order']}/delete-preview",
        headers=app_auth_headers,
    )
    assert resp.status_code in (403, 404)


async def test_preview_flags_a_period_that_loses_all_revenue(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Audyt 22.09 r2 (FIN-02): ostatni krok z zamówień → kontrakt bez przychodu.

    Podgląd nie może obiecywać powrotu do kolumny cache'u (stawki kasowanego
    zamówienia) — po usunięciu tego okresu nie ma żadnej stawki klienta.
    """
    pytest.importorskip("asyncpg")
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Preview solo {marker}")
        candidate = Candidate(name="Ewa", lastname=f"Solo{marker}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=TODAY - timedelta(days=60),
            rate_unit=RateUnit.hourly,
            rate_client=Decimal("190"),
            rate_candidate=Decimal("150"),
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"SOLO-{marker}",
            status=ClientOrderStatus.active,
            start_date=TODAY - timedelta(days=60),
            rate_client=Decimal("190"),
        )
        db.add(order)
        await db.flush()
        db.add(
            ContractClientRate(
                contract_id=contract.id,
                rate=Decimal("190"),
                effective_from=TODAY - timedelta(days=60),
                source_order_id=order.id,
            )
        )
        await db.commit()
        client_id, order_id = client.id, order.id

    resp = await app_client.get(
        f"/api/clients/{client_id}/orders/{order_id}/delete-preview",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    change = resp.json()["rate_changes"][0]
    assert change["removes_revenue"] is True
    assert change["replacement_rate"] is None
    assert change["changes_amount"] is True


async def test_preview_does_not_flag_revenue_loss_when_a_step_survives(
    app_client: AsyncClient, app_auth_headers: dict, two_step_contract
):
    ids = two_step_contract
    resp = await app_client.get(
        f"/api/clients/{ids['client']}/orders/{ids['newer_order']}/delete-preview",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rate_changes"][0]["removes_revenue"] is False


async def test_group_line_context_says_the_row_is_deleted(
    app_client: AsyncClient, app_auth_headers: dict
):
    """FE-N02: kosz linii MD woła ``DELETE …/lines/{id}``, które kasuje linię
    w KAŻDYM statusie — podgląd z ``context=group_line`` nie może mówić
    „zostanie anulowana”."""
    pytest.importorskip("asyncpg")
    from app.models.client_order_group import ClientOrderGroup

    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Preview grp {marker}")
        candidate = Candidate(name="Olga", lastname=f"Grp{marker}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=TODAY - timedelta(days=30),
            rate_unit=RateUnit.hourly,
        )
        group = ClientOrderGroup(
            client_id=client.id,
            order_number=f"G-{marker}",
            start_date=TODAY - timedelta(days=30),
        )
        db.add_all([contract, group])
        await db.flush()
        line = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            order_group_id=group.id,
            title=f"G-{marker}",
            status=ClientOrderStatus.active,
            start_date=TODAY - timedelta(days=30),
        )
        db.add(line)
        await db.commit()
        client_id, line_id = client.id, line.id

    base = f"/api/clients/{client_id}/orders/{line_id}/delete-preview"
    plain = await app_client.get(base, headers=app_auth_headers)
    assert plain.status_code == 200, plain.text
    assert plain.json()["deletes_row"] is False
    as_line = await app_client.get(
        f"{base}?context=group_line", headers=app_auth_headers
    )
    assert as_line.status_code == 200, as_line.text
    assert as_line.json()["deletes_row"] is True
    assert as_line.json()["is_group_line"] is True
