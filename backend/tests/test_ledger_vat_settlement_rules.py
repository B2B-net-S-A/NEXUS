"""Rozliczenie VAT na koniec miesiąca (K5b-3c) — reguły bez bazy.

Kwoty fikcyjne. Decyzja Artura z 16.11.2026: saldo 222/221 idzie na „VAT do
zapłaty” (także nadwyżka naliczonego), grosze na konta różnic z zaokrągleń.
"""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

from app.services.ledger import sources
from app.services.ledger.closing import settlement_check
from app.services.ledger.settings import (
    BankSettings,
    LedgerSettings,
    VatAccounts,
)
from app.services.ledger.vat_settlement import (
    Basis,
    Settlement,
    basis_of,
    ledger_problem,
    missing_accounts,
    rounding,
    same_account,
    settlement_lines,
)

ACCOUNTS = {"tax_account": "225-1", "gain_account": "760", "loss_account": "761"}


def _lines(output, input_, basis):
    return [
        (line.side, line.account, line.amount)
        for line in settlement_lines(output, input_, basis, text_="VAT", **ACCOUNTS)
    ]


def _balanced(lines) -> bool:
    debit = sum(amount for side, _, amount in lines if side == "debit")
    credit = sum(amount for side, _, amount in lines if side == "credit")
    return debit == credit


def test_basis_takes_tax_from_records_and_due_without_previous_surplus():
    totals = {
        "P_38": 23_000,
        "P_39": 300,
        "P_48": 4_401,
        "P_51": 18_599,
        "output_tax": 2_300_040,
        "input_tax": 410_070,
    }
    basis = basis_of(totals)
    # P_39 (nadwyżka z poprzedniego okresu) już jest saldem Wn „VAT do zapłaty”.
    assert basis == Basis(2_300_040, 410_070, 23_000 - 4_101)
    assert basis_of({"P_38": 10, "P_48": 5}) is None


def test_month_with_tax_to_pay_moves_balances_to_tax_account():
    basis = Basis(output_tax=2_300_040, input_tax=410_070, due=23_000 - 4_101)
    lines = _lines({"222": 2_300_040}, {"221": 410_070}, basis)
    # 18 899 zł w deklaracji, a konta dają 18 899,70 zł — 0,70 zł przychodu.
    assert rounding(basis) == -70
    assert lines == [
        ("debit", "222", 2_300_040),
        ("credit", "221", 410_070),
        ("credit", "225-1", 1_889_900),
        ("credit", "760", 70),
    ]
    assert _balanced(lines)


def test_surplus_month_puts_surplus_on_tax_account_debit():
    # P_39 = 200 zł z poprzedniego miesiąca nie zmienia dokumentu.
    totals = {"P_38": 1_000, "P_39": 200, "P_48": 3_700, "P_62": 2_700}
    basis = basis_of({**totals, "output_tax": 100_000, "input_tax": 350_020})
    lines = _lines({"222": 100_000}, {"221": 350_020}, basis)
    assert basis.due == -2_500
    assert lines == [
        ("debit", "222", 100_000),
        ("credit", "221", 350_020),
        ("debit", "225-1", 250_000),
        ("debit", "761", 20),
    ]
    assert _balanced(lines)


def test_lines_follow_each_analytic_account_and_negative_turnover():
    # Korekty przewyższają sprzedaż: VAT należny ujemny, Ma 222.
    basis = Basis(output_tax=-50_000 + 20_000, input_tax=10_000, due=-400)
    lines = _lines({"222-1": -50_000, "222-2": 20_000}, {"221": 10_000}, basis)
    assert ("credit", "222-1", 50_000) in lines
    assert ("debit", "222-2", 20_000) in lines
    assert ("debit", "225-1", 40_000) in lines
    assert rounding(basis) == 0
    assert _balanced(lines)


def test_zero_month_has_no_lines():
    assert _lines({}, {}, Basis(0, 0, 0)) == []


def test_ledger_problem_explains_each_side():
    basis = Basis(output_tax=230_000, input_tax=46_000, due=1_840)
    assert ledger_problem(230_000, 46_000, basis, 2) is None
    problem = ledger_problem(230_000, 47_150, basis, 2)
    assert "wersja 2" in problem and "VAT naliczony" in problem
    assert "VAT należny" not in problem and "spoza rejestru" in problem


