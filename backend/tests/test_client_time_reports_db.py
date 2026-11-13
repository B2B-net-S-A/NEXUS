"""Raport klienta T4T na bazie (plan Nordei N1): kartoteka z faktur do klienta
w KSeF, podpowiedź po imieniu i nazwisku, wersje raportu, statusy i zmiany
między wersjami, godziny z faktury kontraktora = netto ÷ stawka.

Osoby, numery, NIDS i kwoty fikcyjne.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import openpyxl
import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.client_settlement import ClientContractorInvoice
from app.models.contract import ContractStatus, RateUnit
from app.services.client_settlements import time_reports
from app.services.client_settlements.service import SettlementError
from tests.test_client_audit_2026_09_24 import _cleanup, _client, _contract

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)
MONTH = "2026-09"
NIDS = "2020-000001"
WEEKS = [(1, 6, 32), (7, 13, 40), (14, 20, 40), (21, 24, 32), (25, 30, 32)]
HEADER = [
    "Investment ID",
    "Name",
    "UserId",
    "TimePeriodStart",
    "TimePeriodFinish",
    "DateWorked",
    "Sum of Hours",
    "TimesheetStatus",
]


def _rows(number: str, name: str, last_status: int = 2) -> list[list[object]]:
    return [
        [
            NIDS,
            name,
            number,
            datetime(2026, 9, start),
            datetime(2026, 9, end),
            datetime(2026, 9, start),
            hours,
            last_status if start == 25 else 2,
        ]
        for start, end, hours in WEEKS
    ]


def _xlsx(*people: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(HEADER)
    for rows in people:
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def _person(client_id: int, first: str, last: str) -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name=first, lastname=last)
        db.add(candidate)
        await db.commit()
        candidate_id = candidate.id
    return await _contract(
        client_id,
        candidate_id,
        start_date=date(2026, 1, 1),
        rate_unit=RateUnit.hourly,
        rate_candidate=100,
        rate_client=120,
        status=ContractStatus.active,
    )


async def _sales_invoice(client_id: int, contract_id: int, item: str) -> None:
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=f"T4T-{client_id}-{uuid.uuid4().hex[:6]}",
            start_date=date(2026, 1, 1),
            status="active",
            order_type="md",
            is_cost_based=False,
            is_md_budget_based=False,
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            order_group_id=group.id,
            title="linia",
            status=ClientOrderStatus.active,
            start_date=date(2026, 1, 1),
        )
        db.add(line)
        invoice = ClientSalesInvoice(
            ksef_number=f"9990000001-20260930-{uuid.uuid4().hex[:12].upper()}-AB",
            xml_sha256="b" * 64,
            client_id=client_id,
            invoice_number=f"FS {uuid.uuid4().hex[:4]}/09/2026",
            issue_date=date(2026, 9, 30),
            period_year=2026,
            period_month=9,
            period_source="invoice",
            currency="PLN",
            net_amount=Decimal("21120"),
            vat_amount=Decimal("0"),
            gross_amount=Decimal("21120"),
            items=[{"name": item, "unit": "godz.", "quantity": "176"}],
            order_refs=[],
        )
        db.add(invoice)
        await db.flush()
        db.add(
            ClientSalesInvoiceLink(
                invoice_id=invoice.id,
                order_id=line.id,
                period_year=2026,
                period_month=9,
            )
        )
        await db.commit()


async def _contractor_invoice(contract_id: int, net: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientContractorInvoice(
                ksef_number=f"998-{uuid.uuid4().hex[:20]}",
                seller_nip="9980000000",
                issue_date=date(2026, 9, 30),
                net_amount=Decimal(net),
                gross_amount=Decimal(net),
                currency="PLN",
                contract_id=contract_id,
                period_month=MONTH,
                nip_state="known",
            )
        )
        await db.commit()


async def _upload(client_id: int, content: bytes, received: date) -> dict:
    async with AsyncSessionLocal() as db:
        result = await time_reports.upload(
            db,
            client_id,
            MONTH,
            received_on=received,
            file_name="t4t.xlsx",
            content=content,
            sheet=None,
            actor=ACTOR,
        )
        await db.commit()
        return result


async def _view(client_id: int, version_id: int | None = None) -> dict:
    async with AsyncSessionLocal() as db:
        return await time_reports.month_view(
            db, client_id, MONTH, version_id=version_id
        )


async def _drop(client_id: int, contract_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientContractorInvoice).where(
                ClientContractorInvoice.contract_id.in_(contract_ids)
            )
        )
        await db.execute(
            delete(ClientSalesInvoice).where(ClientSalesInvoice.client_id == client_id)
        )
        await db.commit()
    await _cleanup(client_id)


async def test_kartoteka_wersje_i_statusy_osob():
    client_id = await _client()
    jan = await _person(client_id, "Jan", "Testowy")
    anna = await _person(client_id, "Anna", "Przykładowa")
    ewa = await _person(client_id, "Ewa", "Próbna")
    try:
        await _sales_invoice(
            client_id,
            jan,
            f"NIDS:{NIDS}, IT Developer, Contact: Osoba Kontaktowa, Jan Testowy ID:M000001",
        )
        # Faktura innej osoby przypięta do linii zamówienia Jana nie daje numeru.
        await _sales_invoice(
            client_id,
            jan,
            "NIDS:2020-000009, IT Tester, Contact: X, Inna Osoba ID:M000077",
        )
        async with AsyncSessionLocal() as db:
            filled = await time_reports.fill_from_ksef(db, client_id, now=local_now())
            await db.commit()
        assert filled == {
            "invoices": 2,
            "added": 2,
            "updated": 0,
            "skipped": 1,
            "suggested": 0,
        }

        await _contractor_invoice(jan, "17600.00")
        await _contractor_invoice(anna, "17600.00")

        first = _xlsx(
            _rows("M000001", "Jan Testowy"),
            _rows("M000002", "Anna Maria Przykladowa", last_status=1),
            _rows("M000009", "Ktoś Obcy"),
        )
        v1 = await _upload(client_id, first, date(2026, 10, 1))
        assert v1["version"]["version_no"] == 1
        assert v1["suggested"] == 1  # Anna po imieniu i nazwisku, obcy bez podpowiedzi

        view = await _view(client_id)
        by_key = {r["key"]: r for r in view["rows"]}
        assert by_key["M000001"]["status"] == "ok"
        assert by_key["M000001"]["invoice_hours"] == "176.00"
        assert by_key["M000002"]["status"] == "unmatched"
        assert by_key["M000002"]["mapping"] == "suggested"
        assert by_key["M000009"]["status"] == "unmatched"

        async with AsyncSessionLocal() as db:
            ids = await time_reports.ids_view(db, client_id, MONTH)
            (suggestion,) = ids["suggestions"]
            assert suggestion["contract_id"] == anna
            await time_reports.decide_id(
                db, suggestion["id"], approve=True, actor=ACTOR, now=local_now()
            )
            await time_reports.add_manual_id(
                db,
                client_id,
                contract_id=ewa,
                kind="client_person_no",
                value="m000009",
                actor=ACTOR,
                now=local_now(),
            )
            await db.commit()

        view = await _view(client_id)
        by_key = {r["key"]: r for r in view["rows"]}
        assert by_key["M000002"]["status"] == "waiting"  # status 1 tylko w 25–30
        assert by_key["M000009"]["status"] == "no_invoice"
        assert view["previous_version_id"] is None
        assert view["counts"]["changed"] == 0

        second = _xlsx(
            _rows("M000001", "Jan Testowy"),
            _rows("M000002", "Anna Maria Przykladowa"),
            _rows("M000009", "Ktoś Obcy"),
        )
        v2 = await _upload(client_id, second, date(2026, 10, 5))
        assert v2["version"]["version_no"] == 2
        again = await _upload(client_id, second, date(2026, 10, 6))
        assert again["duplicate"] is True and again["version"]["version_no"] == 2

        view = await _view(client_id)
        by_key = {r["key"]: r for r in view["rows"]}
        assert by_key["M000002"]["status"] == "ok"
        assert by_key["M000002"]["changed"] is True
        assert by_key["M000002"]["previous_status"] == "waiting"
        assert view["counts"]["changed"] == 1
        assert [v["counts"]["ok"] for v in view["versions"]] == [1, 2]

        older = await _view(client_id, version_id=view["versions"][0]["id"])
        assert {r["key"]: r["status"] for r in older["rows"]}["M000002"] == "waiting"

        async with AsyncSessionLocal() as db:
            card = await time_reports.person_card(
                db, client_id, MONTH, "M000002", amounts=False
            )
        assert [h["status"] for h in card["history"]] == ["waiting", "ok"]
        assert card["invoice"]["hours"] == "176.00"
        assert card["invoice"]["net"] is None  # bez dostępu do kwot
        assert card["selected"]["projects"][0]["project_no"] == NIDS

        async with AsyncSessionLocal() as db:
            card = await time_reports.person_card(
                db, client_id, MONTH, "M000001", amounts=True
            )
        assert card["invoice"]["rate"] == "100.00"
        assert {(i["kind"], i["value"]) for i in card["ids"]} == {
            ("client_person_no", "M000001"),
            ("project_no", NIDS),
        }
    finally:
        await _drop(client_id, [jan, anna, ewa])


async def test_raport_za_inny_miesiac_i_zly_numer_odrzucone():
    client_id = await _client()
    contract_id = await _person(client_id, "Jan", "Testowy")
    try:
        october = _xlsx(
            [
                [
                    NIDS,
                    "Jan Testowy",
                    "M000001",
                    datetime(2026, 10, 1),
                    datetime(2026, 10, 4),
                    None,
                    8,
                    2,
                ]
            ]
        )
        with pytest.raises(SettlementError, match="za 2026-10"):
            await _upload(client_id, october, date(2026, 11, 2))
        async with AsyncSessionLocal() as db:
            with pytest.raises(SettlementError, match="Niepoprawny numer"):
                await time_reports.add_manual_id(
                    db,
                    client_id,
                    contract_id=contract_id,
                    kind="client_person_no",
                    value="12",
                    actor=ACTOR,
                    now=local_now(),
                )
    finally:
        await _drop(client_id, [contract_id])
