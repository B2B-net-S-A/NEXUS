"""Opis faktury kosztowej wg „Ogólnych założeń” księgowej (E2, 18.11.2026) — bez bazy.

Samochód (1/2 VAT, dwa rejestry, 999 / 902), import usług spoza UE i z UE,
WNT, korekta, waluta z kursem z karty, „5” jako zapis równoległy, konto
brutto z kartoteki, konta zespołów 4 i 7 o rodzaju „inne”, braki w planie
kont i odmowy wyborów. Kontrahenci, numery i kwoty fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.services.finance_ledger import posting
from app.services.finance_ledger import posting_options as options
from app.services.finance_ledger.costs import LedgerError

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)


def _plan(*rows: tuple[str, str]) -> dict[str, posting.AccountView]:
    return {
        number: posting.AccountView(number, f"Konto {number}", kind, True)
        for number, kind in rows
    }


#: Jak plan na produkcji: konta 4 i 7 z rodzajem „inne” (import z Symfonii).
PLAN = _plan(
    ("402-203", "cost"),
    ("402-215", "other"),
    ("244-3", "other"),
    ("751-2", "other"),
    ("301-1", "other"),
    ("221", "vat"),
    ("223", "other"),
    ("403-302", "other"),
    ("226", "other"),
    ("510-5", "other"),
    ("501-6-1", "other"),
    ("490", "other"),
    ("999", "other"),
    ("902", "other"),
)
PLAN_ENTRIES = {
    number: options.PlanEntry(item.number, item.kind, item.active)
    for number, item in PLAN.items()
}


def _rule(**overrides) -> posting.RuleView:
    values = {
        "id": 1,
        "category": "contractor",
        "counterparty_id": None,
        "cost_account": "402-203",
        "vat_account": "221",
        "deduction": "full",
        "register": "purchase",
        "doc_type": "FVZ",
        "service_label": "Usługi IT",
        "description_template": "{usługa} {MM}/{RRRR}",
        "active": True,
    }
    values.update(overrides)
    return posting.RuleView(**values)


def _input(**overrides) -> posting.DecreeInput:
    values = {
        "category": "contractor",
        "counterparty_id": 7,
        "counterparty_name": "Dostawca Testowy",
        "counterparty_account": None,
        "currency": "PLN",
        "net": Decimal("1000.01"),
        "vat": Decimal("230.01"),
        "gross": Decimal("1230.02"),
        "invoice_number": "FT/7/2026",
        "period": date(2026, 10, 1),
        "issue_date": date(2026, 11, 4),
        "counterparty_symfonia_id": "4321",
    }
    values.update(overrides)
    return posting.DecreeInput(**values)


def _choices(**values) -> dict:
    return options.clean_choices(values, PLAN_ENTRIES)


def _sides(decree) -> list[tuple]:
    return [
        (item["kind"], item["account"], item["side"], item["amount"])
        for item in decree["positions"]
    ]


def _compute(inp: posting.DecreeInput, rules=None) -> dict:
    return posting.compute(inp, [_rule()] if rules is None else rules, PLAN, now=NOW)


# ── Konto brutto z kartoteki ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("stored", "foreign", "currency", "expected"),
    [
        (None, False, "PLN", "201-2-4321"),
        (None, True, "EUR", "203-2-4321"),
        (None, True, "PLN", "203-2-4321"),
        (None, False, "EUR", "205-2-4321"),
        # Konto z kartoteki spoza 201/203/205 (np. leasing) wygrywa.
        ("244-1", False, "PLN", "244-1"),
        # Prefiks z kartoteki dopasowany do waluty faktury.
        ("201-2-4321", False, "EUR", "205-2-4321"),
    ],
)
def test_settlement_account_follows_the_accountants_table(
    stored, foreign, currency, expected
) -> None:
    assert (
        posting.settlement_account(stored, "4321", foreign=foreign, currency=currency)
        == expected
    )


def test_settlement_account_without_symfonia_number_uses_the_stored_account() -> None:
    assert (
        posting.settlement_account("201-2-77", None, foreign=False, currency="PLN")
        == "201-2-77"
    )
    assert posting.settlement_account(None, None, foreign=False, currency="PLN") is None


def test_counterparty_without_account_nor_number_blocks() -> None:
    decree = _compute(_input(counterparty_symfonia_id=None))
    assert any("numeru Symfonii" in problem for problem in decree["problems"])


# ── Konta zespołów 4 i 7 o rodzaju „inne” ────────────────────────────────────


def test_net_account_of_group_4_or_7_with_kind_other_is_accepted() -> None:
    for number in ("402-215", "751-2"):
        decree = _compute(_input(choices=_choices(net_account=number)))
        assert decree["problems"] == []
        assert decree["positions"][0]["account"] == number
        assert posting.check(decree, PLAN) == []


def test_net_account_outside_group_4_and_7_is_refused() -> None:
    with pytest.raises(options.ChoiceError, match="nie pasuje"):
        _choices(net_account="301-1")


def test_rule_with_an_other_kind_account_in_group_4_is_complete() -> None:
    decree = _compute(_input(), [_rule(cost_account="402-215")])
    assert decree["problems"] == []


def test_net_account_missing_in_plan_is_refused_and_reported() -> None:
    with pytest.raises(options.ChoiceError, match="nie ma w planie"):
        _choices(net_account="409-111")
    # Konto wyłączone po zapisie wyboru: dekret mówi, czego brakuje.
    plan = dict(PLAN)
    plan["402-215"] = posting.AccountView("402-215", "x", "other", False)
    decree = posting.compute(
        _input(choices=_choices(net_account="402-215")), [_rule()], plan, now=NOW
    )
    assert any("402-215" in problem for problem in decree["problems"])


def test_no_rule_but_net_account_chosen_gives_a_decree() -> None:
    decree = _compute(
        _input(choices=_choices(net_account="402-215", description="Biuro 10/2026")),
        rules=[],
    )
    assert decree["problems"] == []
    assert decree["doc_type"] == "FVZ"
    assert [item["name"] for item in decree["registers"]] == ["Zakup"]


def test_no_rule_and_no_choice_blocks_like_before() -> None:
    decree = _compute(_input(), rules=[])
    assert decree["positions"] == []
    assert "Brak aktywnej reguły" in decree["problems"][0]


# ── Faktura krajowa, „5”, MK ─────────────────────────────────────────────────


def test_domestic_invoice_with_allocation_has_parallel_5_and_490() -> None:
    decree = _compute(_input(choices=_choices(allocation_account="510-5")))
    assert decree["problems"] == []
    assert _sides(decree) == [
        ("cost", "402-203", "debit", 100_001),
        ("vat", "221", "debit", 23_001),
        ("counterparty", "201-2-4321", "credit", 123_002),
        ("allocation", "510-5", "debit", 100_001),
        ("allocation_offset", "490", "credit", 100_001),
    ]
    assert [item["parallel"] for item in decree["positions"]] == [
        False, False, False, True, True,
    ]  # fmt: skip
    assert decree["registers"][0] == {
        "name": "Zakup",
        "rate": "23",
        "net": 100_001,
        "vat": 23_001,
        "gross": 123_002,
        "net_cur": None,
        "vat_cur": None,
        "gross_cur": None,
        "output": False,
        "eu": False,
        "service": False,
    }
    assert posting.check(decree, PLAN) == []


def test_allocation_without_490_in_plan_is_reported() -> None:
    plan = {key: value for key, value in PLAN.items() if key != "490"}
    decree = posting.compute(
        _input(choices=_choices(allocation_account="510-5")), [_rule()], plan, now=NOW
    )
    assert any("490" in problem for problem in decree["problems"])


def test_allocation_account_must_be_in_group_5() -> None:
    with pytest.raises(options.ChoiceError):
        _choices(allocation_account="402-215")


def test_cash_method_from_ksef_sets_mk_and_choice_wins() -> None:
    assert _compute(_input(cash_method=True))["jpk_procedure"] == "MK"
    assert _compute(_input())["jpk_procedure"] is None
    chosen = _compute(_input(cash_method=True, choices=_choices(jpk_procedure="WEW")))
    assert chosen["jpk_procedure"] == "WEW"


def test_service_date_comes_from_the_input_unless_chosen() -> None:
    assert _compute(_input(service_date=date(2026, 10, 31)))["service_date"] == (
        "2026-10-31"
    )
    chosen = _compute(
        _input(
            service_date=date(2026, 10, 31),
            choices=_choices(service_date="2026-10-15"),
        )
    )
    assert chosen["service_date"] == "2026-10-15"


# ── Samochód ─────────────────────────────────────────────────────────────────


def test_car_books_net_plus_half_vat_and_splits_the_register() -> None:
    decree = _compute(
        _input(
            counterparty_account="244-1",
            choices=_choices(
                car=True,
                net_account="244-3",
                allocation_account="510-5",
                offbalance_account="902",
            ),
        )
    )
    assert decree["problems"] == []
    # VAT 230,01: 115,00 do odliczenia, 115,01 do kosztu (pierwsza połowa w dół).
    assert _sides(decree) == [
        ("cost", "244-3", "debit", 100_001 + 11_501),
        ("vat", "221", "debit", 11_500),
        ("counterparty", "244-1", "credit", 123_002),
        ("offbalance", "999", "debit", 61_501),
        ("offbalance_offset", "902", "credit", 61_501),
        ("allocation", "510-5", "debit", 111_502),
        ("allocation_offset", "490", "credit", 111_502),
    ]
    registers = [
        (item["name"], item["net"], item["vat"], item["gross"])
        for item in decree["registers"]
    ]
    assert registers == [
        ("Zakup", 50_000, 11_500, 61_500),
        ("Rejestr NP VAT", 50_001, 11_501, 61_502),
    ]
    assert sum(item[1] for item in registers) == 100_001
    assert posting.check(decree, PLAN) == []


def test_car_correction_uses_correction_registers_and_swaps_sides() -> None:
    decree = _compute(
        _input(
            net=Decimal("-100.00"),
            vat=Decimal("-23.00"),
            gross=Decimal("-123.00"),
            choices=_choices(car=True),
        )
    )
    assert decree["doc_type"] == "FKZ"
    assert [item["name"] for item in decree["registers"]] == [
        "Korekta Zakupu",
        "Korekta Zakupu NP. VAT",
    ]
    assert _sides(decree) == [
        ("cost", "402-203", "credit", 11_150),
        ("vat", "221", "credit", 1_150),
        ("counterparty", "201-2-4321", "debit", 12_300),
    ]


def test_offbalance_only_for_cars() -> None:
    with pytest.raises(options.ChoiceError, match="samochodowych"):
        _choices(offbalance_account="902")
    with pytest.raises(options.ChoiceError):
        _choices(car=True, offbalance_account="999")


# ── Import usług i WNT ───────────────────────────────────────────────────────


def _import_input(**overrides) -> posting.DecreeInput:
    values = {
        "currency": "EUR",
        "net": Decimal("1000.00"),
        "vat": Decimal("0"),
        "gross": Decimal("1000.00"),
        "counterparty_foreign": True,
        "fx_rate": Decimal("4.2345"),
        "fx_date": date(2026, 11, 3),
    }
    values.update(overrides)
    return _input(**values)


def test_import_of_services_from_outside_eu() -> None:
    decree = _compute(
        _import_input(
            choices=_choices(
                doc_type="IU",
                allocation_account="501-6-1",
                fx_table="214/A/NBP/2026",
            )
        )
    )
    assert decree["problems"] == []
    # 1000 EUR × 4,2345 = 4234,50 zł; VAT 23% = 973,94 zł (230,00 EUR).
    assert _sides(decree) == [
        ("cost", "402-203", "debit", 423_450),
        ("counterparty", "203-2-4321", "credit", 423_450),
        ("vat", "221", "debit", 97_394),
        ("vat_due", "226", "credit", 97_394),
        ("allocation", "501-6-1", "debit", 423_450),
        ("allocation_offset", "490", "credit", 423_450),
    ]
    assert [item["amount_cur"] for item in decree["positions"]] == [
        100_000, 100_000, 23_000, 23_000, 100_000, 100_000,
    ]  # fmt: skip
    registers = decree["registers"]
    assert [(item["name"], item["output"]) for item in registers] == [
        ("Import usług VAT naliczony", False),
        ("Import usług VAT należny", True),
    ]
    first = registers[0]
    assert (first["net"], first["vat"], first["gross"]) == (423_450, 97_394, 520_844)
    assert (first["net_cur"], first["vat_cur"], first["gross_cur"]) == (
        100_000,
        23_000,
        123_000,
    )
    # Spoza UE: tylko „Usługa”.
    assert (first["eu"], first["service"]) == (False, True)
    assert decree["jpk_procedure"] == "BFK"
    assert decree["fx_table"] == "214/A/NBP/2026"
    assert posting.check(decree, PLAN) == []


def test_import_of_services_from_eu_marks_eu_and_service() -> None:
    decree = _compute(
        _import_input(counterparty_eu=True, choices=_choices(doc_type="IU"))
    )
    first = decree["registers"][0]
    assert (first["eu"], first["service"]) == (True, True)
    # Flagi z karty wygrywają z podpowiedzią.
    decree = _compute(
        _import_input(counterparty_eu=True, choices=_choices(doc_type="IU", eu=False))
    )
    assert decree["registers"][0]["eu"] is False


def test_wnt_defaults_to_goods_with_its_registers() -> None:
    decree = _compute(
        _import_input(counterparty_eu=True, choices=_choices(doc_type="WNT"))
    )
    assert [item["name"] for item in decree["registers"]] == [
        "Rejestr naliczony WNT",
        "Rejestr należny WNT",
    ]
    assert decree["registers"][0]["service"] is False


def test_import_correction_swaps_sides() -> None:
    decree = _compute(
        _import_input(
            net=Decimal("-100.00"),
            gross=Decimal("-100.00"),
            choices=_choices(doc_type="IU"),
        )
    )
    assert decree["negative"] is True
    assert [item["side"] for item in decree["positions"]] == [
        "credit",
        "debit",
        "credit",
        "debit",
    ]


def test_import_from_a_polish_counterparty_or_with_vat_is_reported() -> None:
    decree = _compute(
        _import_input(counterparty_foreign=False, choices=_choices(doc_type="IU"))
    )
    assert any("z Polski" in problem for problem in decree["problems"])
    decree = _compute(
        _import_input(
            vat=Decimal("230.00"),
            gross=Decimal("1230.00"),
            choices=_choices(doc_type="IU"),
        )
    )
    assert any("VAT od sprzedawcy" in problem for problem in decree["problems"])


def test_import_in_pln_has_no_currency_amounts() -> None:
    decree = _compute(
        _import_input(
            currency="PLN", fx_rate=None, fx_date=None, choices=_choices(doc_type="IU")
        )
    )
    assert decree["problems"] == []
    assert _sides(decree)[2] == ("vat", "221", "debit", 23_000)
    assert decree["registers"][0]["net_cur"] is None


# ── Waluta ───────────────────────────────────────────────────────────────────


def test_currency_without_rate_blocks_with_the_chosen_day() -> None:
    decree = _compute(_input(currency="EUR", fx_rate=None, fx_date=date(2026, 10, 29)))
    assert "Brak kursu NBP EUR z dnia 29.10.2026" in decree["problems"]


def test_currency_amounts_follow_each_position() -> None:
    decree = _compute(
        _input(
            currency="EUR",
            fx_rate=Decimal("4.0000"),
            fx_date=date(2026, 11, 3),
            choices=_choices(fx_table="213/A/NBP/2026"),
        )
    )
    assert decree["problems"] == []
    assert [item["amount_cur"] for item in decree["positions"]] == [
        100_001,
        23_001,
        123_002,
    ]
    assert decree["registers"][0]["gross"] == 492_008


# ── Wybory: odmowy i ręczna korekta ──────────────────────────────────────────


@pytest.mark.parametrize(
    "values",
    [
        {"doc_type": "XYZ"},
        {"register": "Sprzedaż"},
        {"vat_account": "222"},
        {"output_vat_account": "221"},
        {"jpk_procedure": "GTU_01"},
        {"fx_table": "kwiecień"},
        {"fx_rate": "-1"},
        {"fx_date": "2026-13-01"},
        {"import_rate": "7"},
    ],
)
def test_bad_choices_are_refused(values) -> None:
    with pytest.raises(options.ChoiceError):
        _choices(**values)


def test_manual_decree_keeps_registers_and_parallel_flag() -> None:
    computed = _compute(_input(choices=_choices(allocation_account="510-5")))
    body = {
        "register": "purchase",
        "doc_type": "FVZ",
        "description": "Opis",
        "positions": [
            {"kind": item["kind"], "account": item["account"], "side": item["side"],
             "amount": posting.money(item["amount"])}
            for item in computed["positions"]
        ],
    }  # fmt: skip
    manual = posting.manual_decree(body, PLAN, previous=computed, now=NOW)
    assert manual["registers"] == computed["registers"]
    assert manual["choices"] == computed["choices"]
    assert [item["parallel"] for item in manual["positions"]] == [
        False, False, False, True, True,
    ]  # fmt: skip


def test_manual_decree_checks_the_5_account_kind() -> None:
    body = {
        "register": "purchase",
        "doc_type": "FVZ",
        "positions": [
            {"kind": "allocation", "account": "402-215", "side": "debit", "amount": "1"},
            {"kind": "allocation_offset", "account": "490", "side": "credit",
             "amount": "1"},
        ],
    }  # fmt: skip
    with pytest.raises(LedgerError):
        posting.manual_decree(body, PLAN, previous=None, now=NOW)


def test_import_amount_check_compares_the_source_gross_not_the_net() -> None:
    decree = _compute(_import_input(choices=_choices(doc_type="IU")))
    # Rozrachunek = netto po kursie, VAT liczy nabywca — to nie jest zmiana kwot.
    assert posting.amount_issue(decree, Decimal("1000.00"), "EUR") is None
    assert posting.amount_issue(decree, Decimal("1100.00"), "EUR") == (
        posting.AMOUNTS_CHANGED
    )


def test_manual_decree_with_other_amounts_drops_car_registers() -> None:
    computed = _compute(_input(choices=_choices(car=True)))
    body = {
        "register": "purchase",
        "doc_type": "FVZ",
        "description": "Opis",
        "positions": [
            {"kind": "cost", "account": "402-203", "side": "debit", "amount": "1000.01"},
            {"kind": "vat", "account": "221", "side": "debit", "amount": "230.01"},
            {"kind": "counterparty", "account": "201-2-4321", "side": "credit",
             "amount": "1230.02"},
        ],
    }  # fmt: skip
    manual = posting.manual_decree(body, PLAN, previous=computed, now=NOW)
    assert "registers" not in manual and "car" not in manual
    assert manual["choices"] == computed["choices"]
