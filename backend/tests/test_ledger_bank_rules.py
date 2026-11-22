"""Wyciąg w księdze (K4a) — reguły bez bazy: ZUS, urząd skarbowy, opłaty, WB."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

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
        body += ":61:2611021102D1,00NTRFNONREF//R1\r\n:86:~00TR~20x\r\n:62F:D261102PLN1,00\r\n-\r\n"
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


# ── Saldo wyciągu (18.11.2026: plik .eMT z eBI24) ──────────────────────────────

def _valid_nrb(bban: str) -> str:
    from app.services.hr.bank.accounts import iban_check_digits

    return f"{iban_check_digits(bban)}{bban}"


COMPANY_ACCOUNT = _valid_nrb("109010140000000000001234")


def _emt(*, drop_last: bool = False) -> bytes:
    """Układ wyciągu Santandera z eBI24: nagłówki SWIFT, trzy części wyciągu
    (``:62M:`` → ``:60M:``), opis ``?NN`` w kilku liniach, windows-1250."""

    header = "{1:F01TESTPLPWAXXX0000000000}{2:O9400000000000TESTPLPWAXXX0000000000000000000000N}{4:"
    parts = [
        ("60F", "C261006PLN1000,00", [("C", "200,00", "BZ28?00UZNANIE?20FV 1/9/2026?32KLIENT S.A.")], "62M", "C261006PLN1200,00"),
        ("60M", "C261006PLN1200,00", [("D", "50,50", "51CT?00PRZELEW?20Opłata za usługę?32DOSTAWCA")], "62M", "C261006PLN1149,50"),
        ("60M", "C261006PLN1149,50", [
            ("D", "0,71", "PROWIZJA ZA PRZEWALUTOWANIE"),
            ("D", "1000,00", "51CT?00PRZELEW NA RACHUNEK W NASZYM?20Zasilenie lokaty?32FIRMA"),
        ], "62F", "C261006PLN148,79"),
    ]
    if drop_last:
        parts[2][2].pop()
    text = ""
    for number, (open_tag, opening, ops, close_tag, closing) in enumerate(parts, start=1):
        text += f"{header}\r\n:20:261006/10901056\r\n:25:PL{COMPANY_ACCOUNT}\r\n:28C:26252/{number}\r\n"
        text += f":{open_tag}:{opening}\r\n"
        for mark, amount, details in ops:
            text += f":61:261006{mark}N{amount}NTRFNONREF\r\n:86:{details[:40]}\r\n"
            if details[40:]:
                text += details[40:] + "\r\n"
        text += f":{close_tag}:{closing}\r\n-}}\r\n"
    return text.encode("windows-1250")


def test_emt_from_ebi24_reads_every_part_and_balances():
    from app.services.hr.bank import statements

    parsed = statements.parse_file(_emt())
    assert parsed.format == "mt940"
    assert len(parsed.lines) == 4
    assert set(parsed.accounts) == {COMPANY_ACCOUNT}
    assert [item.ok for item in parsed.balances] == [True, True, True]
    assert parsed.balances[-1].closing == Decimal("148.79")
    assert parsed.lines[1].title.startswith("Opłata")
    lines = tuple(line for line in parsed.lines if bank.grosze(line.amount) > 0)
    bank._check_file(parsed, lines)


def test_truncated_statement_is_refused_by_balance():
    from app.services.finance_ledger.costs import LedgerError
    from app.services.hr.bank import statements

    parsed = statements.parse_file(_emt(drop_last=True))
    gap = [item for item in parsed.balances if not item.ok]
    assert [item.statement for item in gap] == [3]
    assert gap[0].expected == Decimal("1148.79")
    with pytest.raises(LedgerError) as error:
        bank._check_file(parsed, parsed.lines)
    assert error.value.status == 422
    assert "Saldo wyciągu się nie zgadza (wyciąg 3 w pliku)" in str(error.value)
    assert "1 148,79" in str(error.value) and "148,79" in str(error.value)


def test_statement_without_closing_balance_is_not_checked():
    from app.services.hr.bank import mt940

    raw = (
        f":20:X\r\n:25:/PL{COMPANY_ACCOUNT}\r\n:60F:C261101PLN10,00\r\n"
        ":61:2611021102D1,00NTRFNONREF//R1\r\n:86:~00TR~20x\r\n-"
    ).encode()
    assert mt940.parse(raw).balances == ()


def test_debit_balances_and_reversals_keep_their_sign():
    from app.services.hr.bank import mt940

    raw = (
        f":20:X\r\n:25:/PL{COMPANY_ACCOUNT}\r\n:60F:D261101PLN10,00\r\n"
        ":61:2611021102RC5,00NTRFNONREF//R1\r\n:86:~00storno uznania\r\n"
        ":61:2611021102RD2,00NTRFNONREF//R2\r\n:86:~00storno obciazenia\r\n"
        ":62F:D261102PLN13,00\r\n-"
    ).encode()
    (balance,) = mt940.parse(raw).balances
    assert (balance.opening, balance.movement, balance.closing) == (
        Decimal("-10.00"),
        Decimal("-3.00"),
        Decimal("-13.00"),
    )
    assert balance.ok


def _camt(closing: str, *, pending: bool = False) -> bytes:
    entries = (
        '<Ntry><Amt Ccy="PLN">100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>'
        "<BookgDt><Dt>2026-11-20</Dt></BookgDt><AcctSvcrRef>A1</AcctSvcrRef></Ntry>"
        '<Ntry><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-11-20</Dt></BookgDt><NtryDtls>'
        '<TxDtls><Amt Ccy="PLN">30.00</Amt></TxDtls><TxDtls><Amt Ccy="PLN">20.00</Amt></TxDtls>'
        "</NtryDtls></Ntry>"
    )
    if pending:
        entries += (
            '<Ntry><Amt Ccy="PLN">999.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>PDNG</Cd></Sts>'
            "<BookgDt><Dt>2026-11-20</Dt></BookgDt></Ntry>"
        )

    def bal(code: str, amount: str) -> str:
        return (
            f"<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp>"
            f'<Amt Ccy="PLN">{amount}</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>'
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt>'
        f"<Acct><Id><IBAN>PL{COMPANY_ACCOUNT}</IBAN></Id><Ccy>PLN</Ccy></Acct>"
        + bal("OPBD", "1000.00")
        + bal("CLBD", closing)
        + entries
        + "</Stmt></BkToCstmrStmt></Document>"
    ).encode()


def test_camt_balance_counts_booked_entries_only():
    from app.services.hr.bank import camt053

    (balance,) = camt053.parse(_camt("1050.00", pending=True)).balances
    assert balance.movement == Decimal("50.00") and balance.ok
    (broken,) = camt053.parse(_camt("1000.00")).balances
    assert not broken.ok
