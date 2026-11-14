"""Wyciąg w księdze (K4a) — reguły bez bazy: ZUS, urząd skarbowy, opłaty, WB."""

from __future__ import annotations

from datetime import date

from app.models.ledger import LedgerBankLine, LedgerBankStatement
from app.services.ledger import bank
from app.services.ledger.settings import BankSettings, CompanyAccount, nrb

ZUS = "83600000020260000000000000"
TAX = "36101000712221234567890123"
SUPPLIER = "11109010140000071219812874"
SETTINGS = BankSettings(
    accounts=(CompanyAccount("61109010140000071219812875", "130-1", "Konto główne"),),
    fees_account="402-9",
    zus_account="229",
    vat_account="222-2",
    pit_account="225",
    cit_account="",
)


def test_nrb_accepts_spaces_and_country_prefix():
    assert nrb("PL61 1090 1014 0000 0712 1981 2875") == "61109010140000071219812875"
    assert nrb("61109010140000071219812875") == "61109010140000071219812875"
    assert nrb("DE89370400440532013000") == ""
    assert nrb(None) == ""
    assert SETTINGS.by_number("PL61109010140000071219812875").account == "130-1"


def test_zus_account_by_bank_routing():
    kind, account, note = bank.rule_for("debit", ZUS, "Składki 10/2026", SETTINGS)
    assert (kind, account, note) == ("zus", "229", "")


def test_tax_micro_account_by_form_symbol():
    title = "/TI/N5260000000/OKR/26M10/SFP/VAT-7M/TXT/VAT 10.2026"
    assert bank.tax_form(title) == "VAT-7M"
    assert bank.rule_for("debit", TAX, title, SETTINGS)[:2] == ("tax", "222-2")
    pit = "/TI/N5260000000/OKR/26M10/SFP/PIT-4R/TXT/zaliczki"
    assert bank.rule_for("debit", TAX, pit, SETTINGS)[:2] == ("tax", "225")
    cit = "/TI/N5260000000/OKR/26M10/SFP/CIT-8/TXT/x"
    kind, account, note = bank.rule_for("debit", TAX, cit, SETTINGS)
    assert (kind, account) == ("tax", None) and "ustaw konto" in note
    unknown = bank.rule_for("debit", TAX, "podatek bez symbolu", SETTINGS)
    assert unknown[:2] == ("tax", None) and "/SFP/" in unknown[2]


def test_bank_fee_has_no_counterparty_account():
    assert bank.rule_for("debit", "", "Opłata za prowadzenie rachunku", SETTINGS)[
        :2
    ] == (
        "fee",
        "402-9",
    )
    # Przelew do dostawcy z „opłatą” w tytule to nie opłata banku.
    assert bank.rule_for("debit", SUPPLIER, "Opłata za fakturę 7/11", SETTINGS)[0] == (
        "unmatched"
    )
    assert bank.rule_for("credit", "", "Odsetki", SETTINGS)[0] == "unmatched"


def test_rules_without_accounts_wait_for_settings():
    empty = BankSettings(zus_account="", pit_account="")
    kind, account, note = bank.rule_for("debit", ZUS, "ZUS", empty)
    assert (kind, account) == ("zus", None) and "Ustawieniach" in note


def _line(
    position: int, direction: str, amount: int, counter: str, **extra
) -> LedgerBankLine:
    return LedgerBankLine(
        id=position,
        statement_id=1,
        line_ref=str(position),
        position=position,
        bank_ref="",
        booked_on=date(2026, 11, 20),
        direction=direction,
        amount=amount,
        title="tytuł",
        counterparty_name="Kontrahent",
        kind="manual",
        counter_account=counter,
        counterparty_id=extra.get("counterparty_id"),
        payroll=False,
    )


def test_wb_spec_posts_each_operation_against_the_bank_account():
    statement = LedgerBankStatement(
        id=7,
        sha256="x",
        format="mt940",
        bank_account="61109010140000071219812875",
        ledger_account="130-1",
        currency="PLN",
        first_day=date(2026, 11, 2),
        last_day=date(2026, 11, 20),
        line_count=2,
        debit_total=10_000,
        credit_total=25_000,
    )
    spec = bank.wb_spec(
        statement,
        [
            _line(1, "debit", 10_000, "229"),
            _line(2, "credit", 25_000, "200-17", counterparty_id=5),
        ],
        payroll=False,
    )
    assert spec.doc_type == "WB" and spec.op_date == date(2026, 11, 20)
    assert spec.source_type == "bank_statement" and spec.source_id == "7"
    assert spec.sensitivity is None
    # Opis bez nazwy z Ustawień — zmiana nazwy nie zmienia odcisku WB.
    assert spec.description == "Wyciąg …2875 02.11–20.11.2026"
    assert [
        (line.side, line.account, line.amount, line.counterparty_id)
        for line in spec.lines
    ] == [
        ("debit", "229", 10_000, None),
        ("credit", "130-1", 10_000, None),
        ("debit", "130-1", 25_000, None),
        ("credit", "200-17", 25_000, 5),
    ]
    payroll = bank.wb_spec(statement, [_line(1, "debit", 10_000, "231")], payroll=True)
    assert payroll.source_id == "7-payroll" and payroll.sensitivity == "payroll"


def test_parser_lists_every_statement_account():
    from app.services.hr.bank import mt940
    from app.services.hr.bank.accounts import iban_check_digits

    first = "1090101400000712198128"
    first = f"{iban_check_digits(first + '75')}{first}75"
    second = "1140200400000000000000"
    second = f"{iban_check_digits(second + '99')}{second}99"
    body = ""
    for account in (first, second):
        body += f":20:X\r\n:25:/PL{account}\r\n:60F:C261101PLN0,00\r\n"
        body += ":61:2611021102D1,00NTRFNONREF//R1\r\n:86:~00TR~20x\r\n:62F:C261102PLN0,00\r\n-\r\n"
    parsed = mt940.parse(body.encode())
    assert parsed.accounts == (first, second)
    assert parsed.account == second and len(parsed.lines) == 2


def test_camt_without_iban_counts_as_another_account():
    from app.services.hr.bank import camt053

    def stmt(account: str, ref: str) -> str:
        return (
            f"<Stmt><Acct><Id>{account}</Id><Ccy>PLN</Ccy></Acct>"
            '<Ntry><Amt Ccy="PLN">1.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>'
            f"<BookgDt><Dt>2026-11-20</Dt></BookgDt><AcctSvcrRef>{ref}</AcctSvcrRef></Ntry>"
            "</Stmt>"
        )

    raw = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt>'
        + stmt("<IBAN>PL61109010140000071219812874</IBAN>", "A1")
        + stmt("<Othr><Id>RACHUNEK-2</Id></Othr>", "A2")
        + "</BkToCstmrStmt></Document>"
    ).encode()
    parsed = camt053.parse(raw)
    assert parsed.accounts == ("61109010140000071219812874", "RACHUNEK-2")
