"""Domyślna jednostka stawki dopasowana do klienta.

Reguła produktowa: żaden klient nie rozlicza się miesięcznie, więc nowe i
uzupełniane zamówienia NIE mogą domyślnie startować z ``monthly`` — mają
przyjmować jednostkę najczęstszą u danego klienta (Nordea → godzinowa,
VeloBank → dzienna/MD). Testy sprawdzają SKUTEK: co realnie ląduje na
utworzonym zamówieniu i co zwraca endpoint zasilający formularze.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.models.contract import RateUnit
from app.services.client_default_rate_unit import default_rate_unit_for_client

_TODAY = date.today()


async def _seed_client(*, name: str | None = None) -> tuple[int, int, int]:
    """Klient + kandydat + kontrakt. Zwraca (client_id, contract_id, candidate_id)."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=name or f"RateUnit-{suffix}")
        db.add(client)
        await db.flush()

        candidate = Candidate(
            name="Ada",
            lastname=f"Nowak-{suffix}",
            email=f"ru-{suffix}@example.com",
        )
        db.add(candidate)
        await db.flush()

        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=30),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("140.000"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id, candidate.id


async def _seed_orders(client_id: int, contract_id: int, units: list[RateUnit]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    async with AsyncSessionLocal() as db:
        for i, unit in enumerate(units):
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_id,
                    title=f"PO-{i}",
                    status=ClientOrderStatus.draft,
                    order_type="periodic",
                    rate_unit=unit,
                )
            )
        await db.commit()


async def _resolve(client_id: int) -> RateUnit:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return await default_rate_unit_for_client(db, client_id)


async def _unassigned_dl_headers(app_client: AsyncClient) -> dict[str, str]:
    """Delivery Lead BEZ przypisania do klienta → rola operacyjna bez finansów.

    Taki użytkownik przechodzi bramkę `DeliveryLeadOrAdmin`, ale `can_finance`
    jest False, więc `contract-with-order` bez żadnej kwoty tworzy rekord czysto
    operacyjny (nie wymusza stawek jak na adminie). To ścieżka, którą realnie
    idzie formularz Delivery Leada bez uprawnień finansowych.
    """
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:6]
    email = f"dl-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="DL bez przypisania",
                role=UserRole.delivery_lead,
                is_active=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ── default_rate_unit_for_client ────────────────────────────────────────────


async def test_dominant_hourly_client_defaults_to_hourly() -> None:
    client_id, contract_id, _ = await _seed_client()
    await _seed_orders(
        client_id,
        contract_id,
        [RateUnit.hourly, RateUnit.hourly, RateUnit.hourly, RateUnit.daily],
    )
    assert await _resolve(client_id) == RateUnit.hourly


async def test_dominant_daily_client_defaults_to_daily() -> None:
    client_id, contract_id, _ = await _seed_client()
    await _seed_orders(
        client_id,
        contract_id,
        [RateUnit.daily, RateUnit.daily, RateUnit.daily, RateUnit.hourly],
    )
    assert await _resolve(client_id) == RateUnit.daily


async def test_monthly_never_wins_even_as_majority() -> None:
    """`monthly` jest wykluczone z liczenia, nawet gdy jest większością."""
    client_id, contract_id, _ = await _seed_client()
    await _seed_orders(
        client_id,
        contract_id,
        [RateUnit.monthly, RateUnit.monthly, RateUnit.monthly, RateUnit.hourly],
    )
    assert await _resolve(client_id) == RateUnit.hourly


async def test_client_without_non_monthly_history_never_returns_monthly() -> None:
    """Klient wyłącznie z `monthly` (albo bez zamówień) → fallback, nigdy `monthly`."""
    client_id, contract_id, _ = await _seed_client()
    await _seed_orders(client_id, contract_id, [RateUnit.monthly, RateUnit.monthly])
    assert await _resolve(client_id) != RateUnit.monthly


