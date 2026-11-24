"""Obrót sprzed KSeF w rabacie od obrotu: faktury z archiwum eBI24 na bazie (24.11.2026).

Faktury za styczeń–marzec są tylko w archiwum eBI24 (wiersz w
``finance_archive_documents``, pozycje w pliku JSON), od kwietnia w KSeF
(``client_sales_invoices``). Do obrotu progu liczą się dokumenty sprzedaży
wystawione w eBI24, bez numeru KSeF, dla nabywcy z numerem klienta, za miesiąc
daty sprzedaży; obrót przed rabatem, bez pozycji wyłączonych, korekta jako
różnica. Bez archiwum próg pada za późno, a karta nie pokazuje korekty.
Numery, nazwy i kwoty fikcyjne.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_archive import FinanceArchiveDocument
from app.services.client_invoicing import rebate

pytestmark = pytest.mark.asyncio

TERMS = rebate.parse_terms(
    {
        "threshold_currency": "EUR",
        "periods": [
            {
                "from_year": 2026,
                "tiers": [{"up_to": 1000, "rate": 1}, {"up_to": None, "rate": 1.5}],
            }
        ],
        "exclude_words": ["hotel"],
    }
)
#: Usługa 2 × 100,00 z rabatem 5% na wierszu (95,00) — obrót przed rabatem 200,00.
SERVICE = {
    "name": "Usługi informatyczne",
    "amountOfUnits": "2",
    "unitNettPrice": 10000,
    "discountRate": 500,
    "nettAmount": 19000,
}
HOTEL = {
    "name": "Hotel",
    "amountOfUnits": "1",
    "unitNettPrice": 5000,
    "discountRate": 0,
    "nettAmount": 5000,
}


def _foreign_id() -> str:
    return f"FI{uuid.uuid4().int % 10**8:08d}"


def _ksef() -> str:
    tail = uuid.uuid4().hex.upper()
    return f"9999999999-20260515-{tail[:12]}-{tail[12:14]}"


def _invoice_json(items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "invoiceType": "INVOICE",
        "currency": "EUR",
        "nettAmount": sum(item["nettAmount"] for item in items),
        "items": items,
        **extra,
    }


class World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.buyer = _foreign_id()
        self.client_id = 0
        self.archive_ids: list[int] = []

    async def archive(
        self,
        sale: str,
        content: Optional[dict[str, Any]],
        *,
        partner: Optional[str] = None,
        number: Optional[str] = None,
        issue: Optional[date] = None,
        ksef: Optional[str] = None,
        kind: str = "sale",
        file_type: str = "ebi",
        net: str = "500.00",
        write: bool = True,
    ) -> None:
        source_id = uuid.uuid4().hex[:24]
        relative = f"ebi24_archive/2026/{source_id}.json"
        body = json.dumps(content or {}).encode()
        if write and content is not None:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        async with AsyncSessionLocal() as db:
            doc = FinanceArchiveDocument(
                source="ebi24",
                source_id=source_id,
                schema_name="EUROPEAN_INCOME_INVOICE",
                kind=kind,
                invoice_number=number or f"A-{source_id[:6]}/2026/UE",
                issue_date=issue or date.fromisoformat(sale),
                partner_name="Bank Testowy",
                partner_id=partner or self.buyer,
                currency="EUR",
                net_amount=Decimal(net),
                ksef_number=ksef,
                file_type=file_type,
                file_path=relative,
                file_sha256=hashlib.sha256(body).hexdigest(),
                meta={"transactionDate": f"{sale}T00:00:00.000"},
            )
            db.add(doc)
            await db.commit()
            self.archive_ids.append(doc.id)

    async def ksef(self, month: int, *, number: str) -> None:
        async with AsyncSessionLocal() as db:
            db.add(
                ClientSalesInvoice(
                    ksef_number=_ksef(),
                    xml_sha256=hashlib.sha256(number.encode()).hexdigest(),
                    buyer_foreign_id=self.buyer,
                    buyer_name="Bank Testowy",
                    client_id=self.client_id,
                    invoice_number=number,
                    issue_date=date(2026, month + 1, 3),
                    sale_date=date(2026, month, 28),
                    period_year=2026,
                    period_month=month,
                    period_source="invoice",
                    currency="EUR",
                    net_amount=Decimal("80.00"),
                    gross_amount=Decimal("80.00"),
                    items=[
                        {
                            "name": "Usługi",
                            "quantity": "1",
                            "unit_price": "80",
                            "net": "80.00",
                        }
                    ],
                    order_refs=[],
                    match_status="unmatched",
                )
            )
            await db.commit()

    async def drop(self) -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(FinanceArchiveDocument).where(
                    FinanceArchiveDocument.id.in_(self.archive_ids)
                )
            )
            await db.execute(
                delete(ClientSalesInvoice).where(
                    ClientSalesInvoice.client_id == self.client_id
                )
            )
            await db.execute(delete(Client).where(Client.id == self.client_id))
            await db.commit()


async def _seed(world: World) -> None:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Testowy {uuid.uuid4().hex[:8]}", nip=world.buyer)
        db.add(client)
        await db.commit()
        world.client_id = client.id
    # KSeF od kwietnia: po 80,00 EUR za IV–X.
    for month in range(4, 11):
        await world.ksef(month, number=f"K{month}/2026/UE")
    # Archiwum eBI24 za I–III — liczy się.
    await world.archive("2026-01-31", _invoice_json([SERVICE, HOTEL]))
    await world.archive("2026-02-28", _invoice_json([SERVICE]), number="A2/2026/UE")
    # Nie liczy się: duplikat lutowej faktury (ten sam numer, wystawiony później).
    await world.archive(
        "2026-02-28",
        _invoice_json([SERVICE]),
        number="a2/2026/ue",
        issue=date(2026, 5, 6),
    )
    # Marzec wystawiony 2 kwietnia: miesiąc z daty sprzedaży, nie wystawienia.
    await world.archive("2026-03-31", _invoice_json([SERVICE]), issue=date(2026, 4, 2))
    # Korekta marcowej faktury: 2 → 1 jednostka (stan przed w treści korygowanej).
    after = {**SERVICE, "amountOfUnits": "1", "nettAmount": 9500}
    await world.archive(
        "2026-03-31",
        _invoice_json(
            [after],
            invoiceType="CORRECTIVE_INVOICE",
            correctedInvoiceNettAmount=19000,
            correctedInvoiceContent=json.dumps(_invoice_json([SERVICE])),
        ),
        issue=date(2026, 4, 10),
    )
    # Nie liczy się: plik nieczytelny (brak na dysku) — karta ma to pokazać.
    await world.archive("2026-03-31", _invoice_json([SERVICE]), write=False)
    # Nie liczy się: dokument z numerem KSeF (jest już w fakturach z KSeF).
    await world.archive("2026-04-30", _invoice_json([SERVICE]), ksef=_ksef())
    # Nie liczy się: ta sama faktura co w KSeF, choć archiwum nie ma numeru KSeF.
    await world.archive("2026-05-31", _invoice_json([SERVICE]), number="K5/2026/UE")
    # Nie liczy się: inny nabywca (np. oddział albo spółka z grupy).
    await world.archive("2026-01-31", _invoice_json([SERVICE]), partner=_foreign_id())
    # Nie liczy się: PDF wgrany do eBI24 (bez pozycji), koszt, grudzień poprzedniego roku.
    await world.archive("2026-02-28", None, file_type="pdf")
    await world.archive("2026-02-10", _invoice_json([SERVICE]), kind="cost")
    await world.archive("2025-12-31", _invoice_json([SERVICE]), issue=date(2026, 1, 5))


async def test_pre_ksef_archive_moves_threshold_crossing_into_october(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    world = World(tmp_path)
    await _seed(world)
    try:
        async with AsyncSessionLocal() as db:
            status = await rebate.year_rebate(
                db, client_id=world.client_id, year=2026, terms=TERMS
            )
        assert status is not None
        # I–III z archiwum: obrót przed rabatem, bez hotelu, korekta jako różnica.
        assert status.month_turnover == {
            1: Decimal("200.00"),
            2: Decimal("200.00"),
            3: Decimal("100.00"),
            **{month: Decimal("80.00") for month in range(4, 11)},
        }
        assert status.turnover == Decimal("1060.00")
        # Do końca IX obrót równy progowi (granica włącznie), w X go przekracza.
        assert status.rate_for(10).rate == Decimal("1")
        assert status.rate_for(11).rate == Decimal("1.5")
        assert status.corrections == (
            rebate.Correction(
                month=10,
                rate_diff=Decimal("0.5"),
                excess=Decimal("60.00"),
                amounts=(("EUR", Decimal("0.30")),),
            ),
        )
        assert status.invoices == 11 and status.excluded == 1
        assert status.archived == 4
        assert status.unreadable == 1
        data = rebate.payload(status, month=11, on_invoice=None, currency="EUR")
        assert data["archived"] == 4 and data["unreadable"] == 1
    finally:
        await world.drop()


async def test_client_without_archive_counts_only_ksef(tmp_path, monkeypatch) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    world = World(tmp_path)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Testowy {uuid.uuid4().hex[:8]}", nip=world.buyer)
        db.add(client)
        await db.commit()
        world.client_id = client.id
    await world.ksef(10, number="K10/2026/UE")
    try:
        async with AsyncSessionLocal() as db:
            status = await rebate.year_rebate(
                db, client_id=world.client_id, year=2026, terms=TERMS
            )
        assert status is not None
        assert status.month_turnover == {10: Decimal("80.00")}
        assert status.archived == 0 and status.unreadable == 0
    finally:
        await world.drop()
