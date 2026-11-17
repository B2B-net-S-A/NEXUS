"""Szablon 4 Symfonii FK (K3b) — plik z fabrykowanych faktur, bez bazy.

Układ (kolejność pól, CRLF, Windows-1250, kropka w kwotach, tabulatory) jest
ten z próbek od Finansów z 17.11.2026; dane w testach są zmyślone.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

import pytest

from app.models.finance_ledger import FinanceCounterparty
from app.services.ledger import exports
from app.services.ledger.export_file import (
    DEFAULT_FORMAT,
    FORMATS,
    ExportInvoice,
    ExportLine,
    SymfoniaFkDocuments,
    SymfoniaFormatError,
)

FORMAT = SymfoniaFkDocuments()


def _invoice(**changes) -> ExportInvoice:
    values = {
        "symbol": "FVS",
        "purchase": False,
        "number": "7/6/2026",
        "issue_date": date(2026, 6, 8),
        "sale_date": date(2026, 5, 31),
        "register_date": date(2026, 6, 8),
        "period_date": date(2026, 5, 31),
        "due_date": date(2026, 7, 8),
        "net": Decimal("1000.00"),
        "vat": Decimal("230.00"),
        "gross": Decimal("1230.00"),
        "vat_rate": "23",
        "ksef_date": date(2026, 6, 8),
        "party_street": "ul. Łąkowa 1",
        "party_postal": "00-001",
        "party_city": "Warszawa",
        "party_country": "PL",
    }
    values.update(changes)
    return ExportInvoice(**values)


def _line(invoice: ExportInvoice, **changes) -> ExportLine:
    values = {
        "journal_no": 1,
        "number": invoice.number,
        "doc_type": "FVS",
        "doc_date": invoice.issue_date,
        "op_date": invoice.register_date,
        "document_description": "Usługi testowe",
        "line_no": 1,
        "account": "200-2-77",
        "debit": Decimal("1230.00"),
        "credit": None,
        "description": "",
        "mpk": None,
        "counterparty": "Firma Testowa Sp. z o.o.",
        "tax_id": "1234567890",
        "symfonia_id": "77",
        "currency": "PLN",
        "amount_cur": None,
        "fx_rate": None,
        "fx_date": None,
        "reverses": None,
        "ksef_number": "1234567890-20260608-AAAAAA000001-01",
        "invoice": invoice,
    }
    values.update(changes)
    return ExportLine(**values)


def _sale_lines(invoice: Optional[ExportInvoice] = None) -> list[ExportLine]:
    invoice = invoice or _invoice()
    return [
        _line(invoice),
        _line(
            invoice,
            line_no=2,
            account="701-1-1",
            debit=None,
            credit=Decimal("1000.00"),
        ),
        _line(invoice, line_no=3, account="222", debit=None, credit=Decimal("230.00")),
    ]


def _text(content: bytes) -> str:
    return content.decode("cp1250")


def _tabs(*blocks: str) -> str:
    """Oczekiwany tekst pisany z wcięciem 4 spacjami → tabulatory, CRLF."""

    joined = "\n".join(block.strip("\n") for block in blocks)
    return joined.replace("    ", "\t").replace("\n", "\r\n") + "\r\n"


INFO = """
INFO{
    Nazwa programu =Sage Symfonia Finanse i Księgowość
    Wersja szablonu =4
}
"""

DOMESTIC_SALE = """
Dokument{
    rodzaj_dok =sprzedaży
    KsefNumber =1234567890-20260608-AAAAAA000001-01
    KSeFDate =2026-06-08
    dozaplaty =1230.00
    wdozaplaty =1230.00
    kod =7/6/2026
    symbol FK =FVS
    seria =sFVS
    nazwa =Faktura
    data =2026-06-08
    datasp =2026-05-31
    dataWystawieniaObca =2026-06-08
    dataWystawienia =2026-06-08
    dataZakupu =2026-05-31
    dataSprzedazy =2026-05-31
    kodKH =
    khid =
    khnazwa =Firma Testowa Sp. z o.o.
    khulica =ul. Łąkowa 1
    khmiasto =Warszawa
    khkodpocz =00-001
    khnip =1234567890
    khKrajKod =PL
    khKrajNazwa =Polska
    wplaty =0.000000000000
    rabat =0.000000000000
    plattypi =131
    forma_platnosci =przelew
    rejestr_platnosci =BANK
    plattermin =2026-07-08
    netto =1000.00
    vat =230.00
    typ_dk =FVS
    waluta =
    kurs =1.00
    schemat =SP
    walnetto =1000.00
    walbrutto =1230.00
    wartprzychod =1000.00
    kursdoch =1.00
    rejestr_vat =Sprzedaż
    typ_rejestru_vat =1
    Dane nabywcy{
        khid =
        fk_ident =77
        khnazwa =Firma Testowa Sp. z o.o.
        khulica =ul. Łąkowa 1
        khmiasto =Warszawa
        khkodpocz =00-001
        khnip =1234567890
        khKrajKod =PL
        khKrajNazwa =Polska
    }
    kwota =1230.00
    FK nazwa =7/6/2026
    opis FK =Usługi testowe
    opis =Usługi testowe
    datarej =2026-06-08
    datawpl =2026-06-08
    Rejestr{
        Skrot =Sprzedaż
        okres =2026-05-31
        Rodzaj =1
        stawka =23
        brutto =1230.00
        netto =1000.00
        vat =230.00
    }
    Zapis{
        strona =WN
        konto =200-2-77
        kwota =1230.00
    }
    Zapis{
        strona =MA
        konto =701-1-1
        kwota =1000.00
    }
    Zapis{
        strona =MA
        konto =222
        kwota =230.00
    }
    Transakcja{
        IdDlaRozliczen =-1
        termin =2026-07-08
    }
}
"""


def test_domestic_sale_block_matches_sample_layout():
    content = FORMAT.render(_sale_lines())
    assert _text(content) == _tabs(INFO, DOMESTIC_SALE)


def test_file_is_windows_1250_with_crlf_only_and_closed_with_brace():
    content = FORMAT.render(_sale_lines())
    assert content.startswith(b"INFO{\r\n")
    assert content.endswith(b"}\r\n")
    # Bez BOM-u, bez gołego LF; „ł” to jeden bajt 0xB3 (UTF-8 dałby dwa).
    assert not content.startswith(b"\xef\xbb\xbf")
    assert content.count(b"\n") == content.count(b"\r\n")
    assert "Łąkowa".encode("cp1250") in content
    assert "Łąkowa".encode("utf-8") not in content


def test_eu_service_sale_has_register_flags_and_no_vat_rate():
    invoice = _invoice(
        symbol="WDT",
        number="9/6/2026/UE",
        net=Decimal("2500.00"),
        vat=Decimal("0.00"),
        gross=Decimal("2500.00"),
        vat_rate="-2",
        party_country="FI",
        party_city="Helsinki",
        party_postal="00020",
    )
    lines = [
        _line(
            invoice,
            doc_type="WDT",
            account="202-2-10",
            debit=Decimal("2500.00"),
            tax_id="FI12345678",
            symfonia_id="10",
        ),
        _line(
            invoice,
            doc_type="WDT",
            line_no=2,
            account="701-10-1",
            debit=None,
            credit=Decimal("2500.00"),
            tax_id="FI12345678",
            symfonia_id="10",
        ),
    ]
    text = _text(FORMAT.render(lines))
    expected_fragments = [
        "\tkod =9/6/2026/UE\r\n\tmppFlags =0\r\n\tJPK_V7 =\r\n\tsymbol FK =WDT\r\n",
        "\tseria =sWDT\r\n",
        "\tkhnip =FI12345678\r\n\tkhKrajKod =FI\r\n\tkhKrajNazwa =Finlandia\r\n",
        "\trejestr_vat =Świadczenie usług poza krajem\r\n\ttyp_rejestru_vat =1\r\n",
        "\t\tstawka =-2\r\n\t\tbrutto =2500.00\r\n\t\tnetto =2500.00\r\n\t\tvat =0.00\r\n"
        "\t\tUE =1\r\n\t\tusluga =1\r\n\t\tJPK_V7 =\r\n\t}\r\n",
    ]
    for fragment in expected_fragments:
        assert fragment in text, fragment


def test_purchase_correction_has_negative_amounts_on_original_sides():
    invoice = _invoice(
        symbol="FKZ",
        purchase=True,
        number="FK 3/2026",
        issue_date=date(2026, 10, 2),
        sale_date=date(2026, 10, 2),
        register_date=date(2026, 10, 2),
        period_date=date(2026, 10, 2),
        due_date=date(2026, 10, 2),
        net=Decimal("-4000.00"),
        vat=Decimal("-920.00"),
        gross=Decimal("-4920.00"),
        negative=True,
        ksef_date=None,
        corrects_number="1/10/2026",
        settlement_account="201-2-1926",
        payment_account="61109010140000071219812874",
    )
    # W NEXUSIE korekta in minus ma strony zamienione i kwoty dodatnie.
    common = {"doc_type": "FVZ", "ksef_number": None}
    lines = [
        _line(
            invoice,
            account="402-215",
            debit=None,
            credit=Decimal("4000.00"),
            **common,
        ),
        _line(
            invoice,
            line_no=2,
            account="201-2-1926",
            debit=Decimal("4920.00"),
            **common,
        ),
        _line(
            invoice,
            line_no=3,
            account="221",
            debit=None,
            credit=Decimal("920.00"),
            **common,
        ),
    ]
    text = _text(FORMAT.render(lines))
    expected = _tabs(
        """
