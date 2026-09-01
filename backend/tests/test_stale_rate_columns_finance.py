"""Pieniądze na powierzchniach zarządczych liczone z HARMONOGRAMÓW, nie z kolumn.

``contracts.rate_client`` / ``rate_candidate`` to cache zapisywany wyłącznie
w momencie ZAPISU umowy. Krok stawki progresywnej albo aneks ``rate_change``,
którego data już nadeszła, nie dotyka tych kolumn — nic w tle ich nie
przelicza. Profil klienta przeszedł na resolver z datami obowiązywania
(``test_client_profile.py``), a analityka, ``/my-clients``, admiński przegląd
klientów i moduł zamówień zostały przy kolumnach, więc te same umowy
raportowały dwie różne kwoty.

Drugi wątek tego pliku: filtr statusu przy pieniądzach. ``status != draft``
wpuszczało wszystko dopisane do enuma później — ``void`` (anulowana, ale
z zachowanym oknem dat, więc przechodziła wszystkie predykaty) i
``ready_for_signature`` (dokument jeszcze niepodpisany). Odwrotnie przy
liczeniu głów: sam ``active`` gubił każdego konsultanta w jego ostatnim
miesiącu, bo dzienny cron przestawia wtedy umowę na ``ending``.

Regresja w obie strony jest CICHA: liczba wygląda prawidłowo, tylko opisuje
co innego.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_TODAY = date.today()
_START = _TODAY - timedelta(days=400)
_STEP = _TODAY - timedelta(days=200)

# Okres 1 = to, co trzymają kolumny legacy. Okres 2 = krok, którego data już
# minęła; każda liczba poniżej ma pochodzić WŁAŚNIE z niego.
_P1_CLIENT = Decimal("15000.000")
_P1_CANDIDATE = Decimal("10000.000")
_P2_CLIENT = Decimal("18000.000")
_P2_CANDIDATE = Decimal("12000.000")
_P2_MARGIN = int(_P2_CLIENT - _P2_CANDIDATE)  # 6000


async def _seed_scheduled_contract(status_value: str = "active"):
    """Klient + umowa, której kolumny legacy zostały w okresie 1.

    Zwraca ``(client_id, contract_id, candidate_name)``. Trzeci krok jest
    datowany w przyszłość — nie ma prawa pojawić się w żadnej dzisiejszej
    liczbie, więc chroni też przed „najnowszy krok wygrywa".
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit
    from app.models.contract_candidate_rate import ContractCandidateRate
    from app.models.contract_client_rate import ContractClientRate

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"StaleRates-{suffix}")
        cand = Candidate(
            name="Stawka",
            lastname=f"Zharmonogramu-{suffix}",
            email=f"stale-{suffix}@example.com",
        )
        db.add_all([client, cand])
        await db.commit()
        await db.refresh(client)
        await db.refresh(cand)

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus(status_value),
            start_date=_START,
            end_date=_TODAY + timedelta(days=20),
            rate_candidate=_P1_CANDIDATE,
            rate_client=_P1_CLIENT,
            margin=_P1_CLIENT - _P1_CANDIDATE,
            rate_unit=RateUnit.monthly,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        db.add_all(
            [
                ContractCandidateRate(
                    contract_id=contract.id, rate=_P1_CANDIDATE, effective_from=_START
                ),
                ContractClientRate(
                    contract_id=contract.id, rate=_P1_CLIENT, effective_from=_START
                ),
                ContractCandidateRate(
                    contract_id=contract.id, rate=_P2_CANDIDATE, effective_from=_STEP
                ),
                ContractClientRate(
                    contract_id=contract.id, rate=_P2_CLIENT, effective_from=_STEP
                ),
                ContractCandidateRate(
                    contract_id=contract.id,
                    rate=Decimal("99000.000"),
                    effective_from=_TODAY + timedelta(days=365),
                ),
                ContractClientRate(
                    contract_id=contract.id,
                    rate=Decimal("99000.000"),
                    effective_from=_TODAY + timedelta(days=365),
                ),
            ]
        )
        await db.commit()
        return client.id, contract.id, f"{cand.name} {cand.lastname}"


