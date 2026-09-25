"""Okno „Zużycie MD" (ticket 7, 25.09.2026) — saldo, numer z importu, korekty.

Czyste funkcje ``app.services.md_consumption_view``; liczby zmyślone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.services.finance_order_matching import build_order_number_index
from app.services.md_consumption_view import (
    ConsumptionIn,
    CorrectionEventIn,
    ImportRefIn,
    build_consumption_view,
    is_foreign_number,
    same_order_number,
)

D = Decimal

CLIENT = 901
# Klient z numerami SAP (same cyfry, ≥ 7) — długi ciąg w „Uwagach" wiąże.
NUMBERS = build_order_number_index([(CLIENT, "4500030197"), (CLIENT, "445")])
SCOPE = {"client_id": CLIENT, "order_numbers": NUMBERS}


def _at(minute: int) -> datetime:
    return datetime(2026, 9, 24, 12, minute, tzinfo=timezone.utc)


def test_balance_after_each_month_ends_at_todays_remaining():
    view = build_consumption_view(
        [
            ConsumptionIn("2026-07", D("23"), "import"),
            ConsumptionIn("2026-08", D("21"), "import"),
            ConsumptionIn("2026-06", D("1"), "manual"),
        ],
        remaining=D("-20"),
        import_refs={},
        corrections=[],
        order_number="4500030197",
        **SCOPE,
    )
    assert view.months["2026-08"].balance_after == D("-20")
    assert view.months["2026-07"].balance_after == D("1")
    assert view.months["2026-06"].balance_after == D("24")
    assert view.used == D("45")


def test_import_number_and_foreign_row_warning():
    view = build_consumption_view(
        [ConsumptionIn("2026-08", D("21"), "import")],
        remaining=D("-19"),
        import_refs={
            "2026-08": [
                ImportRefIn(2, 35, "4500030197", D("2")),
                ImportRefIn(2, 36, "4500030845", D("19")),
            ]
        },
        corrections=[],
        order_number="4500030197",
        **SCOPE,
    )
    refs = view.months["2026-08"].import_rows
    assert [(r.order_number_hint, r.foreign) for r in refs] == [
        ("4500030197", False),
        ("4500030845", True),
    ]
    ((month, ref),) = view.foreign
    assert month == "2026-08" and ref.md_reported == D("19")


def test_corrections_sit_under_their_month_and_mark_the_source():
    view = build_consumption_view(
        [ConsumptionIn("2026-08", D("3.7"), "manual")],
        remaining=D("5.963"),
        import_refs={"2026-08": [ImportRefIn(2, 12, "4500030197", D("4"))]},
        corrections=[
            CorrectionEventIn(
                _at(23),
                "Anna Przykładowa",
                {"period_month": "2026-08", "previous": "4", "md_reported": "3.7"},
            ),
            CorrectionEventIn(
                _at(24),
                "Anna Przykładowa",
                {"period_month": "2026-08", "previous": "3.7", "md_reported": "3.7"},
            ),
        ],
        order_number="4500030197",
        **SCOPE,
    )
    month = view.months["2026-08"]
    assert month.source_kind == "manual_correction"
    first, second = month.corrections
    assert (first.from_source, first.from_md, first.to_md) == (
        "import",
        D("4"),
        D("3.7"),
    )
    assert (second.from_source, second.from_md) == ("manual", D("3.7"))


def test_manual_entry_without_import_is_plain_manual():
    view = build_consumption_view(
        [ConsumptionIn("2026-05", D("10"), "manual")],
        remaining=D("40"),
        import_refs={},
        corrections=[
            CorrectionEventIn(
                _at(1),
                "Anna Przykładowa",
                {"period_month": "2026-05", "previous": "0", "md_reported": "10"},
            )
        ],
        order_number="445",
        **SCOPE,
    )
    month = view.months["2026-05"]
    assert month.source_kind == "manual"
    (correction,) = month.corrections
    assert correction.from_source == "none" and correction.from_md is None


def test_removed_month_corrections_are_listed_separately():
    view = build_consumption_view(
        [],
        remaining=D("50"),
        import_refs={},
        corrections=[
            CorrectionEventIn(
                _at(5),
                None,
                {"period_month": "2026-04", "removed_md": "8"},
            )
        ],
        order_number="445",
        **SCOPE,
    )
    (removed,) = view.removed
    assert (
        removed.removed
        and removed.from_md == D("8")
        and removed.period_month == "2026-04"
    )


def test_foreign_number_compares_digits_only():
    assert not is_foreign_number("SAP 4500030197", "4500030197", **SCOPE)
    assert not is_foreign_number(None, "4500030197", **SCOPE)
    assert is_foreign_number("4500030845", "4500030197", **SCOPE)
    assert not is_foreign_number("0087020188", "87020188", **SCOPE)
    # Zawieranie się cyfr to NIE ten sam numer — ale obcy jest wyłącznie
    # numer, który reguła wiązania uznaje za numer zamówienia klienta.
    assert is_foreign_number("4450012345", "445", **SCOPE)
    assert not is_foreign_number("2026", "OIT/0189/2026/ITVM", **SCOPE)
    other = build_order_number_index([(CLIENT, "OIT/0189/2026/ITVM"), (CLIENT, "2026")])
    assert is_foreign_number(
        "2026", "OIT/0189/2026/ITVM", client_id=CLIENT, order_numbers=other
    )
    assert not is_foreign_number("4500030197", "Zamówienie MD", **SCOPE)


def test_same_order_number_is_exact():
    assert same_order_number("SAP 4500030197", "4500030197")
    assert not same_order_number("2026", "OIT/0189/2026/ITVM")
    assert not same_order_number("4450012345", "445")
    assert not same_order_number("123", "Zamówienie MD")
    assert not same_order_number(None, "445")
