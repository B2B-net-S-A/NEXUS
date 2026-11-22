"""Szablon 4 Symfonii FK: zakup wg próbek z 18.11.2026 (FVZP samochód, IU import usług).

Układ (kolejność pól, znaki kwot, rejestry, ``AtrybutWaluta``, zapisy
równoległe „5”) jest ten z próbek eBI24 od głównej księgowej; dane w testach
są zmyślone. Próbki leżą u Artura, nie w repo — porównanie bajt w bajt
zrobione lokalnie (opis PR-a).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.finance_ledger import FinanceCounterparty
from app.services.ledger import exports
from app.services.ledger.export_file import (
    ExportInvoice,
    ExportLine,
    ExportRegister,
    SymfoniaFkDocuments,
    SymfoniaFormatError,
)

FORMAT = SymfoniaFkDocuments()


def _tabs(*blocks: str) -> str:
    joined = "\n".join(block.strip("\n") for block in blocks)
    return joined.replace("    ", "\t").replace("\n", "\r\n") + "\r\n"


INFO = """
INFO{
    Nazwa programu =Sage Symfonia Finanse i Księgowość
    Wersja szablonu =4
}
"""


def _car_invoice(**changes) -> ExportInvoice:
    values = {
        "symbol": "FVZP",
        "purchase": True,
        "number": "LS/10/2026",
        "issue_date": date(2026, 10, 6),
        "sale_date": date(2026, 10, 31),
        "register_date": date(2026, 10, 7),
        "period_date": date(2026, 10, 7),
        "due_date": date(2026, 10, 20),
        "net": Decimal("1000.02"),
        "vat": Decimal("230.01"),
        "gross": Decimal("1230.03"),
        "vat_rate": "23",
        "ksef_date": date(2026, 10, 6),
        "party_street": "ul. Leasingowa 1",
        "party_postal": "00-001",
        "party_city": "Warszawa",
        "party_country": "PL",
        "payment_account": "PL61109010140000071219812874",
        "registers": (
            ExportRegister("Zakup", "23", Decimal("500.01"), Decimal("115.00"),
                           Decimal("615.01")),
            ExportRegister("Rejestr NP VAT", "23", Decimal("500.01"),
                           Decimal("115.01"), Decimal("615.02")),
        ),
        "line_kinds": {1: "cost", 2: "counterparty", 3: "vat", 4: "allocation",
                       5: "allocation_offset"},
    }  # fmt: skip
    values.update(changes)
    return ExportInvoice(**values)


def _line(invoice: ExportInvoice, line_no: int, account: str, debit, credit, **more):
    values = {
        "journal_no": 1,
        "number": invoice.number,
        "doc_type": "FVZ",
        "doc_date": invoice.issue_date,
        "op_date": invoice.register_date,
        "document_description": "Leasing samochodu",
        "line_no": line_no,
        "account": account,
        "debit": Decimal(debit) if debit else None,
        "credit": Decimal(credit) if credit else None,
        "description": "",
        "mpk": None,
        "counterparty": "Leasing Testowy Sp. z o.o.",
        "tax_id": "1234567890",
        "symfonia_id": "77",
        "currency": "PLN",
        "amount_cur": None,
        "fx_rate": None,
        "fx_date": None,
        "reverses": None,
        "ksef_number": "1234567890-20261006-AAAAAA000001-01",
        "invoice": invoice,
    }
    values.update(more)
    return ExportLine(**values)


def _car_lines(invoice: ExportInvoice) -> list[ExportLine]:
    return [
        _line(invoice, 1, "244-3", "1115.03", None),
        _line(invoice, 2, "244-1", None, "1230.03"),
        _line(invoice, 3, "221", "115.00", None),
        _line(invoice, 4, "510-5", "1115.03", None),
        _line(invoice, 5, "490", None, "1115.03"),
    ]


CAR = """
Dokument{
    rodzaj_dok =zakupu
    KsefNumber =1234567890-20261006-AAAAAA000001-01
    KSeFDate =2026-10-06
    dozaplaty =0.00
    wdozaplaty =0.00
    kod_obcy =LS/10/2026
    symbol FK =FVZP
    seria =sFVZP
    nazwa =Faktura zakupu
    data =2026-10-06
    datasp =2026-10-31
    dataWystawieniaObca =2026-10-06
    dataWystawienia =2026-10-06
    dataZakupu =2026-10-31
    dataSprzedazy =2026-10-31
    kodKH =
    khid =
    khnazwa =Leasing Testowy Sp. z o.o.
    khulica =ul. Leasingowa 1
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
    plattermin =2026-10-20
    netto =-1000.02
    vat =-230.01
    typ_dk =FVZP
    wartoscsp =-1000.02
    waluta =
    kurs =1.00
    schemat =ZK
    walnetto =-1000.02
    walbrutto =-1230.03
    wartprzychod =0.00
    kursdoch =1.00
    data_obcy =2026-10-06
    rejestr_vat =Zakup
    typ_rejestru_vat =0
    Dane sprzedawcy{
        khid =
        khnazwa =Leasing Testowy Sp. z o.o.
        khulica =ul. Leasingowa 1
        khmiasto =Warszawa
        khkodpocz =00-001
        khnip =1234567890
        khKrajKod =PL
        khKrajNazwa =Polska
    }
    kwota =-1230.03
    FK nazwa =LS/10/2026
    opis FK =Leasing samochodu
    opis =Leasing samochodu
    datarej =2026-10-07
    datawpl =2026-10-07
    Rejestr{
        Skrot =Zakup
        okres =2026-10-07
        Rodzaj =2000
        stawka =23
        brutto =615.01
        netto =500.01
        vat =115.00
        ABC =1
    }
    Rejestr{
        Skrot =Rejestr NP VAT
        okres =2026-10-07
        Rodzaj =2000
        stawka =23
        brutto =615.02
        netto =500.01
        vat =115.01
        ABC =1
    }
    Zapis{
        strona =WN
        konto =244-3
        kwota =1115.03
        pozycja =0
    }
    Zapis{
        strona =MA
        konto =244-1
        kwota =1230.03
        pozycja =0
    }
    Zapis{
        strona =WN
        konto =221
        kwota =115.00
        pozycja =0
    }
    Zapis{
        strona =WN
        konto =510-5
        kwota =1115.03
        pozycja =1
        ZapisRownolegly =33
    }
    Zapis{
        strona =MA
        konto =490
        kwota =1115.03
        pozycja =1
        ZapisRownolegly =33
    }
    Transakcja{
        IdDlaRozliczen =-1
        termin =2026-10-20
        rachunek =PL61109010140000071219812874
    }
}
"""


def test_car_invoice_matches_the_fvzp_sample_layout() -> None:
    invoice = _car_invoice()
    assert FORMAT.render(_car_lines(invoice)).decode("cp1250") == _tabs(INFO, CAR)


def _import_invoice(**changes) -> ExportInvoice:
    values = {
        "symbol": "IU",
        "purchase": True,
        "number": "INV-42",
        "issue_date": date(2026, 10, 30),
        "sale_date": date(2026, 10, 30),
        "register_date": date(2026, 10, 30),
        "period_date": date(2026, 10, 30),
        "due_date": date(2026, 11, 6),
        "net": Decimal("1000.00"),
        "vat": Decimal("0"),
        "gross": Decimal("1000.00"),
        "vat_rate": "23",
        "currency": "EUR",
        "party_street": "1 Test Road",
        "party_postal": "",
        "party_city": "",
        "party_country": "IN",
        "payment_account": "50200000000001",
        "jpk_procedure": "BFK",
        "fx_rate": Decimal("4.2345"),
        "fx_date": date(2026, 10, 29),
        "fx_table": "211/A/NBP/2026",
        "registers": (
            ExportRegister("Import usług VAT naliczony", "23", Decimal("4234.50"),
                           Decimal("973.94"), Decimal("5208.44"), Decimal("1000.00"),
                           Decimal("230.00"), Decimal("1230.00"), service=True),
            ExportRegister("Import usług VAT należny", "23", Decimal("4234.50"),
                           Decimal("973.94"), Decimal("5208.44"), Decimal("1000.00"),
                           Decimal("230.00"), Decimal("1230.00"), output=True),
        ),
        "line_kinds": {1: "cost", 2: "counterparty", 3: "vat", 4: "vat_due",
                       5: "allocation", 6: "allocation_offset"},
    }  # fmt: skip
    values.update(changes)
    return ExportInvoice(**values)


def _import_lines(invoice: ExportInvoice) -> list[ExportLine]:
    cur = {"currency": "EUR", "fx_rate": Decimal("4.2345"), "ksef_number": None}
    return [
        _line(invoice, 1, "402-203", "4234.50", None, amount_cur=Decimal("1000.00"),
              **cur),
        _line(invoice, 2, "203-2-55", None, "4234.50", amount_cur=Decimal("1000.00"),
              **cur),
        _line(invoice, 3, "221", "973.94", None, amount_cur=Decimal("230.00"), **cur),
        _line(invoice, 4, "226", None, "973.94", amount_cur=Decimal("230.00"), **cur),
        _line(invoice, 5, "501-6-1", "4234.50", None, amount_cur=Decimal("1000.00"),
              **cur),
        _line(invoice, 6, "490", None, "4234.50", amount_cur=Decimal("1000.00"),
              **cur),
    ]  # fmt: skip


def _zapis(side: str, account: str, amount: str, cur: str, group: str, extra=""):
    return f"""
    Zapis{{
        strona ={side}
        konto ={account}
        kwota ={amount}
        wkwota ={cur}
        kurs =4.2345
        tabela =211/A/NBP/2026
        Waluta =EUR
        pozycja ={group}{extra}
    }}"""


PARALLEL = "\n        ZapisRownolegly =33"

IMPORT = (
    """