async def _seed_plain_contract(status_value: str):
    """Umowa BEZ harmonogramu, z oknem dat obejmującym dziś."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"StatusGate-{suffix}")
        cand = Candidate(
            name="Status",
            lastname=f"Bramka-{suffix}",
            email=f"gate-{suffix}@example.com",
        )
        db.add_all([client, cand])
        await db.commit()
        await db.refresh(client)
        await db.refresh(cand)
        db.add(
            Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus(status_value),
                start_date=_TODAY - timedelta(days=60),
                end_date=_TODAY + timedelta(days=200),
                rate_candidate=Decimal("8000.000"),
                rate_client=Decimal("10000.000"),
                rate_unit=RateUnit.monthly,
                currency="PLN",
            )
        )
        await db.commit()
        return client.id


# ── Analytics v1: MRR/marża ─────────────────────────────────────────────────


async def test_client_finance_uses_the_scheduled_rate_not_the_cached_column():
    from app.analytics.metrics import client_finance
    from app.core.database import AsyncSessionLocal

    client_id, _, _ = await _seed_scheduled_contract()
    async with AsyncSessionLocal() as db:
        data, _, flag = await client_finance(db, client_id)

    assert flag == "complete"
    assert Decimal(data["mrr"]) == _P2_CLIENT, "MRR z kolumny legacy = 15000"
    assert Decimal(data["monthly_margin"]) == Decimal(_P2_MARGIN)


async def test_historical_month_is_priced_with_that_month_rate():
    """Punkt trendu MUSI nieść stawkę tamtego miesiąca, nie dzisiejszą.

    Bez tego lipcowa podwyżka retroaktywnie podnosi styczeń i płaski biznes
    wygląda na rosnący — a wykres nie ma jak tego zasygnalizować.
    """
    from app.analytics.metrics import client_finance
    from app.core.database import AsyncSessionLocal

    client_id, _, _ = await _seed_scheduled_contract()
    before_step = _STEP - timedelta(days=30)
    async with AsyncSessionLocal() as db:
        data, _, _ = await client_finance(db, client_id, as_of=before_step)

    assert Decimal(data["mrr"]) == _P1_CLIENT
    assert Decimal(data["monthly_margin"]) == _P1_CLIENT - _P1_CANDIDATE


@pytest.mark.parametrize("status_value", ["void", "ready_for_signature"])
async def test_non_revenue_statuses_contribute_zero(status_value: str):
    """`void` świadomie zachowuje daty, więc negacja `!= draft` go wpuszczała."""
    from app.analytics.metrics import client_finance
    from app.core.database import AsyncSessionLocal

    client_id = await _seed_plain_contract(status_value)
    async with AsyncSessionLocal() as db:
        data, _, _ = await client_finance(db, client_id)

    assert data["active_contracts"] == 0, f"{status_value} nie jest przychodem"
    assert Decimal(data["mrr"]) == 0


@pytest.mark.parametrize("status_value", ["active", "ending", "ended"])
async def test_revenue_statuses_still_count(status_value: str):
    """Lista pozytywna nie może przy okazji wyciąć niczego, co zarabia."""
    from app.analytics.metrics import client_finance
    from app.core.database import AsyncSessionLocal

    client_id = await _seed_plain_contract(status_value)
    async with AsyncSessionLocal() as db:
        data, _, _ = await client_finance(db, client_id)

    assert data["active_contracts"] == 1
    assert Decimal(data["mrr"]) == Decimal("10000")


# ── /api/my-clients/{id}/dashboard ──────────────────────────────────────────


async def test_my_clients_dashboard_counts_ending_and_prices_from_schedule(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Konsultant w ostatnim miesiącu wciąż pracuje — i wciąż ma marżę."""
    client_id, _, _ = await _seed_scheduled_contract("ending")

    resp = await app_client.get(
        f"/api/my-clients/{client_id}/dashboard", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["active_consultants"] == 1, "`ending` znikał z OBU kafli naraz"
    assert body["monthly_margin_total"] == _P2_MARGIN


# ── /api/admin/clients-overview ─────────────────────────────────────────────


async def test_clients_overview_counts_ending_and_prices_from_schedule(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id, _, _ = await _seed_scheduled_contract("ending")

    resp = await app_client.get("/api/admin/clients-overview", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["client_id"] == client_id)

    assert row["active_consultants"] == 1
    assert row["monthly_margin_total"] == _P2_MARGIN


async def test_clients_overview_by_dl_counts_ending_and_prices_from_schedule(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    client_id, _, _ = await _seed_scheduled_contract("ending")
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        dl = User(
            email=f"dl-overview-{suffix}@example.com",
            password_hash=hash_password(f"T3st_{suffix}!P"),
            name=f"DL Overview {suffix}",
            role=UserRole.delivery_lead,
            is_active=True,
            profile_completed=True,
        )
        db.add(dl)
        await db.commit()
        await db.refresh(dl)
        db.add(
            DeliveryLeadClientAssignment(
                client_id=client_id, delivery_lead_user_id=dl.id
            )
        )
        await db.commit()
        dl_id = dl.id

    resp = await app_client.get(
        "/api/admin/clients-overview/by-dl", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["dl_user_id"] == dl_id)

    assert row["active_consultants"] == 1
    assert row["monthly_margin_total"] == _P2_MARGIN


# ── Marża wiersza zamówienia ────────────────────────────────────────────────


async def _seed_order(client_id: int, contract_id: int) -> int:
    """Zamówienie BEZ własnej stawki — marża ma spaść do stawki z umowy."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title="Zamówienie testowe",
            status=ClientOrderStatus.active,
            start_date=_TODAY - timedelta(days=30),
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order.id


async def test_order_margin_uses_the_scheduled_rate(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id, contract_id, _ = await _seed_scheduled_contract()
    order_id = await _seed_order(client_id, contract_id)

    resp = await app_client.get(
        f"/api/clients/{client_id}/orders/{order_id}", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(str(resp.json()["monthly_margin"])) == Decimal(_P2_MARGIN)


async def test_contractor_list_latest_order_margin_uses_the_scheduled_rate(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Druga ścieżka tej samej funkcji — z eager-loadem, więc i z ryzykiem
    `MissingGreenlet`, gdyby harmonogramy nie zostały wczytane."""
    client_id, contract_id, _ = await _seed_scheduled_contract()
    await _seed_order(client_id, contract_id)

    resp = await app_client.get(
        f"/api/clients/{client_id}/orders", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = next(c for c in resp.json()["contractors"] if c["contract_id"] == contract_id)
    assert Decimal(str(row["latest_order_monthly_margin"])) == Decimal(_P2_MARGIN)
    assert Decimal(str(row["orders"][0]["monthly_margin"])) == Decimal(_P2_MARGIN)
