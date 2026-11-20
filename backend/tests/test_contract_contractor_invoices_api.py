"""Zakładka „Faktury” kontraktu na fakturach konsultanta z KSeF (19.11.2026).

``GET /api/contracts/{id}/contractor-invoices`` czyta ``client_contractor_invoices``
ze wszystkich miesięcy kontraktu. Dostęp jak w Rozliczeniach: „Moduł Finanse”,
bez Delivery Leada i Back office; wyłączony moduł rozliczeń = 404.
Baza testowa jest wspólna: każdy test zakłada własnego klienta i kontrakt.
NIP-y, numery i kwoty fikcyjne.
"""

from __future__ import annotations

import random
import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client_settlement import ClientContractorInvoice
from app.models.user import User, UserRole
from app.services.client_settlements import settings as module_settings
from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract

pytestmark = pytest.mark.asyncio


def _nip() -> str:
    return "997" + "".join(random.choice("0123456789") for _ in range(7))


async def _headers_for(app_client: AsyncClient, role: UserRole) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"ksef-tab-{role.value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Faktury {role.value} {suffix}",
                role=role,
                roles=[role.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _invoice(
    contract_id: int | None,
    *,
    month: str | None,
    issued: date,
    net: str,
    nip_state: str = "known",
    invoice_type: str = "Vat",
) -> int:
    gross = (Decimal(net) * Decimal("1.23")).quantize(Decimal("0.01"))
    nip = _nip()
    async with AsyncSessionLocal() as db:
        row = ClientContractorInvoice(
            ksef_number=f"{nip}-{issued:%Y%m%d}-{uuid.uuid4().hex[:12].upper()}-AB",
            seller_nip=nip,
            seller_name="Jednoosobowa działalność testowa",
            buyer_nip="9990000001",
            invoice_number=f"FV {uuid.uuid4().hex[:4]}/{issued:%m/%Y}",
            invoice_type=invoice_type,
            issue_date=issued,
            currency="PLN",
            net_amount=Decimal(net),
            vat_amount=gross - Decimal(net),
            gross_amount=gross,
            contract_id=contract_id,
            period_month=month,
            nip_state=nip_state,
        )
        db.add(row)
        await db.commit()
        return row.id


@pytest.fixture
def settlements_on(monkeypatch):
    """Przełącznik modułu jest globalny (``app_settings``) — test go nie zapisuje."""

    async def _enabled(_db) -> bool:
        return True

    monkeypatch.setattr(module_settings, "is_enabled", _enabled)


async def test_finanse_widza_faktury_ksef_kontraktu_ze_wszystkich_miesiecy(
    app_client: AsyncClient, settlements_on
) -> None:
    client_id = await _client()
    contract_id = await _contract(client_id, await _candidate())
    other_contract = await _contract(client_id, await _candidate())
    september = await _invoice(
        contract_id, month="2026-09", issued=date(2026, 10, 2), net="18000.00"
    )
    october = await _invoice(
        contract_id, month="2026-10", issued=date(2026, 11, 3), net="19500.00"
    )
    correction = await _invoice(
        contract_id,
        month="2026-10",
        issued=date(2026, 11, 17),
        net="-1500.00",
        invoice_type="Kor",
    )
    suggested = await _invoice(
        contract_id,
        month="2026-08",
        issued=date(2026, 9, 2),
        net="17000.00",
        nip_state="suggested",
    )
    await _invoice(
        contract_id,
        month="2026-10",
        issued=date(2026, 11, 4),
        net="1.00",
        nip_state="rejected",
    )
    await _invoice(
        other_contract, month="2026-10", issued=date(2026, 11, 3), net="2.00"
    )

    resp = await app_client.get(
        f"/api/contracts/{contract_id}/contractor-invoices",
        headers=await _headers_for(app_client, UserRole.finance),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_id"] == contract_id
    assert body["client_id"] == client_id
    rows = body["invoices"]
    # Najnowszy miesiąc pierwszy, w miesiącu najnowsza faktura; odrzucona
    # podpowiedź NIP-u i faktura innego kontraktu nie wracają.
    assert [r["id"] for r in rows] == [correction, october, september, suggested]
    assert [r["period_month"] for r in rows] == [
        "2026-10",
        "2026-10",
        "2026-09",
        "2026-08",
    ]
    first = rows[0]
    assert first["is_correction"] is True
    assert first["invoice_type"] == "Kor"
    assert first["net_amount"] == "-1500.00"
    assert first["gross_amount"] == "-1845.00"
    assert first["currency"] == "PLN"
    assert first["issue_date"] == "2026-11-17"
    assert first["ksef_number"]
    assert rows[1]["is_correction"] is False
    assert rows[3]["nip_state"] == "suggested"
    # Termin płatności zależy od reguł miesiąca — zostaje na karcie osoby.
    assert "due_date" not in first


async def test_kontrakt_bez_faktur_daje_pusta_liste(
    app_client: AsyncClient, settlements_on
) -> None:
    contract_id = await _contract(await _client(), await _candidate())

    resp = await app_client.get(
        f"/api/contracts/{contract_id}/contractor-invoices",
        headers=await _headers_for(app_client, UserRole.finance),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["invoices"] == []


@pytest.mark.parametrize("role", [UserRole.delivery_lead, UserRole.back_office])
async def test_bez_modulu_finanse_odmowa(
    app_client: AsyncClient, settlements_on, role: UserRole
) -> None:
    contract_id = await _contract(await _client(), await _candidate())
    await _invoice(contract_id, month="2026-10", issued=date(2026, 11, 3), net="10.00")

    resp = await app_client.get(
        f"/api/contracts/{contract_id}/contractor-invoices",
        headers=await _headers_for(app_client, role),
    )

    assert resp.status_code == 403, resp.text
    assert "invoices" not in resp.json()


async def test_wylaczony_modul_rozliczen_zamyka_zakladke_poza_adminem(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    async def _disabled(_db) -> bool:
        return False

    monkeypatch.setattr(module_settings, "is_enabled", _disabled)
    contract_id = await _contract(await _client(), await _candidate())
    url = f"/api/contracts/{contract_id}/contractor-invoices"

    closed = await app_client.get(
        url, headers=await _headers_for(app_client, UserRole.finance)
    )
    assert closed.status_code == 404, closed.text
    assert closed.json()["detail"] == module_settings.MODULE_DISABLED_DETAIL

    admin = await app_client.get(url, headers=app_auth_headers)
    assert admin.status_code == 200, admin.text


async def test_nieznany_kontrakt(app_client: AsyncClient, settlements_on) -> None:
    resp = await app_client.get(
        "/api/contracts/2147483000/contractor-invoices",
        headers=await _headers_for(app_client, UserRole.finance),
    )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Nie znaleziono kontraktu."
