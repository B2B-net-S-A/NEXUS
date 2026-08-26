"""P0.12 — stawki/marże kontraktu tylko dla VIEW_FINANCE (M5 PR-01d).

Lista kontraktów, detal, lista kontraktorów i eksport ujawniały
``rate_candidate``/``rate_client``/``margin`` (+ harmonogramy) każdej roli z
``TacPlus`` — więc role bez VIEW_FINANCE widziały finanse niezgodnie z
kanoniczną polityką NEXUS. Na candidate-bearing kontraktach kwoty widzi Admin;
Finance używa bezosobowych endpointów. Pozostali, w tym Delivery Lead,
zachowują widok operacyjny (rekordy są, kwoty = None), a eksport zawierający
tożsamość kandydata jest Admin-only.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import delete, func, select

_TODAY = date.today()


async def _headers_for(
    app_client: AsyncClient,
    role_value: str,
    *,
    assigned_contract_id: int | None = None,
) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.contract import Contract
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    email = f"fin-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Fin {role_value}",
            role=UserRole(role_value),
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if role_value == "delivery_lead" and assigned_contract_id is not None:
            client_id = await db.scalar(
                select(Contract.client_id).where(Contract.id == assigned_contract_id)
            )
            assert client_id is not None
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id,
                    client_id=client_id,
                )
            )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_candidate_client() -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Fin",
            lastname=f"C-{uuid.uuid4().hex[:6]}",
            email=f"finc-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"FinClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)
        return cand.id, client.id


async def _seed_contract(*, currency: str = "PLN") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Fin",
            lastname=f"C-{uuid.uuid4().hex[:6]}",
            email=f"finc-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"FinClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=10),
            end_date=_TODAY + timedelta(days=90),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            margin=Decimal("50.000"),
            currency=currency,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def test_admin_sees_rates_in_detail(
    app_client: AsyncClient, app_auth_headers: dict
):
    # app_auth_headers = admin (ma VIEW_FINANCE)
    cid = await _seed_contract()
    r = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rate_candidate"] is not None
    assert body["rate_client"] is not None
    assert body["margin"] is not None


async def _seed_today_eur_rate() -> tuple[float, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.fx_rate import FxRate

    today = business_today()
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(FxRate).where(
                FxRate.currency == "EUR", FxRate.effective_date == today
            )
        )
        if row is None:
            row = FxRate(
                currency="EUR",
                effective_date=today,
                rate_to_pln=Decimal("4.280000"),
                source="NBP",
            )
            db.add(row)
        else:
            row.rate_to_pln = Decimal("4.280000")
            row.source = "NBP"
        await db.commit()
        await db.refresh(row)
        return float(row.rate_to_pln), row.effective_date.isoformat()


async def test_admin_eur_detail_exposes_persisted_nbp_rate_and_real_date(
    app_client: AsyncClient, app_auth_headers: dict
):
    expected_rate, expected_date = await _seed_today_eur_rate()
    cid = await _seed_contract(currency="EUR")

    response = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)

    assert response.status_code == 200, response.text
    snapshot = response.json()["eur_pln_rate"]
    assert snapshot == {
        "rate": expected_rate,
        "effective_date": expected_date,
        "source": "NBP",
        "table": "A",
    }


async def test_eur_detail_uses_latest_rate_not_newer_than_weekend(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.api import contracts as contracts_api
    from app.core.database import AsyncSessionLocal
    from app.models.fx_rate import FxRate

    thursday = date(2091, 8, 23)
    friday = date(2091, 8, 24)
    sunday = date(2091, 8, 26)
    future_monday = date(2091, 8, 27)
    seeded = (
        (thursday, Decimal("4.100000")),
        (friday, Decimal("4.200000")),
        (future_monday, Decimal("9.900000")),
    )
    seeded_dates = [effective_date for effective_date, _ in seeded]
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FxRate).where(
                FxRate.currency == "EUR",
                FxRate.effective_date.in_(seeded_dates),
            )
        )
        for effective_date, rate in seeded:
            db.add(
                FxRate(
                    currency="EUR",
                    effective_date=effective_date,
                    rate_to_pln=rate,
                    source="NBP",
                )
            )
        await db.commit()

    try:
        monkeypatch.setattr(contracts_api, "business_today", lambda: sunday)
        cid = await _seed_contract(currency="EUR")

        response = await app_client.get(
            f"/api/contracts/{cid}", headers=app_auth_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["eur_pln_rate"] == {
            "rate": 4.2,
            "effective_date": friday.isoformat(),
            "source": "NBP",
            "table": "A",
        }
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(FxRate).where(
                    FxRate.currency == "EUR",
                    FxRate.effective_date.in_(seeded_dates),
                )
            )
            await db.commit()


async def test_repeated_eur_detail_reads_cached_snapshot_without_http_or_writes(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract
    from app.models.fx_rate import FxRate
    from app.services import fx_service

    _, effective_date_raw = await _seed_today_eur_rate()
    effective_date = date.fromisoformat(effective_date_raw)
    cid = await _seed_contract(currency="EUR")

    async with AsyncSessionLocal() as db:
        before_count = await db.scalar(select(func.count(FxRate.id)))
        contract_before = await db.get(Contract, cid)
        fx_before = await db.scalar(
            select(FxRate).where(
                FxRate.currency == "EUR",
                FxRate.effective_date == effective_date,
            )
        )
        assert contract_before is not None
        assert fx_before is not None
        contract_updated_at = contract_before.updated_at
        fx_updated_at = fx_before.updated_at

    class _UnexpectedHttpClient:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("contract GET must never call NBP")

    monkeypatch.setattr(fx_service.httpx, "AsyncClient", _UnexpectedHttpClient)

    first = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
    second = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["eur_pln_rate"] == second.json()["eur_pln_rate"]

    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count(FxRate.id))) == before_count
        contract_after = await db.get(Contract, cid)
        fx_after = await db.scalar(
            select(FxRate).where(
                FxRate.currency == "EUR",
                FxRate.effective_date == effective_date,
            )
        )
        assert contract_after is not None
        assert fx_after is not None
        assert contract_after.updated_at == contract_updated_at
        assert fx_after.updated_at == fx_updated_at


async def test_pln_detail_has_no_nbp_conversion_and_does_not_resolve_fx(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.services import fx_service

    async def _unexpected(*_args, **_kwargs):
        raise AssertionError("PLN contract must not resolve an EUR rate")

    monkeypatch.setattr(fx_service, "get_rate_snapshot_to_pln", _unexpected)
    cid = await _seed_contract(currency="PLN")

    response = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["eur_pln_rate"] is None


async def test_tac_gets_redacted_detail(app_client: AsyncClient):
    await _seed_today_eur_rate()
    cid = await _seed_contract(currency="EUR")
    headers = await _headers_for(app_client, "tac")
    r = await app_client.get(f"/api/contracts/{cid}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Rekord widoczny operacyjnie…
    assert body["status"] == "active"
    # …ale kwoty wyzerowane.
    assert body["rate_candidate"] is None
    assert body["rate_client"] is None
    assert body["margin"] is None
    assert body["candidate_rate_schedule"] == []
    assert body["currency"] is None
    assert body["rate_unit"] is None
    assert body["billing_hours_per_month"] is None
    assert body["eur_pln_rate"] is None


async def test_delivery_lead_gets_redacted_detail(app_client: AsyncClient):
    cid = await _seed_contract()
    headers = await _headers_for(
        app_client,
        "delivery_lead",
        assigned_contract_id=cid,
    )
    response = await app_client.get(f"/api/contracts/{cid}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rate_candidate"] is None
    assert body["rate_client"] is None
    assert body["margin"] is None
    assert body["currency"] is None
    assert body["rate_unit"] is None
    assert body["billing_hours_per_month"] is None


async def test_delivery_lead_cannot_read_unassigned_client_contract(
    app_client: AsyncClient,
):
    cid = await _seed_contract()
    headers = await _headers_for(app_client, "delivery_lead")

    response = await app_client.get(f"/api/contracts/{cid}", headers=headers)

    assert response.status_code == 403, response.text


async def test_export_requires_finance(app_client: AsyncClient, app_auth_headers: dict):
    tac = await _headers_for(app_client, "tac")
    r_tac = await app_client.get("/api/contracts/export?format=csv", headers=tac)
    assert r_tac.status_code == 403, r_tac.text
    r_admin = await app_client.get(
        "/api/contracts/export?format=csv", headers=app_auth_headers
    )
    assert r_admin.status_code == 200, r_admin.text


async def _find_contractor_row(
    app_client: AsyncClient, headers: dict, contract_id: int
) -> dict | None:
    """Znajdź wiersz kontraktora, przechodząc po WSZYSTKICH stronach.

    Wcześniej test brał jedną stronę (`page_size=100`) i zakładał, że jego
    świeżo zaseedowany kontrakt się w niej zmieści. To wiąże wynik z liczbą
    wierszy w bazie: przy nagromadzonych kontraktach — czyli przy drugim
    przebiegu suite'u na tej samej bazie — wiersz wypadał poza pierwszą stronę
    i test czerwieniał z powodu, który nie ma nic wspólnego z redakcją danych
    finansowych, czyli z tym, co ten test bada.

    Podbicie `page_size` tylko przesunęłoby próg (endpoint i tak tnie na 200).
    Przejście po stronach zdejmuje założenie o rozmiarze tabeli całkowicie.
    """
    page = 1
    seen = 0
    while True:
        r = await app_client.get(
            f"/api/contractors?page={page}&page_size=200", headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        items = body["items"]
        for item in items:
            if item["contract_id"] == contract_id:
                return item
        seen += len(items)
        if not items or seen >= body["total"]:
            return None
        page += 1


async def test_tac_gets_redacted_contractor_list(app_client: AsyncClient):
    cid = await _seed_contract()
    headers = await _headers_for(app_client, "tac")
    row = await _find_contractor_row(app_client, headers, cid)
    assert row is not None, "seeded contractor not in list"
    assert row["rate_candidate"] is None
    assert row["margin"] is None
    assert row["currency"] is None
    assert row["rate_unit"] is None


async def test_tac_cannot_create_contract_with_finance_fields(
    app_client: AsyncClient,
):
    """Redaction is not authorization: hidden rates must never be persisted."""
    cand_id, client_id = await _seed_candidate_client()
    tac = await _headers_for(app_client, "tac")
    body = {
        "candidate_id": cand_id,
        "client_id": client_id,
        "start_date": (_TODAY - timedelta(days=1)).isoformat(),
        "end_date": (_TODAY + timedelta(days=120)).isoformat(),
        "rate_candidate": 111.0,
        "rate_client": 222.0,
        "status": "active",
    }
    r = await app_client.post("/api/contracts", json=body, headers=tac)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "finance_fields_forbidden"


async def test_tac_expiring_list_redacted(app_client: AsyncClient):
    cid = await _seed_contract()  # end_date = today + 90, status active
    tac = await _headers_for(app_client, "tac")
    r = await app_client.get("/api/contracts/expiring?days=90", headers=tac)
    assert r.status_code == 200, r.text
    row = next((i for i in r.json() if i["id"] == cid), None)
    assert row is not None, "seeded contract missing from expiring list"
    assert row["rate_candidate"] is None
    assert row["rate_client"] is None
    assert row["margin"] is None


async def test_admin_expiring_list_shows_rates(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_contract()
    r = await app_client.get(
        "/api/contracts/expiring?days=90", headers=app_auth_headers
    )
    assert r.status_code == 200, r.text
    row = next((i for i in r.json() if i["id"] == cid), None)
    assert row is not None
    assert row["rate_client"] is not None


async def test_tac_cannot_patch_finance_fields(
    app_client: AsyncClient,
    app_auth_headers: dict,
):
    cid = await _seed_contract()
    tac = await _headers_for(app_client, "tac")
    r = await app_client.patch(
        f"/api/contracts/{cid}", json={"rate_client": 321.0}, headers=tac
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "finance_fields_forbidden"

    unchanged = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["rate_client"] == 150.0


async def test_delivery_lead_cannot_patch_finance_fields(
    app_client: AsyncClient,
):
    cid = await _seed_contract()
    delivery_lead = await _headers_for(
        app_client,
        "delivery_lead",
        assigned_contract_id=cid,
    )
    response = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"rate_candidate": 1, "candidate_rate_schedule": []},
        headers=delivery_lead,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "finance_fields_forbidden"