Dokument{
    rodzaj_dok =zakupu
    dozaplaty =0.00
    wdozaplaty =0.00
    kod_obcy =INV-42
    mppFlags =0
    JPK_V7 =BFK
    symbol FK =IU
    seria =sIU
    nazwa =Faktura zakupu
    data =2026-10-30
    datasp =2026-10-30
    dataWystawieniaObca =2026-10-30
    dataWystawienia =2026-10-30
    dataZakupu =2026-10-30
    dataSprzedazy =2026-10-30
    kodKH =
    khid =
    khnazwa =Leasing Testowy Sp. z o.o.
    khulica =1 Test Road
    khmiasto =
    khkodpocz =
    khnip =1234567890
    khKrajKod =IN
    khKrajNazwa =Indie
    wplaty =0.000000000000
    rabat =0.000000000000
    plattypi =131
    forma_platnosci =przelew
    rejestr_platnosci =BANK
    plattermin =2026-11-06
    netto =-1000.00
    vat =-230.00
    typ_dk =IU
    wartoscsp =-1000.00
    waluta =EUR
    tabela =211/A/NBP/2026
    kurs =4.2345
    schemat =ZK
    walnetto =-1000.00
    walbrutto =-1230.00
    wartprzychod =0.00
    kursdoch =4.2345
    data_obcy =2026-10-30
    rejestr_vat =Import usług VAT naliczony
    typ_rejestru_vat =0
    Dane sprzedawcy{
        khid =
        khnazwa =Leasing Testowy Sp. z o.o.
        khulica =1 Test Road
        khmiasto =
        khkodpocz =
        khnip =1234567890
        khKrajKod =IN
        khKrajNazwa =Indie
    }
    wkwota =5208.44
    kwota =-1230.00
    FK nazwa =INV-42
    opis FK =Leasing samochodu
    opis =Leasing samochodu
    datarej =2026-10-30
    datawpl =2026-10-30
    Rejestr{
        Skrot =Import usług VAT naliczony
        okres =2026-10-30
        Rodzaj =2000
        stawka =23
        brutto =5208.44
        netto =4234.50
        vat =973.94
        ABC =1
        UE =0
        Naliczony =1
        nettoWaluta =1000.00
        vatWaluta =230.00
        bruttoWaluta =1230.00
        usluga =1
    }
    Rejestr{
        Skrot =Import usług VAT należny
        Nazwa =Import usług VAT należny
        okres =2026-10-30
        Rodzaj =2000
        stawka =23
        brutto =5208.44
        netto =4234.50
        vat =973.94
        ABC =1
        UE =0
        Naliczony =0
        nettoWaluta =1000.00
        vatWaluta =230.00
        bruttoWaluta =1230.00
    }
    AtrybutWaluta{
        data =2026-10-29
        kurs =4.2345
        waluta =EUR
        dane =kurs VAT
    }
    AtrybutWaluta{
        data =2026-10-29
        kurs =4.2345
        waluta =EUR
        dane =kurs CIT/PIT
    }"""
    + _zapis("WN", "402-203", "4234.50", "1000.00", "1")
    + _zapis("MA", "203-2-55", "4234.50", "1000.00", "1")
    + _zapis("WN", "221", "973.94", "230.00", "2")
    + _zapis("MA", "226", "973.94", "230.00", "2")
    + _zapis("WN", "501-6-1", "4234.50", "1000.00", "1", PARALLEL)
    + _zapis("MA", "490", "4234.50", "1000.00", "1", PARALLEL)
    + """
    Transakcja{
        IdDlaRozliczen =-1
        termin =2026-11-06
        rachunek =50200000000001
    }
}
"""
)


def test_import_of_services_matches_the_iu_sample_layout() -> None:
    invoice = _import_invoice()
    text = FORMAT.render(_import_lines(invoice)).decode("cp1250")
    assert text == _tabs(INFO, IMPORT)


def test_eu_import_marks_ue_on_both_registers() -> None:
    base = _import_invoice()
    registers = tuple(
        ExportRegister(**{**item.__dict__, "eu": True}) for item in base.registers
    )
    invoice = _import_invoice(registers=registers, party_country="DE")
    text = FORMAT.render(_import_lines(invoice)).decode("cp1250")
    assert text.count("\tUE =1\r\n") == 2
    assert "khKrajNazwa =Niemcy" in text


def test_purchase_correction_flips_header_and_register_signs() -> None:
    invoice = _car_invoice(symbol="FVZ", negative=True)
    # W NEXUSIE korekta in minus ma strony zamienione i kwoty dodatnie.
    lines = [
        _line(invoice, 1, "244-3", None, "1115.03"),
        _line(invoice, 2, "244-1", "1230.03", None),
        _line(invoice, 3, "221", None, "115.00"),
    ]
    text = FORMAT.render(lines).decode("cp1250")
    assert "\tnetto =1000.02\r\n" in text  # nagłówek korekty in minus dodatni
    assert "\t\tbrutto =-615.01\r\n" in text  # rejestr ujemny
    assert "\t\tstrona =WN\r\n\t\tkonto =244-3\r\n\t\tkwota =-1115.03" in text


def test_cash_method_goes_to_jpk_attribute() -> None:
    invoice = _car_invoice(symbol="FVZ", jpk_procedure="MK")
    text = FORMAT.render(_car_lines(invoice)).decode("cp1250")
    assert "\tkod_obcy =LS/10/2026\r\n\tmppFlags =0\r\n\tJPK_V7 =MK\r\n" in text


def test_foreign_currency_without_rate_is_refused() -> None:
    invoice = _import_invoice(fx_rate=None)
    with pytest.raises(SymfoniaFormatError, match="bez kursu"):
        FORMAT.render(_import_lines(invoice))


def test_currency_invoice_from_an_old_decree_is_refused() -> None:
    invoice = _car_invoice(
        symbol="FVZ",
        registers=(),
        currency="EUR",
        fx_rate=Decimal("4.0"),
        fx_date=date(2026, 10, 5),
        line_kinds={},
    )
    with pytest.raises(SymfoniaFormatError, match="przelicz"):
        FORMAT.render(_car_lines(invoice)[:3])


def test_pln_invoice_from_an_old_decree_has_one_register_from_amounts() -> None:
    invoice = _car_invoice(symbol="FVZ", registers=(), line_kinds={})
    text = FORMAT.render(_car_lines(invoice)[:3]).decode("cp1250")
    assert text.count("\tRejestr{") == 1
    assert "\t\tSkrot =Zakup\r\n" in text and "\t\tbrutto =1230.03\r\n" in text


# ── Dane faktury z dekretu (exports.purchase_invoice) ────────────────────────


def _party() -> FinanceCounterparty:
    return FinanceCounterparty(
        id=5,
        id_type="other",
        id_value="IN000000000",
        name="Dostawca",
        street="1 Test Road",
        postal_code=None,
        city=None,
        country="IN",
    )


def test_purchase_invoice_reads_registers_jpk_and_rate_from_the_decree() -> None:
    entry = SimpleNamespace(
        due_date=None,
        decree={
            "doc_type": "IU",
            "vat_rate": "23",
            "negative": False,
            "jpk_procedure": "BFK",
            "service_date": "2026-10-28",
            "fx_rate": "4.2345",
            "fx_date": "2026-10-29",
            "fx_table": "211/A/NBP/2026",
            "positions": [
                {"kind": "cost", "account": "402-203"},
                {"kind": "counterparty", "account": "203-2-55"},
                {"kind": "vat", "account": "221"},
                {"kind": "vat_due", "account": "226"},
            ],
            "registers": [
                {"name": "Import usług VAT naliczony", "rate": "23", "net": 423450,
                 "vat": 97394, "gross": 520844, "net_cur": 100000, "vat_cur": 23000,
                 "gross_cur": 123000, "output": False, "eu": False, "service": True},
                {"name": "Import usług VAT należny", "rate": "23", "net": 423450,
                 "vat": 97394, "gross": 520844, "net_cur": 100000, "vat_cur": 23000,
                 "gross_cur": 123000, "output": True, "eu": False, "service": False},
            ],
        },
    )  # fmt: skip
    row = SimpleNamespace(
        gross_amount=Decimal("1000.00"),
        vat_amount=Decimal("0"),
        net_amount=Decimal("1000.00"),
        issue_date=date(2026, 10, 30),
        invoice_number="INV-42",
        source_due=None,
        currency="EUR",
    )
    doc = SimpleNamespace(
        op_date=date(2026, 10, 30), doc_date=date(2026, 10, 30), number="INV-42"
    )
    invoice = exports.purchase_invoice(
        entry, row, doc, _party(), payment_account="50200000000001"
    )
    assert isinstance(invoice, ExportInvoice)
    assert (invoice.symbol, invoice.vat_rate, invoice.jpk_procedure) == (
        "IU",
        "23",
        "BFK",
    )
    assert invoice.sale_date == date(2026, 10, 28)
    assert (invoice.fx_rate, invoice.fx_date, invoice.fx_table) == (
        Decimal("4.2345"),
        date(2026, 10, 29),
        "211/A/NBP/2026",
    )
    assert [item.output for item in invoice.registers] == [False, True]
    assert invoice.registers[0].net_cur == Decimal("1000.00")
    assert invoice.line_kinds == {1: "cost", 2: "counterparty", 3: "vat", 4: "vat_due"}
    assert invoice.payment_account == "50200000000001"
    assert invoice.party_country == "IN"


def test_car_correction_from_compute_renders_both_correction_registers() -> None:
    """compute → FKZ → plik: korekta z opisem idzie układem zakupu, nie starym FKZ."""

    from datetime import datetime, timezone

    from app.services.finance_ledger import posting
    from app.services.finance_ledger import posting_options as options

    plan = {
        number: posting.AccountView(number, number, kind, True)
        for number, kind in (
            ("402-203", "cost"), ("221", "vat"), ("510-5", "other"), ("490", "other"),
        )
    }  # fmt: skip
    entries = {k: options.PlanEntry(v.number, v.kind, True) for k, v in plan.items()}
    decree = posting.compute(
        posting.DecreeInput(
            category="contractor",
            counterparty_id=7,
            counterparty_name="Dostawca",
            counterparty_account=None,
            counterparty_symfonia_id="55",
            currency="PLN",
            net=Decimal("-100.00"),
            vat=Decimal("-23.00"),
            gross=Decimal("-123.00"),
            invoice_number="FK/1",
            period=date(2026, 10, 1),
            issue_date=date(2026, 10, 2),
            choices=options.clean_choices(
                {"car": True, "net_account": "402-203", "allocation_account": "510-5",
                 "description": "Korekta leasingu"},
                entries,
            ),
        ),
        [],
        plan,
        now=datetime(2026, 11, 22, tzinfo=timezone.utc),
    )  # fmt: skip
    assert decree["problems"] == [] and decree["doc_type"] == "FKZ"
    row = SimpleNamespace(
        gross_amount=Decimal("-123.00"),
        vat_amount=Decimal("-23.00"),
        net_amount=Decimal("-100.00"),
        issue_date=date(2026, 10, 2),
        invoice_number="FK/1",
        source_due=None,
        currency="PLN",
    )
    doc = SimpleNamespace(
        op_date=date(2026, 10, 3), doc_date=date(2026, 10, 2), number="FK/1"
    )
    entry = SimpleNamespace(due_date=None, decree=decree)
    party = FinanceCounterparty(
        id=7, id_type="nip", id_value="1234567890", name="Dostawca", country="PL"
    )
    invoice = exports.purchase_invoice(entry, row, doc, party, corrects_number="F/1")
    assert isinstance(invoice, ExportInvoice)
    lines = [
        _line(
            invoice,
            no,
            item["account"],
            posting.money(item["amount"]) if item["side"] == "debit" else None,
            posting.money(item["amount"]) if item["side"] == "credit" else None,
            ksef_number="1234567890-20261002-AAAAAA000001-01",
        )
        for no, item in enumerate(decree["positions"], start=1)
    ]
    text = FORMAT.render(lines).decode("cp1250")
    assert "\tsymbol FK =FKZ\r\n" in text and "\tNazwaKor =F/1\r\n" in text
    assert "\t\tSkrot =Korekta Zakupu\r\n" in text
    assert "\t\tSkrot =Korekta Zakupu NP. VAT\r\n" in text
    assert text.count("\t\tvat =-11.50\r\n") == 2
    assert "\t\tkonto =221\r\n\t\tkwota =-11.50\r\n" in text
    assert text.count("ZapisRownolegly =33") == 2
    assert (
        "\t\tkonto =201-2-55\r\n\t\tkwota =-123.00\r\n\t\tpozycja =0\r\n\t\tIdDlaRozliczen =1"
        in text
    )
