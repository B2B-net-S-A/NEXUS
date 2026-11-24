"""Raport „Rabat od obrotu rocznego” z fakturami sprzed KSeF z archiwum eBI24 (24.11.2026).

Faktury za styczeń–marzec są tylko w archiwum eBI24 (wiersz w
``finance_archive_documents``, pozycje w pliku JSON), od kwietnia w KSeF
(``client_sales_invoices``). Raport dolicza archiwum tak samo jak
``rebate.year_rebate``: obrót przed rabatem bez pozycji ze słowem wyłączającym
klienta, kurs NBP z dnia przed datą sprzedaży, miesiąc z daty sprzedaży. Bez
archiwum obrót roku był zaniżony o kwartał, a raport ostrzegał o niepełnym
okresie. Numery, nazwy, kwoty, progi i kursy fikcyjne.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Optional

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_archive import FinanceArchiveDocument
from app.services.client_invoicing import issue_settings, rebate
from app.services.client_reports.generators import annual_spend
from app.services.client_reports.registry import ReportContext, format_amount
from app.services.client_reports.schedule import Period, period_from_key

pytestmark = pytest.mark.asyncio

TERMS = rebate.parse_terms(
    {
        "threshold_currency": "EUR",
        "periods": [{"from_year": 2026, "tiers": [{"up_to": None, "rate": 1}]}],
        "exclude_words": ["hotel"],
    }
)
PARAMS = {
    "currency": "EUR",
    "tiers": [{"up_to": 1000, "rate": 1}, {"up_to": None, "rate": 2}],
    "marginal": True,
}
#: Kurs fikcyjny: 1 EUR = 4 PLN każdego dnia.
EUR_IN_PLN = Decimal("4")


def _line(units: str, price: int, net: int, name: str = "Usługi informatyczne") -> dict:
    """Pozycja z pliku eBI24 (grosze): cena przed rabatem, netto po nim."""
    return {
        "name": name,
        "amountOfUnits": units,
        "unitNettPrice": price,
        "nettAmount": net,
    }


#: 2 × 100,00 EUR z rabatem 5% na wierszu (190,00) — obrót przed rabatem 200,00.
SERVICE = _line("2", 10000, 19000)
HOTEL = _line("1", 5000, 5000, "Hotel")
#: 2 × 400,00 PLN z rabatem 5% (760,00) — obrót 800,00 PLN = 200,00 EUR po kursie.
SERVICE_PLN = _line("2", 40000, 76000)


def _foreign_id() -> str:
    return f"FI{uuid.uuid4().int % 10**8:08d}"


def _ksef() -> str:
    tail = uuid.uuid4().hex.upper()
    return f"9999999999-20260515-{tail[:12]}-{tail[12:14]}"


def _invoice_json(items: list[dict[str, Any]], currency: str = "EUR") -> dict:
    return {
        "invoiceType": "INVOICE",
        "currency": currency,
        "nettAmount": sum(item["nettAmount"] for item in items),
        "items": items,
    }


class World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.buyer = _foreign_id()
        self.client_id = 0
        self.archive_ids: list[int] = []

    async def client(self) -> None:
        async with AsyncSessionLocal() as db:
            client = Client(name=f"Bank Testowy {uuid.uuid4().hex[:8]}", nip=self.buyer)
            db.add(client)
            await db.commit()
            self.client_id = client.id

    async def archive(
        self,
        sale: str,
        content: dict[str, Any],
        *,
        number: str,
        issue: date,
        currency: str = "EUR",
        write: bool = True,
    ) -> None:
        source_id = uuid.uuid4().hex[:24]
        relative = f"ebi24_archive/{sale[:4]}/{source_id}.json"
        body = json.dumps(content).encode()
        if write:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        async with AsyncSessionLocal() as db:
            doc = FinanceArchiveDocument(
                source="ebi24",
                source_id=source_id,
                schema_name="EUROPEAN_INCOME_INVOICE",
                kind="sale",
                invoice_number=number,
                issue_date=issue,
                partner_name="Bank Testowy",
                partner_id=self.buyer,
                currency=currency,
                net_amount=Decimal(content["nettAmount"]) / 100,
                file_type="ebi",
                file_path=relative,
                file_sha256=hashlib.sha256(body).hexdigest(),
                meta={"transactionDate": f"{sale}T00:00:00.000"},
            )
            db.add(doc)
            await db.commit()
            self.archive_ids.append(doc.id)

    async def ksef(self, month: int) -> None:
        async with AsyncSessionLocal() as db:
            db.add(
                ClientSalesInvoice(
                    ksef_number=_ksef(),
                    xml_sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                    buyer_foreign_id=self.buyer,
                    buyer_name="Bank Testowy",
                    client_id=self.client_id,
                    invoice_number=f"K{month}/2026/UE",
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
    await world.client()
    # KSeF od kwietnia: po 80,00 EUR za IV–X, pierwsza wystawiona 3 maja.
    for month in range(4, 11):
        await world.ksef(month)
    # Archiwum eBI24 za I–III: obrót przed rabatem, bez hotelu.
    await world.archive(
        "2026-01-31",
        _invoice_json([SERVICE, HOTEL]),
        number="A1/2026/UE",
        issue=date(2026, 2, 2),
    )
    # Luty w PLN: kurs z dnia przed datą sprzedaży, nie przed wystawieniem.
    await world.archive(
        "2026-02-27",
        _invoice_json([SERVICE_PLN], "PLN"),
        number="A2/2026/UE",
        issue=date(2026, 3, 2),
        currency="PLN",
    )
    await world.archive(
        "2026-03-31",
        _invoice_json([SERVICE]),
        number="A3/2026/UE",
        issue=date(2026, 4, 2),
    )
    # Plik nieczytelny (brak na dysku): poza obrotem, raport ma to pokazać.
    await world.archive(
        "2026-03-31",
        _invoice_json([SERVICE]),
        number="A4/2026/UE",
        issue=date(2026, 4, 2),
        write=False,
    )
    # Grudzień poprzedniego roku wystawiony w styczniu: miesiąc z daty sprzedaży.
    await world.archive(
        "2025-12-31",
        _invoice_json([SERVICE]),
        number="A12/2025/UE",
        issue=date(2026, 1, 5),
    )


class FakeRates:
    """Kursy NBP bez tabeli ``fx_rates``: zapamiętuje, o które dni pytał raport."""

    def __init__(self) -> None:
        self.days: set[date] = set()

    async def __call__(
        self, db: Any, wanted: Mapping[date, set[str]]
    ) -> dict[date, dict[str, Optional[Decimal]]]:
        self.days |= set(wanted)
        return {day: {"PLN": Decimal(1), "EUR": EUR_IN_PLN} for day in wanted}


@pytest.fixture
def world(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    world = World(tmp_path)
    monkeypatch.setattr(
        issue_settings,
        "client_rebate",
        lambda data, client_id: TERMS if client_id == world.client_id else None,
    )
    return world


def _ctx(world: World, period: Period) -> ReportContext:
    return ReportContext(
        client_id=world.client_id,
        client_name="Bank Testowy",
        period=period,
        params=PARAMS,
        today=date(2026, 11, 24),
    )


def _sheet(data: Any, name: str) -> Any:
    return next(sheet for sheet in data.sheets if sheet.name == name)


async def test_year_with_pre_ksef_archive_is_complete(world, monkeypatch) -> None:
    rates = FakeRates()
    monkeypatch.setattr(annual_spend, "rates_to_pln_by_date", rates)
    await _seed(world)
    try:
        async with AsyncSessionLocal() as db:
            data = await annual_spend._load(
                db, _ctx(world, period_from_key("annual", "2026"))
            )
        # I–III z archiwum po 200,00 EUR, IV–X z KSeF po 80,00 EUR.
        headline = data.lines[0]
        assert headline.value == format_amount(Decimal("1160.00"))
        assert headline.label == "Obrót usług przed rabatem (EUR, z przeliczeniem NBP)"
        # Ostrzeżenie o niepełnym okresie znika.
        assert not [check for check in data.checks if "niepełny" in check]
        lines = {line.label: line.value for line in data.lines}
        # Do 1000 po 1%, nadwyżka 160 po 2%.
        assert lines["Kwota rabatu (EUR)"] == format_amount(Decimal("13.20"))
        assert lines["w tym faktury w PLN (netto PLN)"] == format_amount(
            Decimal("760.00")
        )
        # Kurs lutowej faktury w PLN z dnia przed datą sprzedaży (27.02).
        assert rates.days == {date(2026, 2, 26)}
        # Plik nieczytelny trafia do kontroli.
        assert [check for check in data.checks if "bez czytelnego pliku" in check] == [
            "Faktury sprzed KSeF bez czytelnego pliku w archiwum eBI24: 1 — nie weszły "
            "do obrotu, więc obrót jest zaniżony; sprawdź pliki archiwum przed wysłaniem."
        ]
        assert (
            "Faktury sprzed KSeF z archiwum eBI24 w obrocie: 3 (miesiąc i kurs NBP "
            "z daty sprzedaży)." in data.checks
        )
        assert any("(1 faktur)" in check for check in data.checks)  # hotel wyjęty
        # Lista faktur: archiwum za I–III (bez grudnia 2025) przed KSeF.
        invoices = _sheet(data, "Faktury").rows
        assert [row[0] for row in invoices[:4]] == [
            "A1/2026/UE",
            "A2/2026/UE",
            "A3/2026/UE",
            "K4/2026/UE",
        ]
        assert invoices[0][1] == date(2026, 2, 2)
        assert len(invoices) == 10
        turnover = {row[0]: row for row in _sheet(data, "Obrót").rows}
        assert turnover["EUR"][1] == 9 and turnover["PLN"][1] == 1
    finally:
        await world.drop()


async def test_archive_alone_still_flags_late_start(world, monkeypatch) -> None:
    """Archiwum, które zaczyna się w marcu, nie udaje pełnego roku."""
    monkeypatch.setattr(annual_spend, "rates_to_pln_by_date", FakeRates())
    await world.client()
    await world.archive(
        "2026-03-31",
        _invoice_json([SERVICE]),
        number="A3/2026/UE",
        issue=date(2026, 4, 2),
    )
    await world.ksef(4)
    try:
        async with AsyncSessionLocal() as db:
            data = await annual_spend._load(
                db, _ctx(world, period_from_key("annual", "2026"))
            )
        late = [check for check in data.checks if "niepełny" in check]
        assert late == [
            "Faktury z KSeF i archiwum eBI24 są w NEXUSIE od 31.03.2026 — obrót za "
            "wcześniejsze miesiące okresu jest niepełny; uzupełnij pobranie z KSeF "
            "albo archiwum eBI24 przed wysłaniem."
        ]
        assert not [check for check in data.checks if "bez czytelnego pliku" in check]
    finally:
        await world.drop()


async def test_period_across_two_years_takes_archive_months_of_both(
    world, monkeypatch
) -> None:
    """Okres przez dwa lata kalendarzowe (np. rok umowy): miesiące z obu lat archiwum."""
    monkeypatch.setattr(annual_spend, "rates_to_pln_by_date", FakeRates())
    await _seed(world)
    period = Period("2025-12-01", date(2025, 12, 1), date(2026, 2, 28), "XII–II")
    try:
        async with AsyncSessionLocal() as db:
            data = await annual_spend._load(db, _ctx(world, period))
        assert data.lines[0].value == format_amount(Decimal("600.00"))
        numbers = [row[0] for row in _sheet(data, "Faktury").rows]
        assert numbers == ["A12/2025/UE", "A1/2026/UE", "A2/2026/UE"]
        # Plik nieczytelny jest za marzec, czyli poza okresem.
        assert not [check for check in data.checks if "bez czytelnego pliku" in check]
    finally:
        await world.drop()
