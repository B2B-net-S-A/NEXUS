"""Ciągłość wyciągów rachunku: daty sald, numery wyciągów, łańcuch sald (bez bazy).

Reguła: ``docs/claude/zamowienia/faktury-do-klientow-z-ksef.md`` (19.11.2026),
kod ``app/services/ledger/bank_continuity.py``. Układ MT940 jak w wyciągu
Santandera z eBI24: saldo otwarcia z datą dnia wyciągu, ``:28C:`` = rok
i numer wyciągu w roku.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.hr.bank import camt053, mt940
from app.services.hr.bank.accounts import iban_check_digits
from app.services.ledger.bank_continuity import (
    Span,
    covered_until,
    file_span,
    follows,
    numbers_follow,
)

BBAN = "109010140000000000001234"
ACCOUNT = iban_check_digits(BBAN) + BBAN


def _amount(grosze: int) -> str:
    sign = "D" if grosze < 0 else "C"
    value = abs(grosze)
    return f"{sign}", f"{value // 100},{value % 100:02d}"


def _part(day: str, number: str, opening: int, ops: list[int], *, close_tag="62F"):
    """Jedna część wyciągu: ``day`` = RRMMDD, ``ops`` w groszach ze znakiem."""

    mark, value = _amount(opening)
    text = (
        f":20:X\r\n:25:/PL{ACCOUNT}\r\n:28C:{number}\r\n:60F:{mark}{day}PLN{value}\r\n"
    )
    balance = opening
    for index, op in enumerate(ops, start=1):
        sign = "C" if op > 0 else "D"
        text += (
            f":61:{day}{sign}{abs(op) // 100},{abs(op) % 100:02d}NTRFNONREF//R{index}\r\n"
            f":86:~00TR~20operacja {index}\r\n"
        )
        balance += op
    mark, value = _amount(balance)
    return text + f":{close_tag}:{mark}{day}PLN{value}\r\n-\r\n", balance


def _file(*parts: str) -> bytes:
    return "".join(parts).encode()


# ── Parser: daty sald i numer wyciągu ────────────────────────────────────────


def test_mt940_balances_carry_their_dates_and_statement_number():
    first, after = _part("261112", "26201/1", 100_000, [5_000, -2_000])
    second, _ = _part("261113", "26202/1", after, [-1_000])
    parsed = mt940.parse(_file(first, second))

    assert [b.opening_day for b in parsed.balances] == [
        date(2026, 11, 12),
        date(2026, 11, 13),
    ]
    assert [b.closing_day for b in parsed.balances] == [
        date(2026, 11, 12),
        date(2026, 11, 13),
    ]
    assert [b.number for b in parsed.balances] == [26201, 26202]


def test_mt940_bad_balance_date_does_not_reject_the_file():
    text, _ = _part("261112", "26201/1", 100_000, [5_000])
    parsed = mt940.parse(text.replace(":62F:C261112", ":62F:C261199").encode())

    assert parsed.balances[0].ok
    assert parsed.balances[0].closing_day is None
    assert file_span(parsed) is None


def _camt(opening_day: str, closing_day: str, number: str = "41") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
<BkToCstmrStmt><Stmt><Id>S1</Id><LglSeqNb>{number}</LglSeqNb>
<Acct><Id><IBAN>PL{ACCOUNT}</IBAN></Id><Ccy>EUR</Ccy></Acct>
<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">100.00</Amt>
<CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{opening_day}</Dt></Dt></Bal>
<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">150.00</Amt>
<CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{closing_day}</Dt></Dt></Bal>
<Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts>BOOK</Sts>
<BookgDt><Dt>{closing_day}</Dt></BookgDt></Ntry>
</Stmt></BkToCstmrStmt></Document>""".encode()


def test_camt_balances_carry_dates_and_legal_sequence_number():
    parsed = camt053.parse(_camt("2026-11-02", "2026-11-30"))
    balance = parsed.balances[0]

    assert (balance.opening_day, balance.closing_day, balance.number) == (
        date(2026, 11, 2),
        date(2026, 11, 30),
        41,
    )
    assert file_span(parsed) == Span(
        10_000, date(2026, 11, 2), 15_000, date(2026, 11, 30), 41, 41
    )


# ── Plik: salda całego pliku ────────────────────────────────────────────────


def test_file_of_daily_statements_gives_one_span():
    """Wyciąg „miesięczny” z eBI24 jako dni z operacjami: luka 13–15.11 bez wyciągu,
    numery po kolei — plik jest ciągły."""

    first, after = _part("261112", "26101/1", 100_000, [5_000])
    second, end = _part("261116", "26102/1", after, [-2_500])
    span = file_span(mt940.parse(_file(first, second)))

    assert span == Span(
        100_000, date(2026, 11, 12), end, date(2026, 11, 16), 26101, 26102
    )