async def test_tie_breaks_to_daily() -> None:
    client_id, contract_id, _ = await _seed_client()
    await _seed_orders(client_id, contract_id, [RateUnit.daily, RateUnit.hourly])
    assert await _resolve(client_id) == RateUnit.daily


# ── endpoint zasilający formularze ──────────────────────────────────────────


async def test_endpoint_returns_client_default(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id, contract_id, _ = await _seed_client()
    await _seed_orders(client_id, contract_id, [RateUnit.daily, RateUnit.daily])

    resp = await app_client.get(
        f"/api/clients/{client_id}/orders/default-rate-unit",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rate_unit"] == "daily"


# ── create: nowy kontraktor bez jawnej jednostki ────────────────────────────


async def test_operational_order_without_unit_takes_client_default(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Rekord operacyjny (bez stawek/jednostki) dostaje jednostkę klienta,
    a nie serwerowy `monthly`. Ścieżka Delivery Leada bez uprawnień finansowych."""
    client_id, contract_id, candidate_id = await _seed_client()
    await _seed_orders(client_id, contract_id, [RateUnit.hourly, RateUnit.hourly])
    dl_headers = await _unassigned_dl_headers(app_client)

    resp = await app_client.post(
        f"/api/clients/{client_id}/contract-with-order",
        headers=dl_headers,
        json={
            "candidate_id": candidate_id,
            "title": "NOWE-PO-1",
            "contract_start_date": _TODAY.isoformat(),
            # świadomie BEZ rate_unit ani stawek → ścieżka operacyjna
        },
    )
    assert resp.status_code == 201, resp.text
    order_id = resp.json()["order_id"]

    got = await app_client.get(
        f"/api/clients/{client_id}/orders/{order_id}",
        headers=app_auth_headers,
    )
    assert got.status_code == 200, got.text
    assert got.json()["rate_unit"] == "hourly"


async def test_finance_order_without_unit_takes_client_default(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Rola finansowa podaje stawki, ale NIE jednostkę → domyślna jednostka
    klienta (nie `monthly`)."""
    client_id, contract_id, candidate_id = await _seed_client()
    await _seed_orders(client_id, contract_id, [RateUnit.daily, RateUnit.daily])

    resp = await app_client.post(
        f"/api/clients/{client_id}/contract-with-order",
        headers=app_auth_headers,
        json={
            "candidate_id": candidate_id,
            "title": "NOWE-PO-1b",
            "contract_start_date": _TODAY.isoformat(),
            "rate_client": "544.000",
            "rate_candidate": "480.000",
            # BEZ rate_unit → serwer bierze domyślną jednostkę klienta
        },
    )
    assert resp.status_code == 201, resp.text
    order_id = resp.json()["order_id"]

    got = await app_client.get(
        f"/api/clients/{client_id}/orders/{order_id}",
        headers=app_auth_headers,
    )
    assert got.status_code == 200, got.text
    assert got.json()["rate_unit"] == "daily"


async def test_new_contractor_order_respects_explicit_unit(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Jawnie wybrana jednostka (także `monthly`) ma pierwszeństwo nad domyślną."""
    client_id, contract_id, candidate_id = await _seed_client()
    await _seed_orders(client_id, contract_id, [RateUnit.hourly, RateUnit.hourly])

    resp = await app_client.post(
        f"/api/clients/{client_id}/contract-with-order",
        headers=app_auth_headers,
        json={
            "candidate_id": candidate_id,
            "title": "NOWE-PO-2",
            "contract_start_date": _TODAY.isoformat(),
            "rate_client": "160.000",
            "rate_candidate": "120.000",
            "rate_unit": "monthly",
        },
    )
    assert resp.status_code == 201, resp.text
    order_id = resp.json()["order_id"]

    got = await app_client.get(
        f"/api/clients/{client_id}/orders/{order_id}",
        headers=app_auth_headers,
    )
    assert got.status_code == 200, got.text
    assert got.json()["rate_unit"] == "monthly"
