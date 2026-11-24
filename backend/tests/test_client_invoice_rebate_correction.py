"""Szkic korekty zbiorczej rabatu od obrotu za miesiąc przekroczenia progu — bez bazy.

Decyzja Artura 16.11.2026: za miesiąc przekroczenia progu faktury idą jeszcze
po niższej stawce, a różnicę stawek od części obrotu ponad próg rozlicza jedna
korekta za cały miesiąc (art. 106j ust. 3). XML sprawdzamy schematem FA(3)
z ``tests/data/fa3_schema`` (kopia ``crd.gov.pl/wzor/2025/06/25/13775`` z
lokalnymi ścieżkami importów). Kwoty, progi i stawki fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from lxml import etree

from app.services.client_invoicing import (
    fa3_build,
    issue,
    issue_settings,
    rebate,
    rebate_correction,
    requirements,
)
from app.services.client_invoicing.rebate_correction import MonthInvoice

SCHEMA_PATH = Path(__file__).parent / "data" / "fa3_schema" / "schemat.xsd"
NS = {"fa": fa3_build.NAMESPACE}
DAY = date(2026, 10, 30)
TERMS_RAW = {
    "threshold_currency": "PLN",
    "periods": [
        {
            "from_year": 2026,
            "tiers": [{"up_to": 1000, "rate": 1.5}, {"up_to": None, "rate": 3.5}],
        }
    ],
    "exclude_words": ["podróż"],
}
SETTINGS = {
    "seller": {
        "nip": "9876543210",
        "name": "Spółka Testowa sp. z o.o.",
        "address_l1": "ul. Testowa 10, 00-001 Warszawa",
        "address_l2": "",
        "issue_place": "Warszawa",
    },
    "exemption_basis": "",
}
BUYER = {
    "name": "Bank Testowy S.A.",
    "number": "1111111111",
    "address_l1": "ul. Przykładowa 5, 00-002 Warszawa",
    "address_l2": "",
    "country": "PL",
}
KSEF = "9876543210-20261031-E40000000001-1A"


@pytest.fixture(scope="module")
def schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(SCHEMA_PATH)))


def _terms() -> rebate.Terms:
    terms = rebate.parse_terms(TERMS_RAW)
    assert terms is not None
    return terms


def _status(*months: tuple[int, str]) -> rebate.YearRebate:
    entries = [rebate.Entry("PLN", Decimal(net), DAY, month) for month, net in months]
    status = rebate.summarize(2026, _terms(), entries, {})
    assert status is not None
    return status


def _item(name: str, quantity: str, price: str, rate: str = "23") -> dict:
    net = rebate.cents(
        Decimal(quantity) * rebate.cents(Decimal(price) * Decimal("0.985"))
    )
    return {
        "name": name,
        "quantity": quantity,
        "unit_price": price,
        "net": format(net, "f"),
        "vat_rate": rate,
    }


def _invoice(number: str, *items: dict, kind: str = "original") -> MonthInvoice:
    net = sum((Decimal(i["net"]) for i in items), Decimal(0))
    return MonthInvoice(
        number=number,
        issue_date=date(2026, 10, 31),
        ksef_number=KSEF,
        kind=kind,
        net=net,
        items=tuple(items),
    )


def _validate(schema: etree.XMLSchema, xml: bytes) -> etree._Element:
    root = etree.fromstring(xml)
    assert schema.validate(root), [str(e) for e in schema.error_log]
    return root


# ── Kwota = różnica stawek × nadwyżka ──────────────────────────────────────


def test_amount_is_rate_difference_times_excess_over_threshold():
    # Wrzesień 900, październik 300: obrót 1200, próg 1000, nadwyżka 200,
    # różnica 3,5% − 1,5% = 2% → 4,00.
    status = _status((9, "900"), (10, "300"))
    draft = rebate_correction.plan(
        status,
        month=10,
        currency="PLN",
        invoices=[_invoice("10/10/2026", _item("Usługi IT", "3", "100"))],
        words=_terms().exclude_words,
    )
    assert draft.excess == Decimal("200.00")
    assert draft.rate_diff == Decimal("2")
    assert draft.amount == draft.rate_diff * draft.excess / 100 == Decimal("4.00")
    assert sum(fa3_build.line_net(line) for line in draft.lines) == Decimal("-4.00")
    assert not draft.problems


def test_refuses_month_without_crossing_the_threshold():
    status = _status((9, "900"), (10, "300"))
    with pytest.raises(issue.IssueError) as err:
        rebate_correction.plan(status, month=9, currency="PLN", invoices=[], words=())
    assert err.value.status_code == 409
    assert "nie przekroczył progu" in str(err.value)


def test_refuses_currency_without_invoices_in_the_month():
    status = _status((9, "900"), (10, "300"))
    with pytest.raises(issue.IssueError, match="nie ma korekty w EUR"):
        rebate_correction.plan(status, month=10, currency="EUR", invoices=[], words=())


# ── Podział na stawki, faktury korygowane ──────────────────────────────────


def test_amount_splits_by_vat_rate_and_travel_stays_out():
    invoices = [
        _invoice(
            "11/10/2026",
            _item("Usługi IT", "3", "100", "23"),
            _item("Podróż służbowa", "1", "500", "23"),
        ),
        _invoice("12/10/2026", _item("Usługi IT (UE)", "1", "100", "np II")),
    ]
    weights = rebate_correction.rate_weights(invoices, _terms().exclude_words)
    assert weights == {"23": Decimal("300.00"), "np II": Decimal("100.00")}
    parts = rebate_correction.allocate(Decimal("1.01"), weights)
    assert parts == [("23", Decimal("0.76")), ("np II", Decimal("0.25"))]
    assert sum(part for _, part in parts) == Decimal("1.01")


def test_only_original_invoices_with_service_turnover_are_corrected():
    travel_only = _invoice("13/10/2026", _item("Podróż służbowa", "1", "50"))
    correction = _invoice(
        "14/10/2026", _item("Usługi IT", "1", "10"), kind="correction"
    )
    service = _invoice("15/10/2026", _item("Usługi IT", "3", "100"))
    draft = rebate_correction.plan(
        _status((9, "900"), (10, "300")),
        month=10,
        currency="PLN",
        invoices=[travel_only, correction, service],
        words=_terms().exclude_words,
    )
    assert [invoice.number for invoice, _ in draft.corrected] == ["15/10/2026"]
    assert draft.corrected[0][1] == Decimal("300.00")


def test_unknown_vat_code_blocks_the_xml():
    draft = rebate_correction.plan(
        _status((9, "900"), (10, "300")),
        month=10,
        currency="PLN",
        invoices=[_invoice("16/10/2026", _item("Usługi", "3", "100", "oo"))],
        words=(),
    )
    assert any("oo" in problem for problem in draft.problems)


# ── XML FA(3) ──────────────────────────────────────────────────────────────


def test_collective_correction_xml_matches_fa3_schema(schema):
    invoices = [
        _invoice(f"{n}/10/2026", _item("Usługi IT", "1", "100", rate))
        for n, rate in ((1, "23"), (2, "23"), (3, "np II"))
    ]
    draft = rebate_correction.plan(
        _status((9, "900"), (10, "300")),
        month=10,
        currency="PLN",
        invoices=invoices,
        words=_terms().exclude_words,
    )
    doc = rebate_correction.document(
        draft, settings=SETTINGS, buyer=BUYER, today=date(2026, 11, 16), fx_rate=None
    )
    root = _validate(schema, fa3_build.build_xml(doc))
    fa = root.find("fa:Fa", NS)
    assert fa.findtext("fa:RodzajFaktury", namespaces=NS) == "KOR"
    assert fa.findtext("fa:TypKorekty", namespaces=NS) == "2"
    assert (
        fa.findtext("fa:OkresFaKorygowanej", namespaces=NS) == "01.10.2026-31.10.2026"
    )
    refs = fa.findall("fa:DaneFaKorygowanej", NS)
    assert [r.findtext("fa:NrFaKorygowanej", namespaces=NS) for r in refs] == [
        "1/10/2026",
        "2/10/2026",
        "3/10/2026",
    ]
    assert all(
        r.findtext("fa:NrKSeFFaKorygowanej", namespaces=NS) == KSEF for r in refs
    )
    rows = fa.findall("fa:FaWiersz", NS)
    assert sorted(r.findtext("fa:P_12", namespaces=NS) for r in rows) == ["23", "np II"]
    total = sum(Decimal(r.findtext("fa:P_11", namespaces=NS)) for r in rows)
    assert total == -draft.amount
    assert Decimal(fa.findtext("fa:P_13_1", namespaces=NS)) < 0
    assert fa.find("fa:Platnosc", NS) is None


def test_single_invoice_correction_still_matches_schema(schema):
    """Zwykła korekta jednej faktury (bez ``corrected_list``) nadal przechodzi XSD."""

    doc = fa3_build.InvoiceDocument(
        invoice_type="KOR",
        number="KOR/1/11/2026",
        issue_date=date(2026, 11, 16),
        currency="PLN",
        seller_nip="9876543210",
        seller=fa3_build.Party(name="Spółka", address_l1="ul. Testowa 1"),
        buyer=fa3_build.Party(name="Bank", address_l1="ul. Przykładowa 5"),
        buyer_ident=fa3_build.buyer_id("1111111111"),
        lines=[
            {"name": "Usługi", "quantity": "1", "unit_price": "90", "vat_rate": "23"}
        ],
        lines_before=[
            {"name": "Usługi", "quantity": "1", "unit_price": "100", "vat_rate": "23"}
        ],
        corrected=fa3_build.CorrectedInvoice(
            number="1/10/2026",
            issue_date=date(2026, 10, 31),
            ksef_number=None,
            reason="Rabat",
        ),
    )
    _validate(schema, fa3_build.build_xml(doc))


# ── prepare(): warunki klienta, odmowy, pełna ścieżka ──────────────────────


class _Db:
    def __init__(self, client):
        self.client = client

    async def get(self, model, key):
        return self.client


def _client():
    return SimpleNamespace(
        id=11,
        name="Bank Testowy",
        legal_name="Bank Testowy S.A.",
        nip="1111111111",
        address="ul. Przykładowa 5, 00-002 Warszawa",
    )


async def _settings_without_rebate(db):
    return {**SETTINGS, "clients": {}}


@pytest.mark.asyncio
async def test_prepare_refuses_client_without_rebate_terms(monkeypatch):
    monkeypatch.setattr(issue_settings, "load", _settings_without_rebate)
    monkeypatch.setattr(issue_settings, "client_rebate", lambda data, cid: None)
    with pytest.raises(issue.IssueError, match="nie ma warunków rabatu") as err:
        await rebate_correction.prepare(
            _Db(_client()),
            client_id=11,
            year=2026,
            month=10,
            currency="PLN",
            today=date(2026, 11, 16),
        )
    assert err.value.status_code == 409


@pytest.mark.asyncio
async def test_prepare_refuses_unknown_client():
    with pytest.raises(issue.IssueError) as err:
        await rebate_correction.prepare(
            _Db(None), client_id=99, year=2026, month=10, currency="PLN", today=DAY
        )
    assert err.value.status_code == 404


def _patch_prepare(monkeypatch):
    status = _status((9, "900"), (10, "300"))
    invoices = [_invoice("20/10/2026", _item("Usługi IT", "3", "100"))]

    async def load(db):
        return SETTINGS

    async def year_rebate(db, **kwargs):
        return status

    async def month_invoices(db, **kwargs):
        return invoices

    async def fx_for(db, currency, delivery):
        return None, None

    monkeypatch.setattr(issue_settings, "load", load)
    monkeypatch.setattr(issue_settings, "client_rebate", lambda data, cid: _terms())
    monkeypatch.setattr(rebate, "year_rebate", year_rebate)
    monkeypatch.setattr(rebate_correction, "_month_invoices", month_invoices)
    monkeypatch.setattr(issue, "fx_for", fx_for)


@pytest.mark.asyncio
async def test_prepare_without_client_address_shows_amount_but_no_xml(monkeypatch):
    _patch_prepare(monkeypatch)
    client = _client()
    client.address = ""
    prepared = await rebate_correction.prepare(
        _Db(client), client_id=11, year=2026, month=10, currency="PLN", today=DAY
    )
    assert prepared.xml is None
    assert "adresu w kartotece" in prepared.xml_error
    assert rebate_correction.payload(prepared, client_id=11)["amount"] == "4.00"


@pytest.mark.asyncio
async def test_prepare_builds_payload_and_schema_valid_xml(monkeypatch, schema):
    status = _status((9, "900"), (10, "300"))
    invoices = [_invoice("20/10/2026", _item("Usługi IT", "3", "100"))]

    async def load(db):
        return SETTINGS

    async def year_rebate(db, **kwargs):
        return status

    async def month_invoices(db, **kwargs):
        return invoices

    async def fx_for(db, currency, delivery):
        return None, None

    monkeypatch.setattr(issue_settings, "load", load)
    monkeypatch.setattr(issue_settings, "client_rebate", lambda data, cid: _terms())
    monkeypatch.setattr(rebate, "year_rebate", year_rebate)
    monkeypatch.setattr(rebate_correction, "_month_invoices", month_invoices)
    monkeypatch.setattr(issue, "fx_for", fx_for)

    prepared = await rebate_correction.prepare(
        _Db(_client()), client_id=11, year=2026, month=10, currency="pln", today=DAY
    )
    assert prepared.xml_error is None
    _validate(schema, prepared.xml)
    data = rebate_correction.payload(prepared, client_id=11)
    assert data["amount"] == "4.00"
    assert data["net"] == "-4.00"
    assert data["vat"] == "-0.92"
    assert data["invoice_count"] == 1
    assert data["invoices"][0]["number"] == "20/10/2026"
    assert data["lines"][0]["vat_label"] == "23%"
    assert data["xml_ready"] is True


# ── „Wystaw korektę”: szkic KOR z listą faktur (22.11.2026) ─────────────────

FULL_SETTINGS = issue_settings.normalize(
    {
        **SETTINGS,
        "accounts": {"PLN": {"number": "PL61 1090 1014 0000 0712 1981 2874"}},
        "payment_days": 30,
    }
)


class _SaveDb(_Db):
    def __init__(self, client):
        super().__init__(client)
        self.added = []

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        return None


def _patch_create(monkeypatch, *, issued=()):
    _patch_prepare(monkeypatch)

    async def load(db):
        return FULL_SETTINGS

    async def collective_issued(db, **kwargs):
        return list(issued)

    monkeypatch.setattr(issue_settings, "load", load)
    monkeypatch.setattr(issue, "collective_issued", collective_issued)


async def _create(db):
    return await rebate_correction.create(
        db,
        client_id=11,
        year=2026,
        month=10,
        currency="pln",
        actor_id=7,
        today=date(2026, 11, 22),
    )


@pytest.mark.asyncio
async def test_create_saves_kor_draft_with_corrected_list(monkeypatch, schema):
    _patch_create(monkeypatch)

    async def no_requirements(db, invoice):
        return requirements.Requirements()

    # Bez bazy: klient bez reguł ``cl.*`` (wymagania klienta do faktury).
    monkeypatch.setattr(issue, "invoice_requirements", no_requirements)
    db = _SaveDb(_client())
    invoice = await _create(db)

    assert db.added == [invoice]
    assert invoice.invoice_type == "KOR"
    assert invoice.series_code == "KOR"
    assert invoice.status == "draft"
    assert invoice.invoice_number is None
    assert invoice.corrects_id is None
    assert (invoice.period_year, invoice.period_month) == (2026, 10)
    assert invoice.currency == "PLN"
    assert invoice.due_date == date(2026, 12, 22)
    assert invoice.net_amount == Decimal("-4.00")
    collective = invoice.collective_correction
    assert collective["period"] == "01.10.2026-31.10.2026"
    assert collective["correction_type"] == "2"
    assert [i["number"] for i in collective["invoices"]] == ["20/10/2026"]
    assert collective["invoices"][0]["ksef_number"] == KSEF

    # Ten sam XML, który pójdzie do KSeF przy wysyłce (numer z serii KOR).
    invoice.invoice_number = "KOR/1/11/2026"
    doc = await issue.document(None, invoice, FULL_SETTINGS)
    root = _validate(schema, fa3_build.build_xml(doc))
    fa = root.find("fa:Fa", NS)
    assert fa.findtext("fa:RodzajFaktury", namespaces=NS) == "KOR"
    assert fa.findtext("fa:P_2", namespaces=NS) == "KOR/1/11/2026"
    assert fa.findtext("fa:TypKorekty", namespaces=NS) == "2"
    assert (
        fa.findtext("fa:OkresFaKorygowanej", namespaces=NS) == "01.10.2026-31.10.2026"
    )
    refs = fa.findall("fa:DaneFaKorygowanej", NS)
    assert [r.findtext("fa:NrKSeFFaKorygowanej", namespaces=NS) for r in refs] == [KSEF]
    assert not await issue.problems(None, invoice, FULL_SETTINGS)


@pytest.mark.asyncio
async def test_create_refuses_second_correction_for_the_same_month(monkeypatch):
    existing = SimpleNamespace(invoice_number="KOR/1/11/2026", status="sent")
    _patch_create(monkeypatch, issued=[existing])
    db = _SaveDb(_client())
    with pytest.raises(issue.IssueError, match="już jest") as err:
        await _create(db)
    assert err.value.status_code == 409
    assert "KOR/1/11/2026" in str(err.value)
    assert db.added == []


@pytest.mark.asyncio
async def test_create_refuses_draft_without_xml(monkeypatch):
    _patch_create(monkeypatch)
    client = _client()
    client.address = ""
    with pytest.raises(issue.IssueError, match="adresu w kartotece") as err:
        await _create(_SaveDb(client))
    assert err.value.status_code == 422


def _rebate_item(amount: str) -> dict:
    return {
        "name": f"{rebate.REBATE_LINE_PREFIX} — usługi za październik 2026",
        "quantity": "1",
        "unit_price": f"-{amount}",
        "net": f"-{amount}",
        "vat_rate": "23",
    }


def test_issued_rebate_correction_does_not_lower_turnover():
    """Obrót do progu liczy się przed rabatem: przyjęta korekta go nie zmienia."""

    net, touched = rebate.service_base(
        Decimal("-4.00"), [_rebate_item("4.00")], _terms().exclude_words
    )
    assert (net, touched) == (Decimal("0.00"), False)
    invoices = [
        _invoice("20/10/2026", _item("Usługi IT", "3", "100")),
        _invoice("KOR/1/11/2026", _rebate_item("4.00"), kind="correction"),
    ]
    assert rebate_correction.rate_weights(invoices, ()) == {"23": Decimal("300.00")}


def test_pdf_lists_corrected_invoices():
    from app.services.client_invoicing import invoice_pdf

    invoice = SimpleNamespace(
        invoice_type="KOR",
        status="draft",
        invoice_number=None,
        currency="PLN",
        client_id=11,
        series_code="KOR",
        issue_date=date(2026, 11, 22),
        period_from=date(2026, 10, 1),
        period_to=date(2026, 10, 31),
        sale_date=None,
        due_date=None,
        lines=[issue.clean_line(_rebate_item("4.00"))],
        lines_before=[],
        buyer=BUYER,
        fx_rate=None,
        fx_date=None,
        correction_reason="Rabat od obrotu",
        client_order_number=None,
        notes=None,
        ksef_number=None,
        xml=None,
        collective_correction={
            "period": "01.10.2026-31.10.2026",
            "invoices": [
                {
                    "number": "20/10/2026",
                    "issue_date": "2026-10-31",
                    "ksef_number": KSEF,
                }
            ],
        },
    )
    html = invoice_pdf.render_html(invoice, FULL_SETTINGS)
    assert "Korekta zbiorcza (art. 106j ust. 3" in html
    assert "Faktury korygowane" in html
    assert "20/10/2026" in html and "31.10.2026" in html and KSEF in html


@pytest.mark.asyncio
async def test_collective_lines_keep_rebate_name_when_edited(monkeypatch):
    """Nazwa pozycji odróżnia opust od obrotu: edycja jej nie zgubi
    (inaczej przyjęta korekta zaniżyłaby obrót do progu)."""

    _patch_create(monkeypatch)
    db = _SaveDb(_client())
    invoice = await _create(db)
    renamed = {**invoice.lines[0], "name": "Rabat od obrotu 10/2026"}
    with pytest.raises(issue.IssueError, match="Opust \\(rabat od obrotu\\)") as err:
        await issue.update(db, invoice, {"lines": [renamed]}, actor_id=7)
    assert err.value.status_code == 422
    assert invoice.lines[0]["name"].startswith(rebate.REBATE_LINE_PREFIX)

    cheaper = {**invoice.lines[0], "unit_price": "-0.50"}
    await issue.update(db, invoice, {"lines": [cheaper]}, actor_id=7)
    assert invoice.net_amount == Decimal("-0.50")
