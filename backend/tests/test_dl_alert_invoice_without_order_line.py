"""Alert DL: faktura na osobę bez pozycji zamówienia w miesiącu usługi (C5). Dane fikcyjne."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client_order_group import ClientOrderGroup
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.dl_alert import (
    ALERT_INVOICE_WITHOUT_ORDER_LINE as ALERT,
    DL_ALERT_SECTION_BY_TYPE,
    DL_ALERT_TYPE_LABELS,
    DL_ALERT_STATUS_NEW,
    DL_ALERT_STATUS_RESOLVED,
    DlAlert,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.services.client_invoicing import line_gaps as gaps_service
from app.services.client_invoicing.line_gaps import line_gaps
from app.tasks.dl_alerts_scanner import rule_invoice_without_order_line
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 11, 20)


@pytest_asyncio.fixture(autouse=True)
async def module():
    await fx.set_module(True)
    yield
    await fx.wipe()
    await fx.set_module(None)


@pytest_asyncio.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr("app.tasks.dl_alerts_scanner.business_today", lambda: TODAY)


async def _client_with_dl() -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Klient Faktur", None)
        dl = await fx.make_user(db, "delivery_lead")
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl.id, client_id=client_id, is_head=True
            )
        )
        await db.commit()
    return client_id, dl.id


async def _person(client_id: int, first: str, last: str) -> None:
    async with AsyncSessionLocal() as db:
        await fx._person(db, client_id, first, last)
        await db.commit()


async def _invoice(
    client_id: int,
    item: str,
    *,
    period: tuple[int, int] = (2026, 10),
    reason: str = "amount_differs",
) -> int:
    async with AsyncSessionLocal() as db:
        invoice = ClientSalesInvoice(
            ksef_number=f"{fx.COMPANY_NIP}-20261103-{uuid.uuid4().hex[:12].upper()}-AA",
            xml_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            buyer_nip="1111111111",
            client_id=client_id,
            invoice_number=f"FS {uuid.uuid4().hex[:6]}",
            issue_date=date(2026, 11, 3),
            period_year=period[0],
            period_month=period[1],
            period_source="invoice",
            net_amount=Decimal("1000.00"),
            gross_amount=Decimal("1230.00"),
            vat_amount=Decimal("230.00"),
            items=[{"name": item, "unit_price": "100.00"}],
            match_status="unmatched",
            match_reason=reason,
        )
        db.add(invoice)
        await db.commit()
        return invoice.id


async def _alerts(user_id: int) -> list[DlAlert]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(DlAlert).where(
                    DlAlert.user_id == user_id, DlAlert.alert_type == ALERT
                )
            )
        )


async def _scan() -> int:
    async with AsyncSessionLocal() as db:
        created = await rule_invoice_without_order_line(db)
        await db.commit()
    return created


async def _gaps() -> list:
    async with AsyncSessionLocal() as db:
        return await line_gaps(db, TODAY)


async def test_person_with_contract_but_no_line_alerts_their_dl() -> None:
    client_id, dl_id = await _client_with_dl()
    await _person(client_id, "Łukasz", "Bezpozycji")
    invoice_id = await _invoice(client_id, "Usługa IT Lukasz Bezpozycji 10/2026")

    assert await _scan() == 1

    [alert] = await _alerts(dl_id)
    assert alert.client_id == client_id
    assert "Łukasz Bezpozycji" in alert.message
    assert "10.2026" in alert.message
    assert alert.status == DL_ALERT_STATUS_NEW
    assert f"invoice:{invoice_id}:" in alert.dedupe_key
    assert alert.link == f"/clients/{client_id}?tab=zamowienia"


async def test_person_with_a_line_in_the_month_is_not_a_gap() -> None:
    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Klient Z Linią", None)
        await fx.md_group(
            db, client_id, "Z/1", people=[("Anna", "Zlinia", "1200", "20")]
        )
        await db.commit()
    await _invoice(client_id, "Anna Zlinia, usługa")

    assert [gap for gap in await _gaps() if gap.client_id == client_id] == []


async def test_person_on_a_cost_order_with_two_people_is_not_a_gap() -> None:
    """Pozycja kosztowa ma nazwiska po przecinku; osoba ma linię w zamówieniu."""

    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Klient Kosztowy", None)
        await fx.md_group(
            db,
            client_id,
            "K/1",
            people=[
                ("Hanna", "Kosztowa", "1200", None),
                ("Olek", "Budzetowy", "1200", None),
            ],
            cost=True,
        )
        await db.commit()
    await _invoice(client_id, "Hanna Kosztowa usługa")

    assert [gap for gap in await _gaps() if gap.client_id == client_id] == []


async def test_person_in_a_shared_md_pool_is_not_a_gap() -> None:
    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Klient Pula", None)
        group_id, _lines = await fx.md_group(
            db,
            client_id,
            "P/1",
            people=[("Ala", "Pulowa", "1200", None), ("Ola", "Wspolna", "1300", None)],
        )
        group = await db.get(ClientOrderGroup, group_id)
        group.md_budget_mode = "shared"
        group.is_md_budget_based = True
        group.md_budget_total = Decimal("100")
        group.md_budget_remaining = Decimal("100")
        await db.commit()
    await _invoice(client_id, "Ala Pulowa usługa")

    assert [gap for gap in await _gaps() if gap.client_id == client_id] == []


async def test_name_without_a_contract_stays_with_finance() -> None:
    client_id, dl_id = await _client_with_dl()
    await _invoice(client_id, "Nieznana Osoba usługa")

    assert await _scan() == 0
    assert await _alerts(dl_id) == []


async def test_invoice_older_than_six_months_does_not_alert() -> None:
    client_id, dl_id = await _client_with_dl()
    await _person(client_id, "Maja", "Stara")
    await _invoice(client_id, "Maja Stara", period=(2026, 4))

    assert await _scan() == 0
    assert await _alerts(dl_id) == []


async def test_other_reasons_do_not_alert() -> None:
    client_id, dl_id = await _client_with_dl()
    await _person(client_id, "Nela", "Waluta")
    await _invoice(client_id, "Nela Waluta", reason="currency_differs")

    await _scan()

    assert await _alerts(dl_id) == []


async def test_alert_closes_when_finance_assigns_the_invoice() -> None:
    client_id, dl_id = await _client_with_dl()
    await _person(client_id, "Olek", "Zamykany")
    invoice_id = await _invoice(client_id, "Olek Zamykany")
    await _scan()

    async with AsyncSessionLocal() as db:
        invoice = await db.get(ClientSalesInvoice, invoice_id)
        invoice.match_reason = "currency_differs"
        await db.commit()
    await _scan()

    [alert] = await _alerts(dl_id)
    assert alert.status == DL_ALERT_STATUS_RESOLVED


async def test_second_run_does_not_duplicate() -> None:
    client_id, dl_id = await _client_with_dl()
    await _person(client_id, "Pola", "Powtorka")
    await _invoice(client_id, "Pola Powtorka")

    await _scan()
    await _scan()

    assert len(await _alerts(dl_id)) == 1


async def test_module_off_emits_nothing_and_closes_open_cards() -> None:
    client_id, dl_id = await _client_with_dl()
    await _person(client_id, "Radek", "Wylaczony")
    await _invoice(client_id, "Radek Wylaczony")
    await _scan()
    await fx.set_module(False)

    await _scan()

    [alert] = await _alerts(dl_id)
    assert alert.status == DL_ALERT_STATUS_RESOLVED


async def test_type_has_label_and_section() -> None:
    assert DL_ALERT_TYPE_LABELS[ALERT]
    assert DL_ALERT_SECTION_BY_TYPE[ALERT]
    assert gaps_service.GAP_MONTHS_BACK == 6