def test_file_with_a_missing_statement_inside_gives_no_span():
    """Numer 26102 brakuje: równe saldo nad luką nie dowodzi, że nic się nie działo."""

    first, after = _part("261112", "26101/1", 100_000, [5_000])
    third, _ = _part("261116", "26103/1", after, [-2_500])

    assert file_span(mt940.parse(_file(first, third))) is None


def test_file_whose_parts_do_not_chain_gives_no_span():
    first, after = _part("261112", "26101/1", 100_000, [5_000])
    second, _ = _part("261113", "26102/1", after + 1, [-2_500])

    assert file_span(mt940.parse(_file(first, second))) is None


def test_part_without_closing_balance_gives_no_span():
    first, after = _part("261112", "26101/1", 100_000, [5_000])
    second, _ = _part("261113", "26102/1", after, [-2_500])
    without_close = second.replace(":62F:", ":64:")

    assert file_span(mt940.parse(_file(first, without_close))) is None


# ── Łańcuch plików ───────────────────────────────────────────────────────────


def _span(opening, start, closing, end, first=None, last=None) -> Span:
    return Span(opening, start, closing, end, first, last)


def test_next_statement_follows_on_the_same_or_next_day_with_equal_balance():
    april = _span(0, date(2026, 4, 1), 500, date(2026, 4, 30))

    assert follows(april, _span(500, date(2026, 5, 1), 900, date(2026, 5, 31)))
    # Data SWIFT: saldo otwarcia z dniem poprzedniego wyciągu.
    assert follows(april, _span(500, date(2026, 4, 30), 900, date(2026, 5, 31)))
    assert not follows(april, _span(501, date(2026, 5, 1), 900, date(2026, 5, 31)))
    assert not follows(april, _span(500, date(2026, 4, 29), 900, date(2026, 5, 31)))


def test_gap_of_days_needs_consecutive_statement_numbers():
    friday = _span(0, date(2026, 11, 13), 500, date(2026, 11, 13), 26210, 26210)

    assert follows(
        friday, _span(500, date(2026, 11, 16), 700, date(2026, 11, 16), 26211, 26211)
    )
    assert not follows(
        friday, _span(500, date(2026, 11, 16), 700, date(2026, 11, 16), 26212, 26212)
    )
    assert not follows(friday, _span(500, date(2026, 11, 16), 700, date(2026, 11, 16)))


def test_statement_numbering_restarts_in_a_new_year():
    assert numbers_follow(26221, 27001, date(2026, 12, 30), date(2027, 1, 4))
    assert numbers_follow(301, 1, date(2026, 12, 30), date(2027, 1, 4))
    assert not numbers_follow(26221, 27002, date(2026, 12, 30), date(2027, 1, 4))
    assert not numbers_follow(26221, 26001, date(2026, 12, 30), date(2026, 12, 31))


def test_covered_until_follows_the_chain_from_before_the_day():
    april = _span(0, date(2026, 4, 1), 500, date(2026, 4, 30))
    may = _span(500, date(2026, 5, 1), 900, date(2026, 5, 31))
    july = _span(900, date(2026, 7, 1), 950, date(2026, 7, 31))  # czerwca brak

    assert covered_until([april, may, july], date(2026, 4, 15)) == date(2026, 5, 31)
    assert covered_until([april, may, july], date(2026, 5, 1)) == date(2026, 5, 31)
    # Dzień otwarcia to dzień faktury: przy dacie SWIFT ten dzień jest w poprzednim wyciągu.
    assert covered_until([may], date(2026, 5, 1)) is None
    assert covered_until([april, may, july], date(2026, 7, 10)) == date(2026, 7, 31)
    assert covered_until([], date(2026, 4, 15)) is None


def test_daily_statement_inside_a_monthly_one_does_not_break_the_chain():
    november = _span(0, date(2026, 11, 2), 800, date(2026, 11, 30), 26190, 26220)
    daily = _span(300, date(2026, 11, 12), 350, date(2026, 11, 12), 26201, 26201)
    december = _span(800, date(2026, 12, 1), 900, date(2026, 12, 31), 26221, 26240)

    assert covered_until([daily, november, december], date(2026, 11, 5)) == date(
        2026, 12, 31
    )


def test_amounts_in_the_file_are_signed_grosze():
    first, _ = _part("261112", "1/1", -12_345, [2_345])
    span = file_span(mt940.parse(_file(first)))

    assert (span.opening_balance, span.closing_balance) == (-12_345, -10_000)
    assert Decimal(span.closing_balance) / 100 == Decimal("-100")
