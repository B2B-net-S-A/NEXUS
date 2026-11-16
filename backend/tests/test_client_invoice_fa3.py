"""FA(3) z faktury wystawianej w NEXUSIE (E4): budowa XML-a i odczyt tym samym parserem.

„Round-trip”: ``fa3_build.build_xml`` → ``hr/ksef/fa.parse_invoice`` i
``client_invoicing/fa_sales.parse_sales_invoice`` (parsery, które czytają
prawdziwe faktury z KSeF). Przypadki: kraj 23%, nabywca z UE (np., odwrotne
obciążenie), EUR z kursem NBP i VAT w złotych, korekta (różnice), zaliczkowa,
zwolnienie z podstawą, odmowy przy niekompletnym szkicu. XSD FA(3) nie ma
w repo — kolejność elementów sprawdza ``test_fa_children_follow_schema_order``.
Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from lxml import etree

from app.services.client_invoicing import fa3_build, fa_sales, invoice_pdf
from app.services.client_invoicing.fa3_build import (
    BankAccount,
    CorrectedInvoice,
    InvoiceBuildError,
    InvoiceDocument,
    Party,
    buyer_id,
)
from app.services.hr.ksef import fa

SELLER_NIP = "9876543210"
SELLER = Party(
    name="Spółka Testowa sp. z o.o.", address_l1="ul. Testowa 10, 00-001 Warszawa"
)
BUYER = Party(name="Bank Testowy S.A.", address_l1="ul. Przykładowa 5, 00-002 Warszawa")
EU_BUYER = Party(
    name="Pankki Testi Oyj", address_l1="Testikatu 1, Helsinki", country="FI"
)
CREATED = datetime(2026, 11, 30, 9, 0, tzinfo=timezone.utc)

#: Kolejność elementów ``Fa`` ze schematu FA(3) (tylko te, które budujemy).
FA_ORDER = (
    "KodWaluty", "P_1", "P_1M", "P_2", "P_6", "OkresFa",
    "P_13_1", "P_14_1", "P_14_1W", "P_13_2", "P_14_2", "P_14_2W",
    "P_13_3", "P_14_3", "P_14_3W", "P_13_6_1", "P_13_6_3", "P_13_7",
    "P_13_8", "P_13_9", "P_15", "KursWalutyZ", "Adnotacje", "RodzajFaktury",
    "PrzyczynaKorekty", "DaneFaKorygowanej", "DodatkowyOpis", "FaWiersz",
    "Platnosc", "WarunkiTransakcji", "Zamowienie",
)  # fmt: skip


def _line(name: str, quantity: str, price: str, rate: str = "23") -> dict:
    return {
        "name": name,
        "quantity": quantity,
        "unit": "MD",
        "unit_price": price,
        "vat_rate": rate,
    }


def _doc(**overrides) -> InvoiceDocument:
    data = dict(
        invoice_type="VAT",
        number="113/11/2026",
        issue_date=date(2026, 11, 30),
        currency="PLN",
        seller_nip=SELLER_NIP,
        seller=SELLER,
        buyer=BUYER,
        buyer_ident=buyer_id("1111111111"),
        lines=[
            _line(
                "Usługi informatyczne — Jan Przykładowy — październik 2026",
                "21",
                "1200",
            ),
            _line(
                "Usługi informatyczne — Adam Testowy — październik 2026", "19.5", "1150"
            ),
        ],
        period_from=date(2026, 10, 1),
        period_to=date(2026, 10, 31),
        due_date=date(2026, 12, 14),
        account=BankAccount(
            number="PL61109010140000071219812874", bank="Bank Przykładowy"
        ),
        client_order_number="ZAM/2026/118",
        created_at=CREATED,
    )
    data.update(overrides)
    return InvoiceDocument(**data)


def _fa(xml: bytes):
    return etree.fromstring(xml).find("{*}Fa")


def test_domestic_23_round_trip() -> None:
    xml = fa3_build.build_xml(_doc())
    parsed = fa.parse_invoice(xml)
    assert parsed.form == "FA(3)"
    assert parsed.seller_nip == SELLER_NIP
    assert parsed.buyer_nip == "1111111111"
    assert parsed.invoice_number == "113/11/2026"
    assert parsed.invoice_type == "VAT"
    assert parsed.kind == "original"
    # 21 × 1200 + 19,5 × 1150 = 25 200 + 22 425
    assert parsed.net_amount == Decimal("47625.00")
    assert parsed.vat_amount == Decimal("10953.75")
    assert parsed.gross_amount == Decimal("58578.75")
    assert parsed.period == (2026, 10)
    assert [item["net"] for item in parsed.items] == ["25200.00", "22425.00"]
    assert {item["vat_rate"] for item in parsed.items} == {"23"}

    sales = fa_sales.parse_sales_invoice(xml)
    assert sales.buyer_name == "Bank Testowy S.A."
    assert sales.due_date == date(2026, 12, 14)
    assert sales.order_refs == ["ZAM/2026/118"]
    assert sales.period_source == "invoice"

    fa_node = _fa(xml)
    assert fa_node.findtext("{*}Adnotacje/{*}P_18") == "2"
    assert fa_node.findtext("{*}Adnotacje/{*}Zwolnienie/{*}P_19N") == "1"
    assert fa_node.findtext("{*}Platnosc/{*}FormaPlatnosci") == "6"
    assert (
        fa_node.findtext("{*}Platnosc/{*}RachunekBankowy/{*}NrRB")
        == "PL61109010140000071219812874"
    )
    header = etree.fromstring(xml).find("{*}Naglowek/{*}KodFormularza")
    assert header.get("kodSystemowy") == "FA (3)"
    assert header.get("wersjaSchemy") == "1-0E"
    podmiot2 = etree.fromstring(xml).find("{*}Podmiot2")
    assert podmiot2.findtext("{*}JST") == "2" and podmiot2.findtext("{*}GV") == "2"


def test_eu_buyer_reverse_charge_round_trip() -> None:
    xml = fa3_build.build_xml(
        _doc(
            number="290/11/2026/UE",
            buyer=EU_BUYER,
            buyer_ident=buyer_id("FI12345678"),
            lines=[
                _line(
                    "IT services — Jan Przykładowy — October 2026", "20", "300", "np II"
                )
            ],
            currency="EUR",
            fx_rate=Decimal("4.2512"),
        )
    )
    ident = etree.fromstring(xml).find("{*}Podmiot2/{*}DaneIdentyfikacyjne")
    assert ident.findtext("{*}KodUE") == "FI"
    assert ident.findtext("{*}NrVatUE") == "12345678"
    assert ident.find("{*}NIP") is None
    fa_node = _fa(xml)
    assert fa_node.findtext("{*}P_13_9") == "6000.00"
    assert fa_node.find("{*}P_14_1") is None
    assert fa_node.findtext("{*}Adnotacje/{*}P_18") == "1"
    parsed = fa_sales.parse_sales_invoice(xml)
    assert parsed.buyer_foreign_id == "FI12345678"
    assert parsed.base.net_amount == Decimal("6000.00")
    assert parsed.base.vat_amount == Decimal("0.00")
    assert parsed.base.gross_amount == Decimal("6000.00")
    assert parsed.base.currency == "EUR"
    assert parsed.base.items[0]["vat_rate"] == "np II"


def test_foreign_currency_vat_in_pln_by_nbp_rate() -> None:
    xml = fa3_build.build_xml(
        _doc(
            currency="EUR",
            fx_rate=Decimal("4.2512"),
            lines=[_line("Usługi — Jan Przykładowy", "10", "500")],
        )
    )
    fa_node = _fa(xml)
    assert fa_node.findtext("{*}KodWaluty") == "EUR"
    assert fa_node.findtext("{*}P_13_1") == "5000.00"
    assert fa_node.findtext("{*}P_14_1") == "1150.00"
    # 1150 EUR × 4,2512 = 4888,88 zł
    assert fa_node.findtext("{*}P_14_1W") == "4888.88"
    assert fa_node.findtext("{*}FaWiersz/{*}KursWaluty") == "4.2512"
    parsed = fa.parse_invoice(xml)
    assert parsed.currency == "EUR"
    assert parsed.vat_amount == Decimal("1150.00")


def test_foreign_currency_without_rate_is_refused() -> None:
    with pytest.raises(InvoiceBuildError, match="kursu NBP"):
        fa3_build.build_xml(_doc(currency="EUR", fx_rate=None))


def test_correction_differences_round_trip() -> None:
    before = [_line("Usługi — Jan Przykładowy — październik 2026", "21", "1200")]
    after = [_line("Usługi — Jan Przykładowy — październik 2026", "20", "1200")]
    xml = fa3_build.build_xml(
        _doc(
            invoice_type="KOR",
            number="KOR/1/12/2026",
            issue_date=date(2026, 12, 3),
            lines=after,
            lines_before=before,
            corrected=CorrectedInvoice(
                number="113/11/2026",
                issue_date=date(2026, 11, 30),
                ksef_number="9876543210-20261130-E40000000001-1A",
                reason="Zużycie MD po weryfikacji klienta",
            ),
        )
    )
    parsed = fa.parse_invoice(xml)
    assert parsed.kind == "correction"
    assert parsed.invoice_type == "KOR"
    assert parsed.corrected_invoice_number == "113/11/2026"
    assert parsed.corrected_ksef_number == "9876543210-20261130-E40000000001-1A"
    assert parsed.correction_reason == "Zużycie MD po weryfikacji klienta"
    assert parsed.net_amount == Decimal("-1200.00")
    assert parsed.vat_amount == Decimal("-276.00")
    assert parsed.gross_amount == Decimal("-1476.00")
    assert [item.get("before_correction") for item in parsed.items] == [True, None]
    data = _fa(xml).find("{*}DaneFaKorygowanej")
    assert data.findtext("{*}NrKSeF") == "1"


def test_correction_needs_corrected_invoice() -> None:
    with pytest.raises(InvoiceBuildError, match="korygowaną"):
        fa3_build.build_xml(_doc(invoice_type="KOR", lines_before=[]))


def test_advance_invoice_carries_order() -> None:
    xml = fa3_build.build_xml(
        _doc(
            invoice_type="ZAL",
            number="ZAL/1/11/2026",
            period_from=None,
            period_to=None,
            sale_date=date(2026, 11, 25),
            lines=[_line("Zaliczka na wdrożenie systemu", "1", "10000")],
        )
    )
    fa_node = _fa(xml)
    assert fa_node.findtext("{*}RodzajFaktury") == "ZAL"
    assert fa_node.findtext("{*}P_6") == "2026-11-25"
    assert fa_node.find("{*}FaWiersz") is None
    order = fa_node.find("{*}Zamowienie")
    assert order.findtext("{*}WartoscZamowienia") == "12300.00"
    assert order.findtext("{*}ZamowienieWiersz/{*}P_11NettoZ") == "10000.00"
    assert order.findtext("{*}ZamowienieWiersz/{*}P_11VatZ") == "2300.00"
    parsed = fa.parse_invoice(xml)
    assert parsed.invoice_type == "ZAL"
    assert parsed.gross_amount == Decimal("12300.00")


def test_exemption_needs_basis() -> None:
    lines = [_line("Szkolenie", "1", "1000", "zw")]
    with pytest.raises(InvoiceBuildError, match="podstawy zwolnienia"):
        fa3_build.build_xml(_doc(lines=lines))
    xml = fa3_build.build_xml(
        _doc(lines=lines, exemption_basis="art. 43 ust. 1 pkt 29 lit. c ustawy o VAT")
    )
    exemption = _fa(xml).find("{*}Adnotacje/{*}Zwolnienie")
    assert exemption.findtext("{*}P_19") == "1"
    assert exemption.findtext("{*}P_19A").startswith("art. 43")
    assert _fa(xml).findtext("{*}P_13_7") == "1000.00"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"lines": [_line("Bez ceny", "1", "")]}, "nie ma ilości, ceny"),
        ({"seller": Party(name="", address_l1="")}, "dane sprzedawcy"),
        ({"buyer": Party(name="Nabywca", address_l1="")}, "adres nabywcy"),
        ({"lines": []}, "nie ma pozycji"),
        ({"number": ""}, "nie ma numeru"),
    ],
)
def test_incomplete_draft_is_refused(overrides, message) -> None:
    with pytest.raises(InvoiceBuildError, match=message):
        fa3_build.build_xml(_doc(**overrides))


def test_fa_children_follow_schema_order() -> None:
    for doc in (
        _doc(),
        _doc(currency="EUR", fx_rate=Decimal("4.25"), notes="Uwagi do faktury"),
        _doc(
            invoice_type="KOR",
            lines_before=[_line("A", "2", "10")],
            lines=[_line("A", "1", "10")],
            corrected=CorrectedInvoice("1/11/2026", date(2026, 11, 1), None, "Rabat"),
        ),
        _doc(
            invoice_type="ZAL",
            sale_date=date(2026, 11, 2),
            currency="USD",
            fx_rate=Decimal("3.9"),
        ),
    ):
        names = [etree.QName(node).localname for node in _fa(fa3_build.build_xml(doc))]
        positions = [FA_ORDER.index(name) for name in names]
        assert positions == sorted(positions), names


def test_totals_round_vat_per_rate_sum() -> None:
    result = fa3_build.totals(
        [_line("A", "1", "0.05"), _line("B", "1", "0.05"), _line("C", "3", "10", "8")]
    )
    rates = {item.rate.code: item for item in result.rates}
    # VAT od sumy w stawce: 0,10 × 23% = 0,02 (od pozycji osobno wyszłoby 0,02 + 0,02)
    assert rates["23"].vat == Decimal("0.02")
    assert rates["8"].vat == Decimal("2.40")
    assert result.gross == Decimal("32.52")


@pytest.mark.parametrize(
    ("raw", "kind", "country", "number"),
    [
        ("1111111111", "nip", None, None),
        ("PL1111111111", "nip", None, None),
        ("FI12345678", "eu", "FI", "12345678"),
        ("GR123456789", "eu", "EL", "123456789"),
        ("FR1A123456789", "eu", "FR", "1A123456789"),
        ("GB123456789", "other", "GB", "123456789"),
        ("", "none", None, None),
    ],
)
def test_buyer_identifier_kinds(raw, kind, country, number) -> None:
    ident = buyer_id(raw)
    assert ident.kind == kind
    if country:
        assert (ident.country, ident.number) == (country, number)


def test_verification_qr_url() -> None:
    xml = b"<Faktura/>"
    url = invoice_pdf.qr_url("prod", SELLER_NIP, date(2026, 11, 30), xml)
    assert url.startswith("https://qr.ksef.mf.gov.pl/invoice/9876543210/30-11-2026/")
    digest = url.rsplit("/", 1)[1]
    assert "=" not in digest and "+" not in digest and "/" not in digest
    assert invoice_pdf.qr_url("test", SELLER_NIP, date(2026, 11, 30), xml).startswith(
        "https://qr-test.ksef.mf.gov.pl/invoice/"
    )


def _issued(**overrides):
    from app.models.client_issued_invoice import ClientIssuedInvoice

    data = dict(
        id=7,
        client_id=1,
        invoice_type="VAT",
        series_code="PL",
        status="draft",
        currency="PLN",
        issue_date=date(2026, 11, 30),
        period_from=date(2026, 10, 1),
        period_to=date(2026, 10, 31),
        due_date=date(2026, 12, 14),
        buyer={
            "name": "Bank Testowy S.A.",
            "number": "1111111111",
            "address_l1": "ul. Przykładowa 5",
        },
        lines=[{**_line("Usługi — Jan Przykładowy", "21", "1200"), "net": "25200.00"}],
        lines_before=[],
        client_order_number="ZAM/2026/118",
    )
    data.update(overrides)
    return ClientIssuedInvoice(**data)


PDF_SETTINGS = {
    "seller": {
        "name": "Spółka Testowa sp. z o.o.",
        "nip": SELLER_NIP,
        "address_l1": "ul. Testowa 10",
        "address_l2": "",
        "issue_place": "Warszawa",
    },
    "accounts": {
        "PLN": {"number": "PL61109010140000071219812874", "bank": "", "swift": ""}
    },
    "exemption_basis": "",
}


def test_pdf_of_draft_has_no_qr_and_says_draft() -> None:
    html = invoice_pdf.render_html(_issued(), PDF_SETTINGS)
    assert "SZKIC — dokument nie jest fakturą" in html
    assert "svg+xml" not in html
    assert "NIP 1111111111" in html
    assert "ZAM/2026/118" in html


def test_pdf_of_accepted_invoice_has_ksef_number_and_qr() -> None:
    xml = fa3_build.build_xml(_doc())
    html = invoice_pdf.render_html(
        _issued(
            status="accepted",
            invoice_number="113/11/2026",
            ksef_number="9876543210-20261130-E40000000001-1A",
            ksef_environment="test",
            xml=xml.decode("utf-8"),
        ),
        PDF_SETTINGS,
    )
    assert "SZKIC" not in html
    assert "9876543210-20261130-E40000000001-1A" in html
    assert "data:image/svg+xml" in html
    assert "nr 113/11/2026" in html