def _settings(**vat) -> LedgerSettings:
    return LedgerSettings(
        modules={"vat": True},
        accountants=(),
        bank=BankSettings(vat_account="225-1"),
        vat=VatAccounts(
            rounding_gain_account="760", rounding_loss_account="761", **vat
        ),
    )


def test_missing_accounts_and_tax_account_on_a_vat_account():
    settings = _settings()
    assert missing_accounts(settings) == [] and same_account(settings) is None
    empty = replace(settings, bank=BankSettings(), vat=VatAccounts())
    missing = missing_accounts(empty)
    assert len(missing) == 3 and "VAT do zapłaty" in missing[0]
    assert "zaokrągleń" in missing[1] and "Konta VAT" in missing[1]
    clash = replace(settings, bank=BankSettings(vat_account="222-9"))
    assert "222" in same_account(clash)


def _found(basis: Basis, doc=None) -> Settlement:
    from app.services.ledger.documents import DocumentSpec

    lines = settlement_lines(
        {"222": basis.output_tax},
        {"221": basis.input_tax},
        basis,
        text_="VAT",
        **ACCOUNTS,
    )
    spec = DocumentSpec(
        doc_type="VAT",
        op_date=date(2026, 3, 31),
        doc_date=date(2026, 3, 31),
        lines=lines,
        description="Rozliczenie VAT za 03.2026",
        source_type="vat_settlement",
        source_id="2026-03",
    )
    return Settlement(
        year=2026,
        month=3,
        day=date(2026, 3, 31),
        own="2026-03",
        file=None,
        basis=basis,
        output={"222": basis.output_tax},
        input_={"221": basis.input_tax},
        payroll=False,
        blocker=None,
        problem=None,
        spec=spec,
        document=doc,
    )


def test_jpk_correction_after_approval_flags_the_approved_document():
    before = _found(Basis(230_000, 46_000, 1_840))
    booked = SimpleNamespace(
        status="approved", meta={"fingerprint": sources.fingerprint(before.spec)}
    )
    assert _found(Basis(230_000, 46_000, 1_840), booked).changed is False
    # Korekta JPK zmieniła VAT naliczony — zatwierdzony dokument do storna.
    assert _found(Basis(230_000, 52_900, 1_771), booked).changed is True
    draft = SimpleNamespace(status="draft", meta={"fingerprint": "x"})
    assert _found(Basis(230_000, 52_900, 1_771), draft).changed is False
    # Szkic z innej wersji JPK: do przeliczenia, zanim ktoś go zatwierdzi.
    assert _found(Basis(230_000, 52_900, 1_771), draft).stale_draft is True
    assert _found(Basis(230_000, 46_000, 1_840), booked).stale_draft is False


def _check(**data):
    base = {
        "document": None,
        "problem": None,
        "changed": False,
        "blocker": None,
        "to_book": True,
    }
    return settlement_check({**base, **data}, "/accounting/vat")


def test_closing_item_states():
    assert _check()["state"] == "todo"
    assert _check(to_book=False) == {
        "key": "vat_settlement",
        "label": "Rozliczenie VAT",
        "href": "/accounting/vat",
        "state": "ok",
        "detail": "bez kwot do rozliczenia",
    }
    assert _check(blocker="Do rozliczenia VAT brakuje kont: …")["state"] == "todo"
    assert (
        _check(problem="Obroty kont VAT okresu różnią się od JPK")["state"] == "problem"
    )
    draft = {"number": "VAT 1/03/2026", "status": "draft", "payroll": True}
    item = _check(document=draft)
    assert item["state"] == "todo" and "Płacami" in item["detail"]
    stale = _check(document=draft, stale_draft=True)
    assert stale["state"] == "todo" and "nieaktualny" in stale["detail"]
    approved = {**draft, "status": "approved"}
    assert _check(document=approved)["state"] == "ok"
    changed = _check(document=approved, changed=True)
    assert changed["state"] == "problem" and "storno" in changed["detail"]
