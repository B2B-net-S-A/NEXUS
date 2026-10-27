"""„Zastosuj” dla przedłużenia, które nachodzi na obecne zamówienie (27.10.2026).

Zgłoszenie z 27.10.2026: nowe zamówienie od 01.12, obecne do 31.12. Do tej zmiany
„Zastosuj” odmawiał wiersza ``overlap`` i dokument zostawał w kolejce na
zawsze. Teraz człowiek wybiera w panelu: skrócić obecne zamówienie do dnia
przed nowym albo zacząć nowe dzień po obecnym. Postgres — sprawdza CI.
"""

from datetime import date
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.order_mail import OrderMailDocument
from app.services.order_mail_apply import apply_document
from app.services.order_mail_planner import OVERLAP_START_AFTER, OVERLAP_TRIM_PREVIOUS


async def _renewal_overlapping_current(db):
    client = Client(name=f"Overlap mail {uuid.uuid4().hex}")
    candidate = Candidate(name="Jan", lastname="Przedluzony" + uuid.uuid4().hex[:8])
    db.add_all([client, candidate])
    await db.flush()
    contract = Contract(
        client_id=client.id,
        candidate_id=candidate.id,
        status=ContractStatus.active,
        start_date=date(2033, 1, 2),
        rate_client=Decimal("120"),
        rate_candidate=Decimal("100"),
        rate_unit=RateUnit.hourly,
    )
    db.add(contract)
    await db.flush()
    current = ClientOrder(
        client_id=client.id,
        contract_id=contract.id,
        title="9/2033",
        status=ClientOrderStatus.active,
        start_date=date(2033, 7, 1),
        end_date=date(2033, 12, 31),
        rate_client=Decimal("120"),
        rate_candidate=Decimal("100"),
        rate_unit=RateUnit.hourly,
        order_type="periodic",
    )
    db.add(current)
    await db.flush()
    doc = OrderMailDocument(
        internet_message_id=f"<{uuid.uuid4()}@example.test>",
        client_id=client.id,
        outcome="needs_review",
        gate_verdict="review",
        extraction={
            "title": "10/2033",
            "start_date": "2033-12-01",
            "end_date": "2034-05-01",
            "source": "claude",
            "uncertain": False,
            "confidence": {"title": 1.0},
            "consultant_rows": [
                {
                    "consultant_name": f"{candidate.name} {candidate.lastname}",
                    "rate_client": "138.00",
                    "rate_unit": "hour",
                    "start_date": "2033-12-01",
                    "end_date": "2034-05-01",
                    "uncertain": False,
                }
            ],
        },
        proposal={"rows": [{"action": "overlap"}]},
    )
    db.add(doc)
    await db.flush()
    return contract, current, doc


async def _new_order(db, result) -> ClientOrder:
    assert result.ok, result.as_dict()
    return await db.get(ClientOrder, result.rows[0].order_id)


@pytest.mark.asyncio
async def test_without_a_choice_the_overlap_is_still_refused():
    async with AsyncSessionLocal() as db:
        _, current, doc = await _renewal_overlapping_current(db)
        result = await apply_document(db, doc, actor_user_id=None)
        assert not result.ok
        assert f"#{current.id}" in result.error
        await db.refresh(current)
        assert current.end_date == date(2033, 12, 31)
        await db.rollback()


@pytest.mark.asyncio
async def test_trim_previous_ends_the_current_order_the_day_before_the_new_one():
    async with AsyncSessionLocal() as db:
        contract, current, doc = await _renewal_overlapping_current(db)
        result = await apply_document(
            db, doc, actor_user_id=None, overlap_choices={0: OVERLAP_TRIM_PREVIOUS}
        )
        order = await _new_order(db, result)
        assert result.rows[0].action == "overlap"
        assert order.id != current.id and order.contract_id == contract.id
        assert (order.start_date, order.end_date) == (
            date(2033, 12, 1),
            date(2034, 5, 1),
        )
        assert order.rate_client == Decimal("138")
        await db.refresh(current)
        assert current.end_date == date(2033, 11, 30)
        assert current.rate_client == Decimal("120")
        trace = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "client_order",
                Activity.entity_id == current.id,
                Activity.action == "order_mail_trim_previous",
            )
        )
        assert trace is not None
        assert trace.details["before"]["end_date"] == "2033-12-31"
        assert trace.details["end_date"] == "2033-11-30"
        assert trace.details["document_id"] == doc.id
        await db.rollback()


@pytest.mark.asyncio
async def test_start_after_keeps_the_current_order_and_moves_the_new_start():
    async with AsyncSessionLocal() as db:
        _, current, doc = await _renewal_overlapping_current(db)
        result = await apply_document(
            db, doc, actor_user_id=None, overlap_choices={0: OVERLAP_START_AFTER}
        )
        order = await _new_order(db, result)
        assert (order.start_date, order.end_date) == (
            date(2034, 1, 1),
            date(2034, 5, 1),
        )
        await db.refresh(current)
        assert current.end_date == date(2033, 12, 31)
        await db.rollback()


@pytest.mark.asyncio
async def test_an_invoiced_month_is_never_trimmed_by_the_queue():
    async with AsyncSessionLocal() as db:
        _, current, doc = await _renewal_overlapping_current(db)
        invoice = ClientSalesInvoice(
            ksef_number=f"5260000000-20331231-{uuid.uuid4().hex[:12].upper()}-01",
            xml_sha256="b" * 64,
            buyer_nip="5260000000",
            invoice_number=f"FS {uuid.uuid4().hex[:6]}",
            issue_date=date(2033, 12, 31),
            period_year=2033,
            period_month=12,
            period_source="invoice",
            currency="PLN",
            net_amount=Decimal("100"),
            vat_amount=Decimal("0"),
            gross_amount=Decimal("100"),
            items=[{"name": "Usługi"}],
            order_refs=["9/2033"],
        )
        db.add(invoice)
        await db.flush()
        db.add(
            ClientSalesInvoiceLink(
                invoice_id=invoice.id,
                order_id=current.id,
                period_year=2033,
                period_month=12,
            )
        )
        await db.flush()
        result = await apply_document(
            db, doc, actor_user_id=None, overlap_choices={0: OVERLAP_TRIM_PREVIOUS}
        )
        assert not result.ok
        assert "fakturę za 12.2033" in result.error
        await db.refresh(current)
        assert current.end_date == date(2033, 12, 31)
        await db.rollback()


@pytest.mark.asyncio
async def test_a_choice_the_plan_does_not_offer_is_ignored():
    async with AsyncSessionLocal() as db:
        _, current, doc = await _renewal_overlapping_current(db)
        result = await apply_document(
            db, doc, actor_user_id=None, overlap_choices={0: "delete_previous"}
        )
        assert not result.ok
        await db.refresh(current)
        assert current.end_date == date(2033, 12, 31)
        await db.rollback()
