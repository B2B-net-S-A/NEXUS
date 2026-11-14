"""Lista płac z Enovy (K3c) — reguły bez bazy: kolumny, odczyt pliku, dekret."""

from __future__ import annotations

import pytest

from app.services.finance_ledger.counterparty_import import ImportFileError
from app.services.ledger import payroll_lists
from app.services.ledger.settings import PayrollAccounts

HEADER = (
    "Pracownik;Wydział;Razem brutto;Emerytalne prac.;Rentowe prac.;Chorobowe;Zdrowotne;"
    "Zaliczka podatku;PPK pracownika;Inne potrącenia;Do wypłaty;Emerytalne pracodawca;"
    "Rentowe pracodawca;Wypadkowe;FP;FGŚP;PPK pracodawcy"
)
ROW_A = "Osoba A;FO;10000,00;976,00;150,00;245,00;776,61;588,00;200,00;0;7064,39;976,00;650,00;167,00;245,00;10,00;150,00"
ROW_B = "Osoba B;BO;8 000,00;780,80;120,00;196,00;621,29;470,00;0;100,00;5711,91;780,80;520,00;133,60;196,00;8,00;0"
TOTAL = "Razem;;18000,00;1756,80;270,00;441,00;1397,90;1058,00;200,00;100,00;12776,30;1756,80;1170,00;300,60;441,00;18,00;150,00"

ACCOUNTS = PayrollAccounts(
    wages_account="404",
    insurance_account="405",
    settlement_account="231",
    zus_account="229",
    pit_account="225",
    ppk_account="234-1",
    deductions_account="234-2",
)


def _csv(*rows: str) -> bytes:
    return "\r\n".join(rows).encode("utf-8")


@pytest.mark.parametrize(
    ("header", "key"),
    [
        ("Emerytalne pracodawca", "er_pension"),
        ("Emerytalne prac.", "emp_pension"),
        ("Emerytalne", "emp_pension"),
        ("Rentowe pracodawcy", "er_disability"),
        ("Rentowe", "emp_disability"),
        ("PPK pracodawcy", "ppk_er"),
        ("PPK pracownika", "ppk_emp"),
        ("FGŚP", "fgsp"),
        ("FP", "fp"),
        ("Fundusz Pracy", "fp"),
        ("Ubezpieczenie zdrowotne", "health"),
        ("Zaliczka podatku", "pit"),
        ("Do wypłaty", "net"),
        ("Netto", "net_alt"),
        ("Razem brutto", "gross"),
        ("Wydział", "mpk"),
        ("Pracownik", "person"),
        ("Podstawa ub. zdrowotnego", None),
        ("Wynagrodzenie zasadnicze", None),
    ],
)
def test_headers_map_to_columns(header, key):
    assert payroll_lists.column_for(header) == key


def test_parse_skips_total_row_and_reads_polish_amounts():
    parsed = payroll_lists.parse(_csv(HEADER, ROW_A, ROW_B, TOTAL))
    assert len(parsed.rows) == 2 and parsed.skipped == 1
    assert parsed.errors == [] and parsed.warnings == []
    first, second = parsed.rows
    assert first.mpk == "FO" and first.amounts["gross"] == 1_000_000
    assert second.amounts["gross"] == 800_000 and second.amounts["deductions"] == 10_000


def test_totals_and_balanced_decree_per_cost_centre():
    parsed = payroll_lists.parse(_csv(HEADER, ROW_A, ROW_B))
    total, by_mpk = payroll_lists.totals(parsed.rows)
    assert total.gross == 1_800_000
    assert total.employee == 522_370  # składki, zdrowotna, PIT, PPK, potrącenia
    assert total.employer == 383_640  # składki, FP, FGŚP, PPK pracodawcy
    assert total.zus == 755_210 and total.pit == 105_800 and total.ppk == 35_000
    assert total.net == 1_277_630
    assert by_mpk == {"FO": [1_000_000, 219_800], "BO": [800_000, 163_840]}
    lines, problems = payroll_lists.decree(parsed.rows, ACCOUNTS)
    assert problems == []
    debit = sum(line.amount for line in lines if line.side == "debit")
    credit = sum(line.amount for line in lines if line.side == "credit")
    assert debit == credit == 2_706_010
    assert [(line.side, line.account, line.amount, line.mpk) for line in lines] == [
        ("debit", "404", 800_000, "BO"),
        ("debit", "405", 163_840, "BO"),
        ("debit", "404", 1_000_000, "FO"),
        ("debit", "405", 219_800, "FO"),
        ("debit", "231", 522_370, None),
        ("credit", "231", 1_800_000, None),
        ("credit", "229", 755_210, None),
        ("credit", "225", 105_800, None),
        ("credit", "234-1", 35_000, None),
        ("credit", "234-2", 10_000, None),
    ]


def test_net_mismatch_is_a_warning_not_an_error():
    wrong = ROW_A.replace(";7064,39;", ";7000,00;")
    parsed = payroll_lists.parse(_csv(HEADER, wrong))
    assert parsed.errors == [] and len(parsed.rows) == 1
    assert len(parsed.warnings) == 1 and "różnica -64.39 zł" in parsed.warnings[0]["message"]


def test_netto_counts_only_without_do_wyplaty_column():
    header = "Pracownik;Brutto;Zaliczka podatku;Netto"
    parsed = payroll_lists.parse(_csv(header, "Osoba A;1000,00;100,00;900,00"))
    assert parsed.rows[0].amounts["net"] == 90_000 and parsed.warnings == []


def test_ambiguous_and_missing_columns_refuse_the_file():
    with pytest.raises(ImportFileError, match="ta sama"):
        payroll_lists.parse(_csv("Pracownik;Brutto;Emerytalne;Emerytalne", "A;1;1;1"))
    with pytest.raises(ImportFileError, match="Brutto"):
        payroll_lists.parse(_csv("Pracownik;Zaliczka podatku", "A;1"))


def test_unreadable_amount_is_a_row_error():
    parsed = payroll_lists.parse(_csv(HEADER, ROW_A.replace("588,00", "abc")))
    assert parsed.rows == [] and parsed.errors[0]["message"].startswith("Nieczytelna")


def test_missing_accounts_and_ppk_without_account_are_problems():
    parsed = payroll_lists.parse(_csv(HEADER, ROW_A))
    lines, problems = payroll_lists.decree(parsed.rows, PayrollAccounts())
    assert lines == [] and "Wynagrodzenia (koszt)" in problems[0]
    no_ppk = PayrollAccounts(
        wages_account="404",
        insurance_account="405",
        ppk_account="",
        deductions_account="",
    )
    lines, problems = payroll_lists.decree(parsed.rows, no_ppk)
    assert lines == [] and any("PPK" in problem for problem in problems)


def test_list_name_is_required():
    with pytest.raises(Exception, match="nazwę listy"):
        payroll_lists.list_key("  ")
    assert payroll_lists.list_key("LP 03/2026") == "lp032026"
