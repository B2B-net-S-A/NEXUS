"""Rozliczenie kosztów na „5” (K2) — reguły bez bazy.

MPK ze źródła faktury (klient kontraktu, pion z kartoteki, klient albo pion
wniosku, koszty ogólne) i PK rozliczenia: Wn konta „5” z MPK, Ma 490, kwota
ujemna po drugiej stronie, płacowe osobno. Kwoty fikcyjne.
"""

from __future__ import annotations

from datetime import date

from app.services.ledger import allocation
from app.services.ledger.allocation import Mpk
from app.services.ledger.settings import AllocationAccounts

ACCOUNTS = AllocationAccounts(
    settlement_account="490",
    client_account="501-1",
    front_office_account="502",
    back_office_account="503",
    overhead_account="550",
    team_account="504",
)


def _mpk(source_type, **values):
    keys = {
        "contract_client": None,
        "payroll_division": None,
        "request_client": None,
        "requester_division": None,
    }
    keys.update(values)
    return allocation.mpk_of(source_type, **keys)


def test_contractor_invoice_goes_to_client_of_contract():
    assert _mpk("contractor_invoice", contract_client=7) == ("client", 7, None)
    assert _mpk("contractor_invoice") == ("overhead", None, None)


def test_team_invoice_goes_to_division_from_profile():
    assert _mpk("payroll_invoice", payroll_division="back_office") == (
        "back_office",
        None,
        "back_office",
    )
    assert _mpk("payroll_invoice", payroll_division=None) == ("overhead", None, None)


def test_approval_document_prefers_client_then_requester_division():
    assert _mpk("approval_document", request_client=3, requester_division="front_office") == (
        "client",
        3,
        None,
    )
    assert _mpk("approval_document", requester_division="front_office") == (
        "front_office",
        None,
        "front_office",
    )
    assert _mpk("approval_document") == ("overhead", None, None)


def _sides(spec):
    return [(line.side, line.account, line.amount, line.mpk) for line in spec.lines]


def test_allocation_debits_cost_centres_and_credits_settlement():
    totals = {
        Mpk("OG", "overhead", "Koszty ogólne"): 5_000,
        Mpk("K7", "client", "Klient Testowy"): 120_000,
        Mpk("BO", "back_office", "Back office"): 30_000,
    }
    spec = allocation.allocation_spec(2026, 10, totals, ACCOUNTS, payroll=False)
    assert _sides(spec) == [
        ("debit", "501-1", 120_000, "K7"),
        ("debit", "503", 30_000, "BO"),
        ("debit", "550", 5_000, "OG"),
        ("credit", "490", 155_000, None),
    ]
    assert spec.op_date == date(2026, 10, 31)
    assert (spec.source_type, spec.source_id) == ("cost_allocation", "2026-10")
    assert spec.sensitivity is None


def test_negative_cost_centre_goes_to_credit_and_balances():
    totals = {
        Mpk("K7", "client", "Klient Testowy"): 50_000,
        Mpk("K9", "client", "Klient Drugi"): -20_000,
    }
    spec = allocation.allocation_spec(2026, 2, totals, ACCOUNTS, payroll=False)
    debit = sum(line.amount for line in spec.lines if line.side == "debit")
    credit = sum(line.amount for line in spec.lines if line.side == "credit")
    assert debit == credit == 50_000
    assert ("credit", "501-1", 20_000, "K9") in _sides(spec)


def test_offsetting_centres_need_no_settlement_line():
    totals = {
        Mpk("K7", "client", "Klient Testowy"): 10_000,
        Mpk("K9", "client", "Klient Drugi"): -10_000,
    }
    spec = allocation.allocation_spec(2026, 2, totals, ACCOUNTS, payroll=False)
    assert [line.account for line in spec.lines] == ["501-1", "501-1"]


def test_nothing_to_allocate_gives_no_document():
    assert allocation.allocation_spec(2026, 2, {}, ACCOUNTS, payroll=False) is None
    zero = {Mpk("OG", "overhead", "Koszty ogólne"): 0}
    assert allocation.allocation_spec(2026, 2, zero, ACCOUNTS, payroll=False) is None


def test_team_costs_are_a_separate_payroll_document_on_one_account():
    totals = {
        Mpk("FO", "front_office", "Front office"): 1_000_000,
        Mpk("BO", "back_office", "Back office"): 400_000,
        Mpk("OG", "overhead", "Koszty ogólne"): 50_000,
    }
    spec = allocation.allocation_spec(2026, 10, totals, ACCOUNTS, payroll=True)
    assert spec.sensitivity == "payroll"
    assert spec.source_id == "2026-10-payroll"
    assert "osób zespołu" in spec.description
    # D2: pion tylko w MPK — konto jedno, więc obroty nie dzielą kwot na piony.
    assert {line.account for line in spec.lines if line.side == "debit"} == {"504"}
    assert [line.mpk for line in spec.lines[:3]] == ["BO", "FO", "OG"]


def test_cost_kind_comes_from_the_chart_even_after_it_changes():
    from app.services.ledger.engine import PlanAccount

    plan = {
        "402": PlanAccount("402", "Usługi obce", "cost", True, None, True),
        "402-203": PlanAccount("402-203", "IT", "cost", False, None, True),
        "221": PlanAccount("221", "VAT", "vat", True),
    }
    assert allocation.account_kind("402-203", plan) == "cost"
    assert allocation.account_kind("402-203-7", plan) == "cost"
    assert allocation.account_kind("221", plan) == "vat"
    assert allocation.account_kind("999", plan) is None


def test_accounts_are_complete_only_with_every_field():
    assert ACCOUNTS.complete()
    assert not AllocationAccounts().complete()
