"""Numer nabywcy dopisywany do klienta przy ręcznym przypisaniu faktury. Dane fikcyjne."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from math import ceil
from typing import Optional

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.api import client_sales_invoices as api
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.critical_event import CriticalEvent
from app.services.client_invoicing import matching, sync
from app.services.order_client_identity import normalize_registry_id
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio

FINANCE = "/api/finance/sales-invoices"
NOVEMBER = {"year": 2026, "month": 11}
EVENT = "client.registry_number_added"
EU_VAT = "FI12345678"


@pytest_asyncio.fixture
async def client():
    target = FastAPI()
    target.include_router(api.finance_router, prefix=FINANCE)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


@pytest_asyncio.fixture
async def seed(monkeypatch):
    monkeypatch.setattr(settings, "KSEF_MODE", "simulate")
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", fx.COMPANY_NIP)
    monkeypatch.setattr(settings, "KSEF_SIMULATE_DIR", str(fx.DATA_DIR.parent))
    data = await fx.seed_month()
    await fx.set_module(True)
    async with AsyncSessionLocal() as db:
        await sync.run_once(db, now=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))
    yield data
    await fx.wipe()
    await fx.set_module(None)
    async with AsyncSessionLocal() as db:
        await db.execute(update(Client).where(Client.nip == EU_VAT).values(nip=None))
        await db.commit()


async def _client_with_order(
    nip: Optional[str] = None, merged_into: Optional[int] = None
) -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Nabywca Testowy", nip)
        if merged_into is not None:
            (await db.get(Client, client_id)).merged_into_client_id = merged_into
        order_id = await fx.periodic_order(
            db,
            client_id,
            f"PO-{uuid.uuid4().hex[:6]}",
            rate="100",
            unit=fx.RateUnit.monthly,
        )
        await db.commit()
    return client_id, order_id


async def _sibling_of_unknown(**buyer: Optional[str]) -> int:
    """Druga faktura tego samego nabywcy, czekająca na numer u klienta."""

    async with AsyncSessionLocal() as db:
        source = await db.scalar(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number == fx.KSEF_UNKNOWN
            )
        )
        values = {
            column.name: getattr(source, column.name)
            for column in ClientSalesInvoice.__table__.columns
            if column.name not in {"id", "created_at", "updated_at"}
        }
        values["ksef_number"] = (
            f"{fx.COMPANY_NIP}-20261105-{uuid.uuid4().hex[:12].upper()}-AA"
        )
        values["invoice_number"] = f"FS {uuid.uuid4().hex[:6]}"
        values.update(
            client_id=None,
            match_status="unmatched",
            match_method=None,
            match_reason="unknown_buyer",
            matched_by=None,
            matched_at=None,
        )
        sibling = ClientSalesInvoice(**values)
        for key, value in buyer.items():
            setattr(sibling, key, value)
            setattr(source, key, value)
        db.add(sibling)
        await db.commit()
        return sibling.id


async def _nip(client_id: int) -> Optional[str]:
    async with AsyncSessionLocal() as db:
        return (await db.get(Client, client_id)).nip


async def _events(client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(CriticalEvent).where(
                CriticalEvent.event_type == EVENT, CriticalEvent.client_id == client_id
            )
        )
        return len(list(rows))


async def _assign(
    client, seed, order_id: int, *, save: bool = True, user: str = "finance"
):
    invoice = await fx.invoice(fx.KSEF_UNKNOWN)
    return await client.post(
        f"{FINANCE}/{invoice.id}/assign",
        json={
            "targets": [{"order_id": order_id}],
            **NOVEMBER,
            "save_buyer_number": save,
        },
        headers=fx.headers(seed.users[user]),
    )


async def _options(client, seed, client_id: int) -> dict:
    invoice = await fx.invoice(fx.KSEF_UNKNOWN)
    response = await client.get(
        f"{FINANCE}/{invoice.id}/options",
        params={"client_id": client_id, **NOVEMBER},
        headers=fx.headers(seed.users["finance"]),
    )
    assert response.status_code == 200, response.text
    return response.json()["buyer_number"]


async def test_saved_number_links_the_rest_of_the_buyers_invoices(client, seed):
    client_id, order_id = await _client_with_order()
    sibling_id = await _sibling_of_unknown()

    check = await _options(client, seed, client_id)
    assert check["state"] == "add"
    assert check["number"] == fx.UNKNOWN_NIP
    assert check["kind"] == "nip"
    assert check["other_waiting"] == 1

    response = await _assign(client, seed, order_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["match_method"] == "manual"
    assert body["buyer_number"]["saved"] is True
    assert body["buyer_number"]["retried"] == 1
    assert await _nip(client_id) == fx.UNKNOWN_NIP
    assert await _events(client_id) == 1

    async with AsyncSessionLocal() as db:
        sibling = await db.get(ClientSalesInvoice, sibling_id)
        assert sibling.client_id == client_id
        assert sibling.match_reason != "unknown_buyer"
        # Ręcznego przypisania automat nie ruszył.
        assigned = await db.scalar(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number == fx.KSEF_UNKNOWN
            )
        )
        assert assigned.match_method == "manual"


async def test_rematch_pending_finds_the_buyer_after_the_number_is_saved(client, seed):
    """Faktura z następnego pobrania: numer jest już u klienta, wiąże ją zwykły przebieg."""

    client_id, order_id = await _client_with_order()
    assert (await _assign(client, seed, order_id)).status_code == 200
    sibling_id = await _sibling_of_unknown()

    async with AsyncSessionLocal() as db:
        await matching.rematch_pending(db)
        await db.commit()
    async with AsyncSessionLocal() as db:
        sibling = await db.get(ClientSalesInvoice, sibling_id)
        assert sibling.client_id == client_id


def _other_buyer(index: int) -> str:
    """Fikcyjny NIP nabywcy bez klienta; suma kontrolna celowo się nie zgadza."""

    return f"77777777{index}3"


async def _waiting_in_queue() -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(ClientSalesInvoice)
                .where(
                    ClientSalesInvoice.match_status == "unmatched",
                    ClientSalesInvoice.match_reason.in_(sorted(matching.RETRY_REASONS)),
                )
            )
        )


async def test_rematch_reaches_the_oldest_invoices_when_the_queue_exceeds_the_limit(
    seed,
):
    """Ponad ``limit`` czekających: najstarsze też dostają kolejną próbę."""

    client_id = await _client_without_orders()
    oldest = [
        await _sibling_of_unknown(issue_date=date(2026, 8, day)) for day in (3, 4)
    ]
    for index in range(7):
        await _sibling_of_unknown(
            buyer_nip=_other_buyer(index), issue_date=date(2026, 11, 5)
        )
    # Numer wpisany ręcznie w profilu, bez okna „Przypisz i dopisz NIP”.
    async with AsyncSessionLocal() as db:
        (await db.get(Client, client_id)).nip = fx.UNKNOWN_NIP
        await db.commit()

    limit = 3
    queue = await _waiting_in_queue()
    assert queue > limit
    for _ in range(ceil(queue / limit)):
        async with AsyncSessionLocal() as db:
            result = await matching.rematch_pending(db, limit=limit)
            await db.commit()
        # Budżet przebiegu: billing_rows liczy się na każdą fakturę.
        assert result["retried"] == limit

    async with AsyncSessionLocal() as db:
        for invoice_id in oldest:
            invoice = await db.get(ClientSalesInvoice, invoice_id)
            assert (invoice.client_id, invoice.match_reason) == (client_id, "no_orders")


async def test_rematch_failure_does_not_stop_the_rotation(seed, monkeypatch):
    """Faktura, na której przebieg pada, nie blokuje następnych w kolejce."""

    for index in range(5):
        await _sibling_of_unknown(buyer_nip=_other_buyer(index))

    limit = 2
    tried: list[int] = []

    async def fail(db, invoice, *, registry=None):
        tried.append(invoice.id)
        raise RuntimeError("awaria przebiegu")

    with monkeypatch.context() as patch:
        patch.setattr(matching, "auto_match", fail)
        async with AsyncSessionLocal() as db:
            with pytest.raises(RuntimeError):
                await matching.rematch_pending(db, limit=limit)
            await db.rollback()
    assert len(tried) == 1

    original = matching.auto_match

    async def record(db, invoice, *, registry=None):
        tried.append(invoice.id)
        return await original(db, invoice, registry=registry)

    monkeypatch.setattr(matching, "auto_match", record)
    async with AsyncSessionLocal() as db:
        await matching.rematch_pending(db, limit=limit)
        await db.commit()

    assert len(tried) == 1 + limit
    assert tried[0] not in tried[1:]


async def test_assign_without_the_flag_leaves_the_client_alone(client, seed):
    client_id, order_id = await _client_with_order()
    sibling_id = await _sibling_of_unknown()

    response = await _assign(client, seed, order_id, save=False)

    assert response.status_code == 200, response.text
    assert "buyer_number" not in response.json()
    assert await _nip(client_id) is None
    assert await _events(client_id) == 0
    async with AsyncSessionLocal() as db:
        sibling = await db.get(ClientSalesInvoice, sibling_id)
        assert sibling.match_reason == "unknown_buyer"


async def test_eu_vat_goes_to_the_client_like_nip(client, seed):
    client_id, order_id = await _client_with_order()
    sibling_id = await _sibling_of_unknown(buyer_nip=None, buyer_foreign_id=EU_VAT)

    check = await _options(client, seed, client_id)
    assert (check["state"], check["kind"]) == ("add", "vat_ue")

    response = await _assign(client, seed, order_id)

    assert response.status_code == 200, response.text
    assert await _nip(client_id) == EU_VAT
    async with AsyncSessionLocal() as db:
        sibling = await db.get(ClientSalesInvoice, sibling_id)
        assert sibling.client_id == client_id


@pytest.mark.parametrize(
    ("raw", "stored"),
    [("FR1A123456789", "FR1"), ("IE9S99999L", "IE9")],
)
async def test_vat_cut_short_by_a_letter_is_not_a_number_of_one_company(
    client, seed, raw, stored
):
    """Różne firmy dają ten sam klucz po normalizacji, więc nie wolno go zapisać."""

    assert normalize_registry_id(raw) == stored
    client_id, order_id = await _client_with_order()
    sibling_id = await _sibling_of_unknown(buyer_nip=None, buyer_foreign_id=stored)

    assert (await _options(client, seed, client_id))["state"] == "none"
    response = await _assign(client, seed, order_id)

    assert response.status_code == 200, response.text
    assert response.json()["buyer_number"]["saved"] is False
    assert await _nip(client_id) is None
    async with AsyncSessionLocal() as db:
        sibling = await db.get(ClientSalesInvoice, sibling_id)
        assert sibling.client_id is None
        assert sibling.match_reason == "unknown_buyer"


async def test_vat_cut_short_in_a_client_profile_binds_no_invoice(client, seed):
    """Ten sam klucz wpisany ręcznie w profilu też nie wiąże cudzych faktur."""

    await _client_with_order(nip="FR1A123456789")
    sibling_id = await _sibling_of_unknown(buyer_nip=None, buyer_foreign_id="FR1")

    async with AsyncSessionLocal() as db:
        await matching.rematch_pending(db)
        await db.commit()
    async with AsyncSessionLocal() as db:
        sibling = await db.get(ClientSalesInvoice, sibling_id)
        assert sibling.client_id is None
        assert sibling.match_reason == "unknown_buyer"


async def test_other_number_is_not_overwritten(client, seed):
    client_id, order_id = await _client_with_order(nip=fx.OTHER_CLIENT_NIP)
    sibling_id = await _sibling_of_unknown()

    check = await _options(client, seed, client_id)
    assert check["state"] == "differs"
    assert check["existing"] == fx.OTHER_CLIENT_NIP

    # Faktura i tak się przypisuje; odmowa dotyczy tylko numeru.
    response = await _assign(client, seed, order_id)

    assert response.status_code == 200, response.text
    assert response.json()["match_method"] == "manual"
    assert response.json()["buyer_number"]["saved"] is False
    assert await _nip(client_id) == fx.OTHER_CLIENT_NIP
    assert await _events(client_id) == 0
    async with AsyncSessionLocal() as db:
        sibling = await db.get(ClientSalesInvoice, sibling_id)
        assert sibling.match_reason == "unknown_buyer"


async def test_text_in_the_number_field_counts_as_a_number(client, seed):
    client_id, order_id = await _client_with_order(nip="do uzupełnienia")

    assert (await _options(client, seed, client_id))["state"] == "differs"
    await _assign(client, seed, order_id)

    assert await _nip(client_id) == "do uzupełnienia"


async def test_number_of_another_client_is_not_duplicated(client, seed):
    owner_id, _order = await _client_with_order(nip=fx.UNKNOWN_NIP)
    client_id, order_id = await _client_with_order()

    check = await _options(client, seed, client_id)
    assert check["state"] == "taken"
    assert check["owner_name"].startswith("Nabywca Testowy")

    response = await _assign(client, seed, order_id)

    assert response.status_code == 200, response.text
    assert response.json()["buyer_number"]["saved"] is False
    assert await _nip(client_id) is None
    assert await _nip(owner_id) == fx.UNKNOWN_NIP


async def test_number_shared_by_two_clients_stays_with_them(client, seed):
    await _client_with_order(nip=fx.UNKNOWN_NIP)
    await _client_with_order(nip=fx.UNKNOWN_NIP)
    client_id, order_id = await _client_with_order()

    check = await _options(client, seed, client_id)
    assert check["state"] == "taken"
    assert check["owner_name"] is None

    await _assign(client, seed, order_id)

    assert await _nip(client_id) is None


async def test_number_goes_to_the_canonical_client_not_the_duplicate(client, seed):
    canonical_id, _order = await _client_with_order()
    duplicate_id, order_id = await _client_with_order(merged_into=canonical_id)

    response = await _assign(client, seed, order_id)

    assert response.status_code == 200, response.text
    assert await _nip(canonical_id) == fx.UNKNOWN_NIP
    assert await _nip(duplicate_id) is None


async def test_number_on_the_merged_duplicate_counts_as_the_clients(client, seed):
    canonical_id, order_id = await _client_with_order()
    await _client_with_order(nip=fx.OTHER_CLIENT_NIP, merged_into=canonical_id)

    assert (await _options(client, seed, canonical_id))["state"] == "differs"
    await _assign(client, seed, order_id)

    assert await _nip(canonical_id) is None


@pytest.mark.parametrize("role", ["recruiter", "dl"])
async def test_only_who_can_assign_can_save_the_number(client, seed, role):
    client_id, order_id = await _client_with_order()

    response = await _assign(client, seed, order_id, user=role)

    assert response.status_code == 403
    assert await _nip(client_id) is None


# ── Numer bez przypisania (klient bez zamówień w tym miesiącu) ───────────────


async def _client_without_orders(nip: Optional[str] = None) -> int:
    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Nabywca Bez Zamówień", nip)
        await db.commit()
    return client_id


async def _number_only(client, seed, client_id: int, *, user: str = "finance"):
    invoice = await fx.invoice(fx.KSEF_UNKNOWN)
    return await client.post(
        f"{FINANCE}/{invoice.id}/buyer-number",
        json={"client_id": client_id},
        headers=fx.headers(seed.users[user]),
    )


async def test_number_without_assigning_moves_the_buyers_invoices_to_the_client(
    client, seed
):
    client_id = await _client_without_orders()
    sibling_id = await _sibling_of_unknown()

    response = await _number_only(client, seed, client_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["buyer_number"]["saved"] is True
    assert body["buyer_number"]["retried"] == 2
    # Bez zamówień: faktura zostaje do przypisania, ale już u klienta.
    assert body["match_status"] == "unmatched"
    assert body["match_reason"] == "no_orders"
    assert body["client_id"] == client_id
    assert await _nip(client_id) == fx.UNKNOWN_NIP
    assert await _events(client_id) == 1
    async with AsyncSessionLocal() as db:
        sibling = await db.get(ClientSalesInvoice, sibling_id)
        assert (sibling.client_id, sibling.match_reason) == (client_id, "no_orders")


async def test_number_without_assigning_refuses_another_number(client, seed):
    client_id = await _client_without_orders(nip=fx.OTHER_CLIENT_NIP)

    response = await _number_only(client, seed, client_id)

    assert response.status_code == 409
    assert "inny numer" in response.json()["detail"]
    assert await _nip(client_id) == fx.OTHER_CLIENT_NIP
    assert await _events(client_id) == 0
    assert (await fx.invoice(fx.KSEF_UNKNOWN)).match_reason == "unknown_buyer"


async def test_number_without_assigning_refuses_a_number_of_another_client(
    client, seed
):
    await _client_without_orders(nip=fx.UNKNOWN_NIP)
    client_id = await _client_without_orders()

    response = await _number_only(client, seed, client_id)

    assert response.status_code == 409
    assert "inny klient" in response.json()["detail"]
    assert await _nip(client_id) is None


async def test_number_without_assigning_keeps_the_invoices_own_client(client, seed):
    """Faktura ma już klienta: numer idzie do niego, nie do klienta z żądania."""

    own_id = await _client_without_orders()
    other_id = await _client_without_orders()
    invoice = await fx.invoice(fx.KSEF_UNKNOWN)
    async with AsyncSessionLocal() as db:
        row = await db.get(ClientSalesInvoice, invoice.id)
        row.client_id = own_id
        row.match_reason = "reopened"
        await db.commit()

    response = await _number_only(client, seed, other_id)

    assert response.status_code == 200, response.text
    assert await _nip(own_id) == fx.UNKNOWN_NIP
    assert await _nip(other_id) is None


async def test_number_without_assigning_needs_an_existing_client(client, seed):
    response = await _number_only(client, seed, 999999999)

    assert response.status_code == 404


@pytest.mark.parametrize("role", ["recruiter", "dl"])
async def test_number_without_assigning_is_only_for_finance(client, seed, role):
    client_id = await _client_without_orders()

    response = await _number_only(client, seed, client_id, user=role)

    assert response.status_code == 403
    assert await _nip(client_id) is None
