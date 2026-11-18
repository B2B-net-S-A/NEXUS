"""Konto przychodu FVS jak w Symfonii — reguły bez bazy.

Kolejność: konto z dokumentu tej faktury w księdze, dekret faktury w archiwum
eBI24, konto faktury korygowanej, konto poprzedniej faktury nabywcy; bez
historii albo z kontem spoza planu — problem, nie konto zapasowe. Konto
przychodów w Ustawieniach to tryb jednego konta. Konta, numery i kwoty fikcyjne.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.ledger import engine, revenue, sources
from app.services.ledger import settings as ledger_settings
from app.services.ledger.revenue import Posted, RevenueHistory
from app.services.ledger.settings import LedgerSettings, SalesAccounts

BUYER = "5260250274"


def _invoice(**overrides):
    values = {
        "id": 40,
        "ksef_number": None,
        "invoice_kind": "vat",
        "corrected_ksef_number": None,
        "corrects_invoice_id": None,
        "issue_date": date(2026, 11, 5),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _history(**overrides):
    values = {
        "by_buyer": {
            BUYER: (
                Posted(date(2026, 9, 30), "701-91-1", seq=1),
                Posted(date(2026, 10, 15), "701-91-3", seq=2),
                Posted(date(2026, 12, 1), "702-91-1", seq=3),
            )
        }
    }
    values.update(overrides)
    return RevenueHistory(**values)


def test_previous_invoice_of_buyer_gives_the_account():
    assert revenue.pick(_invoice(), _history(), BUYER) == (
        "701-91-3",
        revenue.PREVIOUS,
    )
    # Późniejsza faktura nabywcy nie decyduje o wcześniejszej.
    early = _invoice(issue_date=date(2026, 10, 1))
    assert revenue.pick(early, _history(), BUYER) == ("701-91-1", revenue.PREVIOUS)


def test_same_day_prefers_nexus_ledger_then_later_row():
    history = RevenueHistory(
        by_buyer={
            BUYER: (
                Posted(date(2026, 10, 31), "701-91-2", rank=1, seq=5),
                Posted(date(2026, 10, 31), "701-91-1", rank=0, seq=9),
            )
        }
    )
    assert revenue.pick(_invoice(), history, BUYER)[0] == "701-91-2"


def test_own_fvs_of_the_invoice_is_not_its_previous_invoice():
    history = RevenueHistory(
        by_buyer={
            BUYER: (
                Posted(date(2026, 10, 1), "701-91-1", seq=1),
                Posted(date(2026, 11, 5), "760-4", invoice_id="40", rank=1, seq=2),
            )
        }
    )
    assert revenue.pick(_invoice(), history, BUYER)[0] == "701-91-1"


def test_ebi24_decree_of_the_invoice_wins_over_history():
    history = _history(by_ksef={"KSEF-1": "702-91-1"})
    assert revenue.pick(_invoice(ksef_number="KSEF-1"), history, BUYER) == (
        "702-91-1",
        revenue.EBI24,
    )


def test_existing_document_keeps_its_revenue_account():
    """Poprawka księgowej w szkicu przetrwa przebudowę po zmianie historii."""

    history = _history(by_ksef={"KSEF-1": "702-91-1"}, current={"40": "701-91-2"})
    assert revenue.pick(_invoice(ksef_number="KSEF-1"), history, BUYER) == (
        "701-91-2",
        revenue.DOCUMENT,
    )


def test_correction_takes_account_of_corrected_invoice():
    by_ksef = _history(by_ksef={"KSEF-0": "702-91-3"})
    correction = _invoice(
        invoice_kind="correction", corrected_ksef_number="KSEF-0", corrects_invoice_id=7
    )
    assert revenue.pick(correction, by_ksef, BUYER) == ("702-91-3", revenue.ORIGINAL)
    by_nexus = _history(by_invoice={"7": "701-91-2"})
    assert revenue.pick(correction, by_nexus, BUYER) == ("701-91-2", revenue.ORIGINAL)
    # Korygowanej nie znamy — jak każda faktura nabywcy.
    assert revenue.pick(correction, _history(), BUYER)[1] == revenue.PREVIOUS


def test_buyer_without_history_is_a_problem_not_a_fallback():
    assert revenue.pick(_invoice(), _history(), "1111111111") == (
        None,
        revenue.NO_HISTORY,
    )
    assert revenue.pick(_invoice(), _history(), None) == (None, revenue.NO_HISTORY)


def test_buyer_id_compares_nip_with_or_without_country_prefix():
    assert revenue.buyer_id("PL 526-025-02-74") == BUYER
    assert revenue.buyer_id(" fi12345678 ") == "FI12345678"
    assert revenue.buyer_id(None) == ""


PLAN = engine.plan_from_rows(
    [
        ("701", "Przychody", "other", True, None),
        ("701-91", "Klient testowy", "other", True, None),
        ("701-91-1", "T&M", "revenue", True, None),
        ("701-91-3", "New Business", "revenue", True, None),
    ]
)


def _settings(revenue_account: str = "") -> LedgerSettings:
    return replace(
        ledger_settings.normalize(None),
        sales=SalesAccounts(
            receivable_account="200-2",
            revenue_account=revenue_account,
            vat_account="222",
        ),
    )


def _ctx(history: RevenueHistory, plan=PLAN):
    return sources._SalesContext(
        counterparties={},
        issued_rates={},
        originals={},
        nbp={},
        revenue=history,
        plan=plan,
    )


def test_settings_account_is_the_single_account_mode():
    found = sources.revenue_account(
        _invoice(), _ctx(_history()), _settings("701-91-1"), ("nip", BUYER)
    )
    assert found == ("701-91-1", revenue.SETTINGS)


def test_history_account_must_be_postable_in_the_plan():
    key = ("nip", BUYER)
    assert sources.revenue_account(_invoice(), _ctx(_history()), _settings(), key) == (
        "701-91-3",
        revenue.PREVIOUS,
    )
    synthetic = _history(by_ksef={"KSEF-1": "701-91"})
    account, problem = sources.revenue_account(
        _invoice(ksef_number="KSEF-1"), _ctx(synthetic), _settings(), key
    )
    assert account is None
    assert problem.startswith("Konto przychodu 701-91 (z dekretu tej faktury")
    assert "ma konta analityczne" in problem
    missing = _history(by_ksef={"KSEF-1": "702-91-1"})
    account, problem = sources.revenue_account(
        _invoice(ksef_number="KSEF-1"), _ctx(missing), _settings(), key
    )
    assert account is None and "702-91-1 nie ma w planie kont" in problem


def test_sales_spec_records_where_the_revenue_account_came_from():
    counterparty = SimpleNamespace(
        id=3, name="Nabywca", revenue_account=None, symfonia_partner_id="17"
    )
    invoice = SimpleNamespace(
        id=40,
        invoice_type="VAT",
        invoice_kind="vat",
        buyer_nip=BUYER,
        buyer_foreign_id=None,
        buyer_name="Nabywca",
        ksef_number="KSEF-1",
        corrected_ksef_number=None,
        corrected_invoice_number=None,
        corrects_invoice_id=None,
        invoice_number="1/11/2026",
        currency="PLN",
        net_amount=Decimal("100.00"),
        vat_amount=Decimal("23.00"),
        gross_amount=Decimal("123.00"),
        sale_date=date(2026, 11, 3),
        issue_date=date(2026, 11, 5),
    )
    ctx = sources._SalesContext(
        counterparties={("nip", BUYER): counterparty},
        issued_rates={},
        originals={},
        nbp={},
        revenue=_history(by_ksef={"KSEF-1": "701-91-1"}),
        plan=PLAN,
    )
    spec = sources.sales_spec(invoice, ctx, _settings())
    assert [(line.side, line.account, line.amount) for line in spec.lines] == [
        ("debit", "200-2-17", 12_300),
        ("credit", "701-91-1", 10_000),
        ("credit", "222", 2_300),
    ]
    assert spec.meta["revenue_from"] == revenue.EBI24
    no_history = sources.sales_spec(
        invoice,
        sources._SalesContext({("nip", BUYER): counterparty}, {}, {}, {}),
        _settings(),
    )
    assert no_history == revenue.NO_HISTORY


# ── Konto wskazane dla nabywcy bez historii (decyzja Artura 18.11.2026) ──────


def test_chosen_account_fills_in_only_when_the_buyer_has_no_history():
    assert revenue.pick(_invoice(), _history(), "1111111111", "760-5") == (
        "760-5",
        revenue.CHOSEN,
    )
    # Historia wygrywa: poprzednia faktura nabywcy, dekret i faktura korygowana.
    assert revenue.pick(_invoice(), _history(), BUYER, "760-5") == (
        "701-91-3",
        revenue.PREVIOUS,
    )
    archived = _history(by_ksef={"KSEF-1": "701-91-1"})
    assert revenue.pick(_invoice(ksef_number="KSEF-1"), archived, None, "760-5") == (
        "701-91-1",
        revenue.EBI24,
    )
    assert revenue.pick(_invoice(), _history(), None, "") == (None, revenue.NO_HISTORY)


def _chosen(counterparty_id: int, account: str) -> LedgerSettings:
    return replace(
        _settings(),
        revenue_accounts={
            counterparty_id: ledger_settings.RevenueChoice(account=account, by=7)
        },
    )


def test_chosen_account_goes_through_the_plan_check():
    key = ("nip", "1111111111")
    assert sources.revenue_account(
        _invoice(), _ctx(_history()), _chosen(3, "701-91-1"), key, counterparty_id=3
    ) == ("701-91-1", revenue.CHOSEN)
    # Wskazanie innego nabywcy nie przechodzi na tego.
    assert sources.revenue_account(
        _invoice(), _ctx(_history()), _chosen(4, "701-91-1"), key, counterparty_id=3
    ) == (None, revenue.NO_HISTORY)
    account, problem = sources.revenue_account(
        _invoice(), _ctx(_history()), _chosen(3, "701-91"), key, counterparty_id=3
    )
    assert account is None
    assert problem.startswith("Konto przychodu 701-91 (wskazane dla nabywcy")
    assert sources.needs_revenue_choice(problem)
    assert sources.needs_revenue_choice(revenue.NO_HISTORY)
    assert not sources.needs_revenue_choice(sources.NO_BUYER)


def test_revenue_choices_survive_the_settings_round_trip():
    raw = {
        "revenue_accounts": {
            "3": {"account": "760-5", "by": 7, "at": "2026-11-18T10:00:00+00:00"},
            "4": {"account": "zła wartość!"},
            "x": {"account": "701-91-1"},
            "5": "701-91-1",
        }
    }
    loaded = ledger_settings.normalize(raw)
    assert loaded.revenue_accounts == {
        3: ledger_settings.RevenueChoice(
            account="760-5", by=7, at="2026-11-18T10:00:00+00:00"
        )
    }
    assert ledger_settings.normalize(ledger_settings.to_json(loaded)) == loaded
