"""Środki trwałe (K6) bez bazy: dokument AM (Wn 401 z MPK / Ma 070-071 i podział
na „5”), zapisy OT, ulepszenia, likwidacji i sprzedaży, MPK po zmianie (MT),
import ewidencji z Symfonii po aliasach nagłówków. Kwoty i konta fikcyjne."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.ledger_assets import LedgerAsset
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.counterparty_import import ImportFileError
from app.services.ledger import assets, assets_import
from app.services.ledger.allocation import Mpk
from app.services.ledger.settings import AllocationAccounts, AssetsAccounts

ACCOUNTS = AssetsAccounts(
    cost_account="401", intake_account="080", disposal_account="761"
)
ALLOCATION = AllocationAccounts(
    settlement_account="490",
    client_account="501",
    front_office_account="502",
    back_office_account="503",
    overhead_account="550",
    team_account="504",
)
LABELS = {
    "FO": Mpk("FO", "front_office", "Front office"),
    "OG": Mpk("OG", "overhead", "Koszty ogólne"),
    "K7": Mpk("K7", "client", "Klient Testowy"),
}


def _lines(spec):
    return [(line.side, line.account, line.amount, line.mpk) for line in spec.lines]


def test_am_document_posts_cost_by_mpk_depreciation_by_account_and_split():
    items = [
        assets.AmItem(asset_id=3, account="070", mpk="OG", amount=92_250),
        assets.AmItem(asset_id=1, account="070", mpk="FO", amount=50_000),
        assets.AmItem(asset_id=2, account="071", mpk="OG", amount=10_000),
        assets.AmItem(asset_id=4, account="070", mpk="K7", amount=1_000),
    ]
    spec, problems = assets.depreciation_spec(
        date(2026, 10, 1), items, ACCOUNTS, ALLOCATION, LABELS
    )
    assert problems == []
    assert (spec.doc_type, spec.op_date, spec.source_type, spec.source_id) == (
        "AM",
        date(2026, 10, 31),
        "assets_month",
        "2026-10",
    )
    assert _lines(spec) == [
        ("debit", "401", 50_000, "FO"),
        ("debit", "401", 1_000, "K7"),
        ("debit", "401", 102_250, "OG"),
        ("credit", "070", 143_250, None),
        ("credit", "071", 10_000, None),
        ("debit", "502", 50_000, "FO"),
        ("debit", "501", 1_000, "K7"),
        ("debit", "550", 102_250, "OG"),
        ("credit", "490", 153_250, None),
    ]
    debit = sum(line.amount for line in spec.lines if line.side == "debit")
    credit = sum(line.amount for line in spec.lines if line.side == "credit")
    assert debit == credit == 2 * 153_250
    # Rozbicie na środki (posortowane) — trwały zapis tego, co zatwierdzono.
    assert spec.meta["assets"] == [
        [1, 50_000, "FO", "070"],
        [2, 10_000, "OG", "071"],
        [3, 92_250, "OG", "070"],
        [4, 1_000, "K7", "070"],
    ]
    assert spec.meta["detail_hash"]
    assert spec.description == "Amortyzacja 10.2026 — 4 środki"


def test_am_needs_cost_and_split_accounts():
    items = [assets.AmItem(asset_id=1, account="070", mpk="OG", amount=100)]
    spec, problems = assets.depreciation_spec(
        date(2026, 10, 1),
        items,
        AssetsAccounts(cost_account="", intake_account="080", disposal_account=""),
        AllocationAccounts(),
        LABELS,
    )
    assert spec is None
    assert assets.NO_COST_ACCOUNT in problems and assets.NO_ALLOCATION in problems
    assert len(problems) == len(set(problems))


def test_am_without_amounts_is_nothing():
    assert assets.depreciation_spec(
        date(2026, 10, 1), [], ACCOUNTS, ALLOCATION, LABELS
    ) == (None, [])


def test_detail_hash_changes_when_assets_swap_amounts():
    first = [
        assets.AmItem(asset_id=1, account="070", mpk="OG", amount=100),
        assets.AmItem(asset_id=2, account="070", mpk="OG", amount=200),
    ]
    swapped = [
        assets.AmItem(asset_id=1, account="070", mpk="OG", amount=200),
        assets.AmItem(asset_id=2, account="070", mpk="OG", amount=100),
    ]
    a, _ = assets.depreciation_spec(
        date(2026, 10, 1), first, ACCOUNTS, ALLOCATION, LABELS
    )
    b, _ = assets.depreciation_spec(
        date(2026, 10, 1), swapped, ACCOUNTS, ALLOCATION, LABELS
    )
    assert _lines(a) == _lines(b)
    assert a.meta["detail_hash"] != b.meta["detail_hash"]


def _asset(**values):
    data = {
        "id": 9,
        "inventory_number": "ST/2026/001",
        "name": "Stacje robocze",
        "kind": "fixed",
        "accepted_on": date(2026, 1, 10),
        "initial_value": 2_400_000,
        "asset_account": "010",
        "depreciation_account": "070",
        "mpk": "OG",
        "balance_method": "linear",
        "balance_rate": Decimal("25"),
        "tax_method": "linear",
        "tax_rate": Decimal("25"),
        "coefficient": Decimal("2.0"),
        "opening_month": None,
        "opening_balance": 0,
        "opening_tax": 0,
        "opening_balance_year": None,
        "opening_tax_year": None,
        "disposed_on": None,
    }
    data.update(values)
    return SimpleNamespace(**data)


def _op(op_id: int, op_type: str, day: date, **values):
    data = {
        "id": op_id,
        "op_type": op_type,
        "op_date": day,
        "number": f"{op_type} {op_id}/{day.year}",
        "title": "ST/2026/001 Stacje robocze",
        "amount": None,
        "counter_account": None,
        "mpk_from": None,
        "mpk_to": None,
    }
    data.update(values)
    return SimpleNamespace(**data)


def test_intake_and_improvement_post_asset_against_intake_account():
    asset = _asset()
    intake = _op(1, "OT", date(2026, 1, 10), amount=2_400_000, counter_account="080")
    spec, problems = assets.operation_spec(intake, asset, [intake], ACCOUNTS)
    assert problems == []
    assert (spec.doc_type, spec.number, spec.source_id) == ("PK", "OT 1/2026", "1")
    assert _lines(spec) == [
        ("debit", "010", 2_400_000, None),
        ("credit", "080", 2_400_000, None),
    ]
    assert spec.description == "OT 1/2026 — ST/2026/001 Stacje robocze"
    improvement = _op(2, "UL", date(2026, 4, 2), amount=50_000, counter_account="080-1")
    spec, _ = assets.operation_spec(improvement, asset, [intake, improvement], ACCOUNTS)
    assert _lines(spec) == [
        ("debit", "010", 50_000, None),
        ("credit", "080-1", 50_000, None),
    ]


def test_liquidation_writes_off_value_with_depreciation_through_its_month():
    asset = _asset(status="liquidated", disposed_on=date(2026, 9, 20))
    intake = _op(1, "OT", date(2026, 1, 10), amount=2_400_000, counter_account="080")
    liquidation = _op(2, "LT", date(2026, 9, 20))
    spec, problems = assets.operation_spec(
        liquidation, asset, [intake, liquidation], ACCOUNTS
    )
    assert problems == []
    # Odpisy 02–09.2026 po 500 zł = 4 000 zł; netto 20 000 zł na 761.
    assert _lines(spec) == [
        ("debit", "070", 400_000, None),
        ("debit", "761", 2_000_000, None),
        ("credit", "010", 2_400_000, None),
    ]
    assert spec.op_date == date(2026, 9, 20)


def test_sale_of_fully_depreciated_asset_has_no_net_value_line():
    asset = _asset(
        balance_method="one_off", status="sold", disposed_on=date(2026, 6, 1)
    )
    intake = _op(1, "OT", date(2026, 1, 10), amount=2_400_000, counter_account="080")
    sale = _op(2, "SP", date(2026, 6, 1), amount=100_000)
    spec, _ = assets.operation_spec(
        sale, asset, [intake, sale], AssetsAccounts(disposal_account="")
    )
    assert _lines(spec) == [
        ("debit", "070", 2_400_000, None),
        ("credit", "010", 2_400_000, None),
    ]


def test_liquidation_with_net_value_needs_disposal_account():
    asset = _asset(status="liquidated", disposed_on=date(2026, 3, 5))
    liquidation = _op(2, "LT", date(2026, 3, 5))
    spec, problems = assets.operation_spec(
        liquidation, asset, [liquidation], AssetsAccounts(disposal_account="")
    )
    assert spec is None and problems == [assets.NO_DISPOSAL_ACCOUNT]


def test_mpk_follows_transfers_from_their_month():
    asset = _asset(mpk="BO")
    moves = [
        _op(2, "MT", date(2026, 5, 20), mpk_from="OG", mpk_to="FO"),
        _op(3, "MT", date(2026, 8, 1), mpk_from="FO", mpk_to="BO"),
    ]
    assert assets.mpk_in(asset, moves, date(2026, 4, 1)) == "OG"
    assert assets.mpk_in(asset, moves, date(2026, 5, 1)) == "FO"
    assert assets.mpk_in(asset, moves, date(2026, 7, 1)) == "FO"
    assert assets.mpk_in(asset, moves, date(2026, 8, 1)) == "BO"
    assert assets.mpk_in(_asset(mpk="OG"), [], date(2026, 1, 1)) == "OG"


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("FO", ("front_office", None)),
        ("BO", ("back_office", None)),
        ("OG", ("overhead", None)),
        ("K12", ("client", 12)),
        ("K", None),
        ("ZARZAD", None),
        ("k12", None),
    ],
)
def test_mpk_codes(code, kind):
    assert assets.mpk_kind(code) == kind


@pytest.mark.parametrize(
    ("count", "word"),
    [
        (1, "1 środek"),
        (2, "2 środki"),
        (5, "5 środków"),
        (12, "12 środków"),
        (22, "22 środki"),
    ],
)
def test_assets_word(count, word):
    assert assets.assets_word(count) == word


# ── Import z Symfonii ŚT ─────────────────────────────────────────────────────


def _csv(*rows: str) -> bytes:
    return ("\n".join(rows) + "\n").encode("utf-8")


def test_import_recognises_symfonia_headers_and_values():
    content = _csv(
        "Ewidencja środków trwałych;;;;;;;;;",
        "Numer inwentarzowy;Nazwa;Symbol KŚT;Data przyjęcia;Wartość początkowa;"
        "Umorzenie bilansowe;Umorzenie podatkowe;Metoda amortyzacji;"
        "Stawka bilansowa %;Stawka podatkowa %;Konto umorzenia;MPK;Stan",
        "ST/2024/001;Serwer plików;491;05.02.2024;24 600,00;19 680,00;19 680,00;"
        "liniowa;30;30;070;og;używany",
        "WNiP/2024/001;Licencja systemu;;2024-01-15;28000;28000;28000;L;0,5;50;071;FO;",
        "ST/2020/004;Stary laptop;491;2020-03-01;4 000,00;4 000,00;4 000,00;liniowa;"
        "30;30;070;OG;zlikwidowany",
        ";;;;;;;;;;;;",
    )
    parsed = assets_import.parse(content)
    assert parsed.skipped_disposed == 1
    first, second = parsed.rows
    assert first.errors == [] and second.errors == []
    assert first.values["inventory_number"] == "ST/2024/001"
    assert first.values["accepted_on"] == date(2024, 2, 5)
    assert first.values["initial_value"] == 2_460_000
    assert first.values["balance_accumulated"] == 1_968_000
    assert first.values["balance_method"] == "linear"
    assert first.values["balance_rate"] == Decimal("30.00")
    assert first.values["depreciation_account"] == "070"
    assert first.values["mpk"] == "OG"
    assert second.values["balance_rate"] == Decimal("50.00")  # 0,5 z Excela = 50%
    assert second.values["kst"] is None
    assert parsed.columns["tax_rate"] == "Stawka podatkowa %"


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("Umorzenie", "balance_accumulated"),
        ("Umorzenie podatkowe", "tax_accumulated"),
        ("Umorzenie bilansowe na początek roku", "balance_year"),
        ("Konto", "asset_account"),
        ("Konto umorzenia", "depreciation_account"),
        ("Wartość netto", None),
        ("Stawka", "balance_rate"),
        ("Metoda amortyzacji podatkowej", "tax_method"),
        ("Data likwidacji", "disposed_on"),
    ],
)
def test_header_aliases_prefer_the_longest_match(header, field):
    assert assets_import.match_header(header) == field


def test_import_reports_row_errors_without_failing_the_file():
    content = _csv(
        "Nazwa;Data przyjęcia;Wartość początkowa;Metoda;Stawka",
        "Monitor;31.02.2026;1 000,00;liniowa;20",
        "Biurko;2026-01-10;abc;sprytna;250",
    )
    first, second = assets_import.parse(content).rows
    assert first.errors == ["Brak albo niepoprawna data przyjęcia."]
    assert any("Wartość początkowa" in error for error in second.errors)
    assert any("Nieznana metoda" in error for error in second.errors)
    assert any("Niepoprawna stawka" in error for error in second.errors)


def test_import_needs_header_and_some_assets():
    with pytest.raises(ImportFileError):
        assets_import.parse(_csv("Kolumna A;Kolumna B", "1;2"))
    with pytest.raises(ImportFileError):
        assets_import.parse(
            _csv(
                "Nazwa;Data przyjęcia;Wartość początkowa;Stan",
                "Auto;2020-01-01;1;sprzedany",
            )
        )


@pytest.mark.parametrize(
    ("raw", "method"),
    [
        ("Liniowa", "linear"),
        ("degresywna", "degressive"),
        ("D", "degressive"),
        ("Jednorazowa", "one_off"),
        ("Nie amortyzuje się", "none"),
        ("brak", "none"),
        ("?", None),
    ],
)
def test_method_words(raw, method):
    assert assets_import.parse_method(raw) == method


def test_import_defaults_follow_kind_and_balance_plan():
    values = assets_import._asset_values(
        {
            "name": "Licencja",
            "accepted_on": date(2025, 3, 1),
            "initial_value": 100_000,
            "asset_account": "020",
            "balance_method": "linear",
            "balance_rate": Decimal("50"),
            "balance_accumulated": 40_000,
            "tax_accumulated": None,
            "balance_year": None,
            "tax_year": None,
        },
        date(2026, 10, 1),
    )
    assert values["kind"] == "intangible" and values["kst"] is None
    assert (values["tax_method"], values["tax_rate"]) == ("linear", Decimal("50"))
    assert values["opening"] == {
        "month": date(2026, 10, 1),
        "balance": 40_000,
        "tax": 40_000,
        "balance_year": None,
        "tax_year": None,
    }
    assert values["mpk"] == "OG"


def test_import_rejects_non_numeric_coefficient():
    # Przegląd K6: „NaN” przechodził jako współczynnik i dawał 500 w podglądzie.
    row = assets_import._row(
        {
            "name": "Laptop",
            "accepted_on": "2025-03-10",
            "initial_value": "6000,00",
            "kst": "491",
            "balance_rate": "30",
            "coefficient": "NaN",
        },
        2,
    )
    assert any("współczynnik" in error for error in row.errors)


def test_plan_validation_refuses_non_finite_numbers():
    probe = LedgerAsset(
        kind="fixed",
        kst="491",
        accepted_on=date(2025, 3, 10),
        initial_value=600_000,
        balance_method="linear",
        balance_rate=Decimal("30"),
        tax_method="linear",
        tax_rate=Decimal("30"),
        coefficient=Decimal("NaN"),
        opening_month=None,
        opening_balance=0,
        opening_tax=0,
        opening_balance_year=None,
        opening_tax_year=None,
    )
    with pytest.raises(LedgerError) as caught:
        assets.validate_plan(probe)
    assert caught.value.status == 422
