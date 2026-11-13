"""Księga NEXUSA (K1, 0699) — reguły bez bazy.

Konto pozycji (dokładne, wyłączone, z analityką pod sobą, analityka słownika,
konto bez słownika), bilans dekretu, storno czerwone, czyszczenie pozycji
z żądania, numer dokumentu bez numeru ze źródła, przełączniki modułów (moduł
bez ekranów nie włącza się) i lista „Księgowi”. Konta i kwoty fikcyjne.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import ledger_schema as schema
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import engine
from app.services.ledger import settings as ledger_settings
from app.services.ledger.engine import LineIn

PLAN = engine.plan_from_rows(
    [
        ("131-1", "Rachunek bieżący", "other", True, None),
        ("201-2", "Rozrachunki z dostawcami", "settlement", True, "counterparty"),
        ("221", "VAT naliczony", "vat", True, None),
        ("402", "Usługi obce", "cost", True, None),
        ("402-203", "Usługi obce — kontraktorzy", "cost", True, None),
        ("409-998", "Pozostałe koszty", "cost", False, None),
        ("490", "Rozliczenie kosztów", "other", True, None),
        ("501", "Koszty działalności", "other", True, None),
    ]
)


def _line(side: str, account: str, amount: int) -> LineIn:
    return LineIn(side=side, account=account, amount=amount)


# ── Konta ────────────────────────────────────────────────────────────────────


def test_plan_marks_accounts_with_analytics():
    assert PLAN["402"].has_children is True
    assert PLAN["402-203"].has_children is False
    assert PLAN["131-1"].has_children is False


def test_exact_postable_account_resolves():
    resolved, problem = engine.resolve("402-203", PLAN)
    assert problem is None
    assert resolved is not None and resolved.analytic is False


def test_account_with_analytics_is_not_postable():
    resolved, problem = engine.resolve("402", PLAN)
    assert resolved is None
    assert "ma konta analityczne" in problem


def test_inactive_account_is_refused():
    resolved, problem = engine.resolve("409-998", PLAN)
    assert resolved is None
    assert "wyłączone" in problem


def test_dictionary_account_takes_analytics_without_plan_rows():
    resolved, problem = engine.resolve("201-2-1042", PLAN)
    assert problem is None
    assert resolved is not None and resolved.analytic is True
    assert resolved.plan.number == "201-2"


def test_dictionary_account_itself_needs_analytic():
    resolved, problem = engine.resolve("201-2", PLAN)
    assert resolved is None
    assert "201-2-NNN" in problem


def test_unknown_child_of_account_without_dictionary_is_refused():
    resolved, problem = engine.resolve("501-7", PLAN)
    assert resolved is None
    assert "słownik analityki" in problem


def test_unknown_account_is_refused():
    resolved, problem = engine.resolve("999", PLAN)
    assert resolved is None
    assert problem == "Konta 999 nie ma w planie kont."


def test_synthetic_groups_dictionary_analytics_only():
    assert engine.synthetic_of("201-2-1042", PLAN) == "201-2"
    assert engine.synthetic_of("402-203", PLAN) == "402-203"


# ── Dekret ───────────────────────────────────────────────────────────────────


def test_balanced_invoice_decree_has_no_issues():
    lines = [
        _line("debit", "402-203", 1_000_000),
        _line("debit", "221", 230_000),
        _line("credit", "201-2-1042", 1_230_000),
    ]
    result = engine.check(lines, PLAN)
    assert result.issues == []
    assert (result.debit, result.credit) == (1_230_000, 1_230_000)


def test_unbalanced_decree_names_both_sums():
    result = engine.check(
        [_line("debit", "402-203", 1_000), _line("credit", "131-1", 999)], PLAN
    )
    assert result.issues == ["Suma Wn (10,00 zł) różni się od sumy Ma (9,99 zł)."]
    with pytest.raises(LedgerError) as exc:
        engine.ensure_valid(
            [_line("debit", "402-203", 1_000), _line("credit", "131-1", 999)], PLAN
        )
    assert exc.value.status == 422


def test_single_line_and_zero_amount_are_refused():
    issues = engine.check([_line("debit", "402-203", 0)], PLAN).issues
    assert issues[0] == "Dokument potrzebuje co najmniej dwóch pozycji."
    assert "Pozycja 1: kwota nie może być zerem." in issues


def test_bad_account_reports_line_number():
    issues = engine.check(
        [_line("debit", "402", 100), _line("credit", "131-1", 100)], PLAN
    ).issues
    assert issues == [
        "Pozycja 1: Konto 402 ma konta analityczne — księguj na analitykę."
    ]


def test_red_storno_keeps_sides_and_negates_amounts():
    lines = [
        LineIn(side="debit", account="402-203", amount=1_000, amount_cur=250),
        _line("credit", "201-2-1042", 1_000),
    ]
    storno = engine.reversal(lines)
    assert [(line.side, line.account, line.amount) for line in storno] == [
        ("debit", "402-203", -1_000),
        ("credit", "201-2-1042", -1_000),
    ]
    assert storno[0].amount_cur == -250
    assert engine.totals(storno) == (-1_000, -1_000)
    assert engine.check(storno, PLAN).issues == []


def test_reclassification_on_one_side_balances_algebraically():
    lines = [_line("debit", "402-203", 500), _line("debit", "490", -500)]
    result = engine.check(lines, PLAN)
    assert result.issues == []
    assert (result.debit, result.credit) == (0, 0)


# ── Pozycje z żądania ────────────────────────────────────────────────────────


def test_clean_line_normalizes_account_and_text():
    line = engine.clean_line(
        {
            "side": "credit",
            "account": " 201-2-1042 ",
            "amount": 1_500,
            "description": "  zapłata   za  fakturę ",
        },
        1,
    )
    assert line == LineIn(
        side="credit",
        account="201-2-1042",
        amount=1_500,
        description="zapłata za fakturę",
    )


@pytest.mark.parametrize(
    "raw, message",
    [
        (
            {"side": "left", "account": "131-1", "amount": 1},
            "Pozycja 2: wybierz stronę Wn albo Ma.",
        ),
        (
            {"side": "debit", "account": "", "amount": 1},
            "Pozycja 2: podaj numer konta.",
        ),
        (
            {"side": "debit", "account": "131-1", "amount": True},
            "Pozycja 2: niepoprawna kwota.",
        ),
        (
            {"side": "debit", "account": "131-1", "amount": 1.5},
            "Pozycja 2: niepoprawna kwota.",
        ),
        (
            {"side": "debit", "account": "131;1", "amount": 1},
            "Pozycja 2: niepoprawny numer konta „131;1”.",
        ),
    ],
)
def test_clean_line_refuses_bad_input(raw, message):
    with pytest.raises(LedgerError) as exc:
        engine.clean_line(raw, 2)
    assert exc.value.message == message
    assert exc.value.status == 422


def test_auto_number_uses_period():
    assert engine.auto_number("PK", 3, date(2026, 10, 31)) == "PK 3/10/2026"


def test_doc_type_labels_cover_schema():
    assert set(engine.DOC_TYPE_LABELS) == set(schema.DOC_TYPES)


# ── Przełączniki i lista „Księgowi” ──────────────────────────────────────────


def test_settings_default_all_modules_off():
    current = ledger_settings.normalize(None)
    assert set(current.modules) == set(ledger_settings.MODULES)
    assert not any(current.modules.values())
    assert current.accountants == ()


def test_settings_cannot_open_module_without_screens():
    raw = {
        "modules": {"ledger": True, "payroll": True, "bank": "yes"},
        "accountants": [3, 3, 1],
    }
    current = ledger_settings.normalize(raw)
    assert current.modules["ledger"] is True
    assert current.modules["payroll"] is False
    assert current.modules["bank"] is False
    assert current.accountants == (1, 3)


def test_settings_drop_bad_accountant_ids():
    current = ledger_settings.normalize({"accountants": [0, -2, "7", True, 5]})
    assert current.accountants == (5,)


def test_every_module_has_label_stage_and_replacement():
    for key in ledger_settings.MODULES:
        assert ledger_settings.MODULE_LABELS[key]
        assert ledger_settings.MODULE_REPLACES[key]
    assert ledger_settings.BUILT <= set(ledger_settings.MODULES)


def test_account_kind_check_adds_other_to_e2_kinds():
    assert schema.ACCOUNT_KINDS[-1] == "other"
    assert "'other'" in schema.CK_ACCOUNT_KIND