Dokument{
    rodzaj_dok =zakupu
    KsefNumber =
    KSeFDate =2026-10-02
    Dokument korygowany{
        kod =1/10/2026
    }
    Dokument nadrzędny{
        kod =1/10/2026
    }
    opis =
    NazwaKor =1/10/2026
    DataKor =2026-10-02
    DataObcyKor =2026-10-02
    dozaplaty =0.00
    wdozaplaty =0.00
    kod_obcy =FK 3/2026
    symbol FK =FKZ
    seria =sFKZ
    nazwa =Faktura korygująca zakupu
"""
    )
    # Początek bloku (po INFO) — kolejność pól korekty zakupu.
    assert _tabs(INFO).rstrip("\r\n") in text
    body = text[len(_tabs(INFO)) :]
    assert body.startswith(expected.rstrip("\r\n"))
    tail = _tabs(
        """
    typ_dk =FKZ
    wartoscsp =4000.00
    waluta =
    kurs =1.00
    schemat =ZK
    walnetto =4000.00
    walbrutto =4920.00
    wartprzychod =0.00
    kursdoch =1.00
    data_obcy =2026-10-02
    rejestr_vat =Korekta Zakupu
    typ_rejestru_vat =0
"""
    )
    assert tail.rstrip("\r\n") in body
    register = _tabs(
        """
    Rejestr{
        Skrot =Korekta Zakupu
        okres =2026-10-02
        Rodzaj =2000
        stawka =23
        brutto =-4920.00
        netto =-4000.00
        vat =-920.00
        ABC =1
    }
    Zapis{
        strona =WN
        konto =402-215
        kwota =-4000.00
        pozycja =0
    }
    Zapis{
        strona =MA
        konto =201-2-1926
        kwota =-4920.00
        pozycja =0
        IdDlaRozliczen =1
    }
    Zapis{
        strona =WN
        konto =221
        kwota =-920.00
        pozycja =0
    }
    Transakcja{
        IdDlaRozliczen =1
        termin =2026-10-02
        rachunek =61 1090 1014 0000 0712 1981 2874
    }
}
"""
    )
    assert body.endswith(register)


def test_several_documents_follow_each_other_in_one_info_block():
    second = _invoice(number="8/6/2026")
    lines = [
        *_sale_lines(),
        *[_line_with(line, journal_no=2) for line in _sale_lines(second)],
    ]
    text = _text(FORMAT.render(lines))
    assert text.count("INFO{") == 1
    assert text.count("\r\nDokument{\r\n") == 2
    assert text.index("kod =7/6/2026") < text.index("kod =8/6/2026")


def _line_with(line: ExportLine, **changes) -> ExportLine:
    values = {name: getattr(line, name) for name in line.__dataclass_fields__}
    values.update(changes)
    return ExportLine(**values)


def test_text_is_one_line_and_encodable():
    lines = [
        _line_with(
            line,
            counterparty="Ala\r\n}\nDokument{ Åbo 株式会社",
            document_description="Opis\twiększy",
        )
        for line in _sale_lines()
    ]
    content = FORMAT.render(lines)
    text = _text(content)
    # Nowa linia w nazwie nie zamyka bloku ani nie otwiera następnego.
    assert "\tkhnazwa =Ala } Dokument{ Abo ????\r\n" in text
    assert text.split("\r\n").count("Dokument{") == 1  # jedna linia otwierająca
    assert "\topis =Opis większy\r\n" in text
    assert content.count(b"\r\n") == text.count("\r\n")


def test_foreign_currency_and_unknown_symbol_are_refused_with_the_number():
    foreign = _invoice(currency="EUR")
    other = _invoice(symbol="FVZ", number="Z/1")
    with pytest.raises(SymfoniaFormatError) as caught:
        FORMAT.render(
            [
                _line_with(_sale_lines(foreign)[0], journal_no=1),
                _line_with(_sale_lines(other)[0], journal_no=2),
            ]
        )
    message = str(caught.value)
    assert "7/6/2026" in message and "EUR" in message
    assert "Z/1" in message and "FVZ" in message and "FVS, WDT, FKZ" in message
    assert "2 dok." in message


def test_non_invoice_and_unknown_rate_are_refused():
    pk = _line_with(
        _sale_lines()[0], doc_type="PK", invoice=None, number="PK 1/06/2026"
    )
    with pytest.raises(SymfoniaFormatError, match="to nie faktura"):
        FORMAT.render([pk])
    problem = _line_with(pk, invoice_problem="faktura bez kwoty brutto")
    with pytest.raises(SymfoniaFormatError, match="faktura bez kwoty brutto"):
        FORMAT.render([problem])
    mixed = _invoice(vat_rate=None)
    with pytest.raises(SymfoniaFormatError, match="stawka VAT"):
        FORMAT.render(_sale_lines(mixed))


def test_unknown_country_is_refused():
    with pytest.raises(SymfoniaFormatError, match="kraj kontrahenta"):
        FORMAT.render(_sale_lines(_invoice(party_country="ZZ")))


def test_line_without_amount_is_refused():
    lines = _sale_lines()
    lines[1] = _line_with(lines[1], credit=None)
    with pytest.raises(SymfoniaFormatError, match="bez kwoty"):
        FORMAT.render(lines)


def test_format_is_registered_next_to_the_neutral_ones():
    assert FORMATS[FORMAT.key] is not None
    assert set(FORMATS) == {"neutral_xlsx", "neutral_csv", "symfonia_fk_txt4"}
    assert DEFAULT_FORMAT == "neutral_xlsx"
    assert FORMAT.extension == "txt"
    assert FORMAT.media_type == "text/plain; charset=windows-1250"


# ── Dane faktury z NEXUSA (bez bazy: atrapy wierszy) ────────────────────────


def _party(id_type: str = "nip", country: str = "PL") -> FinanceCounterparty:
    return FinanceCounterparty(
        id=5,
        id_type=id_type,
        id_value="1234567890",
        name="Odbiorca",
        street="ul. Testowa 2",
        postal_code="00-950",
        city="Łódź",
        country=country,
    )


def _sales(**changes) -> SimpleNamespace:
    values = {
        "invoice_kind": "original",
        "invoice_number": "3/6/2026",
        "issue_date": date(2026, 6, 8),
        "sale_date": date(2026, 5, 31),
        "due_date": None,
        "net_amount": Decimal("1000.00"),
        "vat_amount": Decimal("230.00"),
        "gross_amount": Decimal("1230.00"),
        "currency": "PLN",
        "ksef_acquired_at": datetime(2026, 6, 8, 22, 30, tzinfo=timezone.utc),
        "corrected_invoice_number": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_sales_invoice_picks_symbol_register_and_dates():
    domestic = exports.sales_invoice(_sales(), _party())
    assert (domestic.symbol, domestic.vat_rate, domestic.negative) == (
        "FVS",
        "23",
        False,
    )
    assert domestic.period_date == date(2026, 5, 31)  # okres = data sprzedaży
    assert domestic.register_date == date(2026, 6, 8)  # rejestr = wystawienie
    assert domestic.due_date == date(2026, 6, 8)  # brak terminu = wystawienie
    # 22:30 UTC to już 9.06 w Warszawie — data KSeF to dzień firmy.
    assert domestic.ksef_date == date(2026, 6, 9)
    assert (domestic.party_city, domestic.party_country) == ("Łódź", "PL")

    eu = exports.sales_invoice(
        _sales(vat_amount=Decimal("0"), gross_amount=Decimal("1000.00")),
        _party("vat_eu", "FI"),
    )
    assert (eu.symbol, eu.vat_rate) == ("WDT", "-2")
    # Nabywca z UE z VAT na fakturze — szablon 4 tego nie opisuje.
    assert exports.sales_invoice(_sales(), _party("vat_eu", "FI")).vat_rate is None


def test_sales_correction_is_fks_and_negative_amounts_flag_the_sign():
    correction = exports.sales_invoice(
        _sales(
            invoice_kind="correction",
            net_amount=Decimal("-100.00"),
            vat_amount=Decimal("-23.00"),
            gross_amount=Decimal("-123.00"),
            corrected_invoice_number="2/6/2026",
        ),
        _party(),
    )
    assert (correction.symbol, correction.negative) == ("FKS", True)
    assert correction.corrects_number == "2/6/2026"
    assert correction.vat_rate == "23"


def test_purchase_invoice_from_queue_row_and_decree():
    entry = SimpleNamespace(
        due_date=None,
        decree={
            "doc_type": "FKZ",
            "positions": [
                {"kind": "cost", "account": "402-1"},
                {"kind": "counterparty", "account": "201-2-9"},
            ],
        },
    )
    row = SimpleNamespace(
        gross_amount=Decimal("-123.00"),
        vat_amount=Decimal("-23.00"),
        net_amount=Decimal("-100.00"),
        issue_date=date(2026, 10, 2),
        invoice_number="FK 1/2026",
        source_due=date(2026, 10, 30),
        currency="PLN",
    )
    doc = SimpleNamespace(
        op_date=date(2026, 10, 5), doc_date=date(2026, 10, 2), number="FK 1/2026"
    )
    invoice = exports.purchase_invoice(entry, row, doc, _party())
    assert isinstance(invoice, ExportInvoice)
    assert (invoice.symbol, invoice.purchase, invoice.negative) == ("FKZ", True, True)
    assert invoice.settlement_account == "201-2-9"
    assert invoice.register_date == date(2026, 10, 5)  # data wpływu
    # NEXUS nie czyta XML-a kosztów: data sprzedaży = data wystawienia.
    assert invoice.sale_date == date(2026, 10, 2)
    assert invoice.due_date == date(2026, 10, 30)
    assert invoice.corrects_number is None and invoice.payment_account is None

    no_amount = SimpleNamespace(**{**row.__dict__, "gross_amount": None})
    assert exports.purchase_invoice(entry, no_amount, doc, None) == (
        "faktura bez kwoty brutto"
    )
    plain = SimpleNamespace(due_date=None, decree={})
    assert exports.purchase_invoice(plain, row, doc, None).symbol == "FVZ"
