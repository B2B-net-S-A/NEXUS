"""Dzienniki kolejki „Koszty” i kroki z listy (22.11.2026) — reguły bez bazy.

Mapowanie kategorii na dzienniki i folderów eBI24 na kategorie, kto robi
„Zweryfikuj” faktury kontraktora i „Gotowa do księgowania” (także cofnięcie),
stan porównania faktury z rozliczeniem miesiąca i lista „Weryfikujący
kontraktorów” w ustawieniach. Dane fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.client_settlements import rules_catalog
from app.services.finance_ledger import costs, journals, settlement_match
from app.services.finance_ledger_schema import CATEGORIES
from app.services.ledger import settings as ledger_settings

NOBODY = costs.Approvers(accountant=False, verifier=False)
VERIFIER = costs.Approvers(accountant=False, verifier=True)
ACCOUNTANT = costs.Approvers(accountant=True, verifier=False)


def test_kazda_kategoria_ma_dziennik_a_dziennik_kategorie() -> None:
    assert set(journals.CATEGORY_JOURNAL) == set(CATEGORIES)
    assert {journals.journal_of(c) for c in CATEGORIES} == set(journals.JOURNALS)
    assert journals.categories_of("contractors") == ("contractor", "team")
    assert journals.categories_of("office") == ("office",)
    assert set(journals.categories_of("purchases")) == {"benefit", "proforma", "other"}
    assert set(journals.EBI24_FOLDER_CATEGORY.values()) <= set(CATEGORIES)
    assert journals.label_of("purchases") == "Zakupy pozostałe"
    assert journals.label_of(None) is None


@pytest.mark.parametrize(
    ("action", "stage", "category", "approvers", "refused"),
    [
        # Wstępna weryfikacja kontraktorów: lista albo „Księgowi”.
        ("verify", "new", "contractor", NOBODY, costs.VERIFY_CONTRACTORS_DETAIL),
        ("verify", "new", "team", NOBODY, costs.VERIFY_CONTRACTORS_DETAIL),
        ("verify", "new", "contractor", VERIFIER, None),
        ("verify", "new", "contractor", ACCOUNTANT, None),
        ("back", "verified", "contractor", NOBODY, costs.VERIFY_CONTRACTORS_DETAIL),
        ("back", "verified", "contractor", VERIFIER, None),
        # Poza „Kontraktorami” weryfikuje każdy z „Modułem Finanse”.
        ("verify", "new", "office", NOBODY, None),
        ("back", "verified", "other", NOBODY, None),
        # „Gotowa” i jej cofnięcie: tylko „Księgowi”, w każdym dzienniku.
        ("ready", "verified", "office", NOBODY, costs.READY_ACCOUNTANTS_DETAIL),
        ("ready", "verified", "contractor", VERIFIER, costs.READY_ACCOUNTANTS_DETAIL),
        ("ready", "verified", "contractor", ACCOUNTANT, None),
        ("back", "ready", "office", VERIFIER, costs.READY_ACCOUNTANTS_DETAIL),
        ("back", "ready", "office", ACCOUNTANT, None),
        # Przyjęcie, odrzucenie i cofnięcie do poczekalni — bez list.
        ("accept", "received", "contractor", NOBODY, None),
        ("reject", "new", "contractor", NOBODY, None),
        ("back", "new", "contractor", NOBODY, None),
    ],
)
def test_kroki_z_listy(action, stage, category, approvers, refused) -> None:
    assert costs.stage_refusal(action, stage, category, approvers) == refused


def test_uprawnienia_na_karcie() -> None:
    assert costs.permissions("contractor", NOBODY) == {"verify": False, "ready": False}
    assert costs.permissions("office", NOBODY) == {"verify": True, "ready": False}
    assert costs.permissions("contractor", VERIFIER) == {"verify": True, "ready": False}
    assert costs.permissions("contractor", ACCOUNTANT) == {
        "verify": True,
        "ready": True,
    }
    assert costs.ANYONE == costs.Approvers(accountant=True, verifier=True)


def _invoice(net: str, state: str = "known") -> SimpleNamespace:
    return SimpleNamespace(net_amount=Decimal(net), nip_state=state)


def _settlement(cost: str | None, status: str = "accepted") -> SimpleNamespace:
    return SimpleNamespace(
        amount_cost=Decimal(cost) if cost is not None else None, status=status
    )


def _rules(level: str = "block", tolerance: str = "0,00") -> dict:
    rules = rules_catalog.effective({})
    rules["ci.amount"] = {"level": level, "params": {"tolerance": tolerance}}
    return rules


@pytest.mark.parametrize(
    ("settlement", "invoices", "rules", "expected"),
    [
        (None, [_invoice("1000.00")], _rules(), "missing"),
        (_settlement("1000.00"), [_invoice("1000.00")], _rules(), "match"),
        (_settlement("1000.00"), [_invoice("999.00")], _rules(), "differs"),
        # Tolerancja z reguły klienta.
        (
            _settlement("1000.00"),
            [_invoice("999.50")],
            _rules(tolerance="1,00"),
            "match",
        ),
        # Korekta w tym samym miesiącu liczy się razem z fakturą.
        (
            _settlement("900.00"),
            [_invoice("1000.00"), _invoice("-100.00")],
            _rules(),
            "match",
        ),
        (_settlement(None, "checking"), [_invoice("1000.00")], _rules(), "waiting"),
        (_settlement("1000.00"), [_invoice("1.00")], _rules(level="off"), "unchecked"),
        (
            _settlement("1000.00"),
            [_invoice("1000.00", state="suggested")],
            _rules(),
            "nip_check",
        ),
    ],
)
def test_stan_porownania_z_rozliczeniem(settlement, invoices, rules, expected) -> None:
    assert settlement_match.summarize(settlement, invoices, rules) == expected
    assert expected in settlement_match.STATE_LABELS


def test_lista_weryfikujacych_w_ustawieniach() -> None:
    parsed = ledger_settings.normalize(
        {"accountants": [3], "cost_verifiers": [9, 4, 4, True, -1, "7"]}
    )
    assert parsed.cost_verifiers == (4, 9)
    assert ledger_settings.to_json(parsed)["cost_verifiers"] == [4, 9]
    assert ledger_settings.normalize({}).cost_verifiers == ()
    user = SimpleNamespace(id=9, has_role=lambda role: False)
    assert ledger_settings.can_verify_contractors(user, parsed)
    assert not ledger_settings.can_approve(user, parsed)
    accountant = SimpleNamespace(id=3, has_role=lambda role: False)
    assert ledger_settings.can_verify_contractors(accountant, parsed)
