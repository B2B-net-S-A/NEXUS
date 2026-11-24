"""Czyste przeliczenia generatorów katalogu raportów klienta (bez bazy)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.client_reports.generators.annual_spend import (
    compute_rebate,
    turnover_by_currency,
)
from app.services.client_reports.generators.annual_statistics import format_md
from app.services.client_reports.generators.client_data import (
    NO_ROLE,
    InvoiceRow,
    MdRow,
    OrderRow,
    invoice_type_label,
    md_grouped,
    order_label,
    order_mode,
    order_unit_price,
    order_value,
    period_months,
    sheet_amount,
    totals_by_currency,
)
from app.services.client_reports.generators.contract_realisation import specialists
from app.services.client_reports.generators.engagement import (
    ContractSpan,
    engagements,
    invoices_by_month,
    roles_count,
    team_summary,
    tenure_months,
)
from app.services.client_reports.generators.orders_quarterly import (
    orders_checks,
    order_sheet_row,
)
from app.services.client_reports.registry import (
    all_generators,
    clean_params,
    get_generator,
)
from app.services.client_reports.schedule import Period

Q3 = Period("2026-Q3", date(2026, 7, 1), date(2026, 9, 30), "III kwartał 2026")


def _order(**kw) -> OrderRow:
    base = dict(
        order_id=1,
        order_number=None,
        title=None,
        description=None,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 12, 31),
        order_type=None,
        rate_unit="hourly",
        total_value=None,
        md_total=None,
        md_rate_revenue=None,
        rate_client=None,
        currency="PLN",
        project=None,
        person=None,
    )
    base.update(kw)
    return OrderRow(**base)


def _invoice(net: str, currency: str = "PLN", **kw) -> InvoiceRow:
    base = dict(
        invoice_number="F/1",
        invoice_type="VAT",
        invoice_kind="original",
        issue_date=date(2026, 8, 5),
        service_month=date(2026, 7, 1),
        currency=currency,
        net_amount=Decimal(net),
    )
    base.update(kw)
    return InvoiceRow(**base)


# ----------------------------------------------------------------- rejestr


def test_registry_has_new_generators_with_amount_permission():
    keys = {g.key for g in all_generators()}
    new = {
        "orders_quarterly",
        "engagement_report",
        "annual_statistics",
        "contract_realisation_annual",
        "annual_spend",
    }
    assert new <= keys
    assert all(get_generator(k).needs_amounts for k in new)
    assert get_generator("orders_quarterly").needs_client_rate


def test_annual_spend_params_validated_by_registry():
    generator = get_generator("annual_spend")
    cleaned = clean_params(
        generator,
        {
            "tiers": [{"up_to": 100, "rate": 2}, {"up_to": None, "rate": 3}],
            "marginal": True,
            "obce": 1,
        },
    )
    assert cleaned == {
        "tiers": [{"up_to": 100.0, "rate": 2.0}, {"up_to": None, "rate": 3.0}],
        "marginal": True,
    }
    with pytest.raises(ValueError):
        clean_params(generator, {"tiers": [{"up_to": 100, "rate": 150}]})
    with pytest.raises(ValueError):
        clean_params(generator, {"marginal": "tak"})


# --------------------------------------------------------------- zamówienia


def test_order_value_prefers_total_then_md_budget():
    assert (
        order_value(
            _order(
                total_value=Decimal("1000"),
                md_total=Decimal(5),
                md_rate_revenue=Decimal(10),
            )
        )
        == 1000
    )
    assert order_value(
        _order(md_total=Decimal("12.5"), md_rate_revenue=Decimal("800"))
    ) == Decimal("10000")
    assert order_value(_order(md_total=Decimal(5))) is None
    assert order_value(_order()) is None


def test_order_value_zero_total_is_kept():
    assert (
        order_value(
            _order(
                total_value=Decimal(0), md_total=Decimal(5), md_rate_revenue=Decimal(10)
            )
        )
        == 0
    )


@pytest.mark.parametrize(
    ("order_type", "expected"),
    [("cost", "ryczałt"), ("md", "T&M"), ("periodic", "T&M"), (None, "T&M")],
)
def test_order_mode(order_type, expected):
    assert order_mode(order_type) == expected


def test_unit_price_md_uses_revenue_rate_per_md():
    order = _order(
        order_type="md",
        rate_unit="hourly",
        md_rate_revenue=Decimal(900),
        rate_client=Decimal(100),
    )
    assert order_unit_price(order) == (Decimal(900), "MD")


def test_unit_price_periodic_uses_client_rate_with_unit():
    assert order_unit_price(
        _order(order_type="periodic", rate_client=Decimal(150))
    ) == (Decimal(150), "godz.")
    assert order_unit_price(
        _order(rate_unit="monthly", rate_client=Decimal(20000))
    ) == (Decimal(20000), "mies.")
    assert order_unit_price(
        _order(rate_unit="daily", md_rate_revenue=Decimal(700))
    ) == (Decimal(700), "MD")
    assert order_unit_price(_order()) == (None, None)


def test_order_label_falls_back_to_title_then_id():
    assert order_label(_order(order_number="Z/1", title="T")) == "Z/1"
    assert order_label(_order(title="T")) == "T"
    assert order_label(_order(order_id=7)) == "zamówienie 7"


def test_order_sheet_row_keeps_amounts_numeric():
    row = order_sheet_row(
        _order(
            order_type="md",
            md_total=Decimal("10"),
            md_rate_revenue=Decimal("812.345"),
            person="A B",
        )
    )
    assert row[2] == "T&M"
    assert row[5] == 8123.45 and isinstance(row[5], float)
    assert row[7] == 812.35
    assert row[8] == "MD"


def test_orders_checks_count_missing_values():
    checks = orders_checks(
        [_order(), _order(total_value=Decimal(1), project="P", person="X")]
    )
    assert any(c.startswith("1 zleceń bez wartości") for c in checks)
    assert any("bez nazwy projektu" in c for c in checks)
    assert orders_checks([]) == []


def test_totals_by_currency_skips_missing_and_normalises():
    totals = totals_by_currency(
        [
            ("pln", Decimal(10)),
            ("PLN", Decimal("5.5")),
            ("EUR", Decimal(1)),
            ("EUR", None),
            (None, Decimal(2)),
        ]
    )
    assert totals == {"EUR": Decimal(1), "PLN": Decimal("15.5"), "—": Decimal(2)}
    assert totals_by_currency([]) == {}


def test_sheet_amount_rounds_half_up():
    assert sheet_amount(Decimal("0.005")) == 0.01
    assert sheet_amount(None) is None


# --------------------------------------------------------------- miesiące


def test_period_months_calendar_quarter():
    assert period_months(date(2026, 7, 1), date(2026, 9, 30)) == [
        "2026-07",
        "2026-08",
        "2026-09",
    ]


def test_period_months_contract_year_has_no_double_month():
    months = period_months(date(2026, 2, 27), date(2027, 2, 26))
    assert months[0] == "2026-03" and months[-1] == "2027-02" and len(months) == 12


def test_period_months_across_year_and_short_period():
    assert period_months(date(2026, 12, 1), date(2027, 1, 31)) == ["2026-12", "2027-01"]
    assert period_months(date(2026, 11, 10), date(2026, 11, 16)) == []


# --------------------------------------------------------------- MD


def test_md_grouped_by_role_with_missing_role():
    rows = [
        MdRow(1, "A", "Tester", Decimal(10)),
        MdRow(2, "B", None, Decimal(4)),
        MdRow(3, "C", "Tester", Decimal("2.5")),
        MdRow(4, "D", "Analityk", Decimal(0)),
    ]
    assert md_grouped(rows, "role") == [
        ("Tester", Decimal("12.5")),
        (NO_ROLE, Decimal(4)),
    ]
    assert md_grouped([], "role") == []


def test_specialists_split_by_role_and_skip_zero():
    rows = [
        MdRow(1, "A", "Tester", Decimal(10)),
        MdRow(2, "A", "Tester", Decimal(5)),
        MdRow(3, "A", None, Decimal(1)),
        MdRow(4, "B", "Dev", Decimal(0)),
    ]
    assert specialists(rows) == [
        ("A", "Tester", Decimal(15)),
        ("A", NO_ROLE, Decimal(1)),
    ]


def test_format_md_drops_zero_fraction():
    assert format_md(Decimal("1234")) == "1 234"
    assert format_md(Decimal("12.5")) == "12,50"


# --------------------------------------------------------------- zaangażowanie


def _span(
    cid: int, start: date, end: date | None, role: str | None = "Dev"
) -> ContractSpan:
    return ContractSpan(cid, f"Osoba {cid}", start, end, role, None)


def test_engagement_merges_renewals_and_counts_moves():
    spans = [
        _span(1, date(2025, 1, 1), date(2026, 6, 30)),  # przedłużenie — nie „weszła”
        _span(1, date(2026, 7, 1), None, "Lead"),
        _span(2, date(2026, 8, 1), None),  # weszła
        _span(3, date(2025, 3, 1), date(2026, 8, 15)),  # odeszła
        _span(
            4, date(2026, 1, 1), date(2026, 9, 30)
        ),  # koniec w ostatnim dniu — jest na koniec
        _span(5, date(2025, 1, 1), date(2026, 6, 30)),  # przed okresem — poza raportem
    ]
    people = engagements(spans, Q3)
    assert [p.person for p in people] == ["Osoba 1", "Osoba 2", "Osoba 3", "Osoba 4"]
    first = people[0]
    assert (
        first.start_date == date(2025, 1, 1)
        and first.end_date is None
        and first.role == "Lead"
    )
    summary = team_summary(people, Q3)
    assert (summary.at_end, summary.joined, summary.left) == (3, 1, 1)
    assert summary.at_end + summary.left == len(people)


def test_engagement_tenure_capped_at_period_end():
    people = engagements([_span(1, date(2026, 7, 1), date(2027, 6, 30))], Q3)
    assert people[0].tenure_months == tenure_months(date(2026, 7, 1), Q3.end) == 3.0


def test_team_summary_empty():
    summary = team_summary([], Q3)
    assert (summary.at_end, summary.joined, summary.left, summary.avg_tenure) == (
        0,
        0,
        0,
        None,
    )


def test_roles_count_sorted_and_missing_role():
    people = engagements(
        [
            _span(1, date(2026, 1, 1), None),
            _span(2, date(2026, 1, 1), None),
            _span(3, date(2026, 1, 1), None, None),
        ],
        Q3,
    )
    assert roles_count(people) == [("Dev", 2), (NO_ROLE, 1)]


def test_invoices_by_month_groups_currency_and_corrections():
    invoices = [
        _invoice("1000"),
        _invoice("-200", invoice_type="KOR", invoice_kind="correction"),
        _invoice("50", "EUR"),
        _invoice("300", service_month=date(2026, 8, 1)),
    ]
    assert invoices_by_month(invoices) == [
        (date(2026, 7, 1), "EUR", 1, Decimal(50)),
        (date(2026, 7, 1), "PLN", 2, Decimal(800)),
        (date(2026, 8, 1), "PLN", 1, Decimal(300)),
    ]
    assert invoices_by_month([]) == []


def test_invoice_type_label():
    assert invoice_type_label(_invoice("1")) == "faktura"
    assert (
        invoice_type_label(_invoice("1", invoice_type="VAT", invoice_kind="correction"))
        == "korekta"
    )
    assert invoice_type_label(_invoice("1", invoice_type="ZAL")) == "zaliczkowa"


# --------------------------------------------------------------- rabat


# Progi i stawki fikcyjne: warunki z umów klientów są tylko w ustawieniach.
TIERS = [{"up_to": 12_000_000.0, "rate": 1.5}, {"up_to": None, "rate": 3.5}]


def test_turnover_includes_corrections_per_currency():
    turnovers = turnover_by_currency(
        [
            _invoice("1000"),
            _invoice("-250", invoice_kind="correction"),
            _invoice("100", "eur"),
        ]
    )
    assert [(t.currency, t.count, t.corrections, t.net) for t in turnovers] == [
        ("EUR", 1, 0, Decimal(100)),
        ("PLN", 2, 1, Decimal(750)),
    ]
    assert turnover_by_currency([]) == []


def test_rebate_without_tiers_is_none():
    assert compute_rebate(Decimal(1000), []) is None


def test_rebate_whole_turnover_at_tier_rate():
    low = compute_rebate(Decimal(10_000_000), TIERS)
    assert (low.rate, low.amount) == (Decimal("1.5"), Decimal("150000.00"))
    high = compute_rebate(Decimal(20_000_000), TIERS)
    assert (high.rate, high.amount, high.above_top) == (
        Decimal("3.5"),
        Decimal("700000.00"),
        False,
    )


def test_rebate_boundary_belongs_to_lower_tier():
    at_bound = compute_rebate(Decimal(12_000_000), TIERS)
    assert at_bound.rate == Decimal("1.5")
    assert compute_rebate(Decimal("12000000.01"), TIERS).rate == Decimal("3.5")


def test_rebate_marginal_splits_turnover():
    result = compute_rebate(Decimal(20_000_000), TIERS, marginal=True)
    assert [(b.base, b.amount) for b in result.bands] == [
        (Decimal(12_000_000), Decimal("180000.00")),
        (Decimal(8_000_000), Decimal("280000.00")),
    ]
    assert result.amount == Decimal("460000.00")
    assert result.rate == Decimal("2.3000")


def test_rebate_marginal_below_first_bound_single_band():
    result = compute_rebate(Decimal(1000), TIERS, marginal=True)
    assert len(result.bands) == 1 and result.amount == Decimal("15.00")


def test_rebate_tiers_order_does_not_matter():
    reversed_tiers = list(reversed(TIERS))
    assert compute_rebate(Decimal(20_000_000), reversed_tiers) == compute_rebate(
        Decimal(20_000_000), TIERS
    )


def test_rebate_above_top_without_open_tier_uses_last_rate():
    tiers = [{"up_to": 100.0, "rate": 1.0}, {"up_to": 200.0, "rate": 2.0}]
    flat = compute_rebate(Decimal(300), tiers)
    assert (flat.rate, flat.amount, flat.above_top) == (
        Decimal("2.0"),
        Decimal("6.00"),
        True,
    )
    assert flat.bands[0].lower == Decimal(100)
    marginal = compute_rebate(Decimal(300), tiers, marginal=True)
    assert marginal.amount == Decimal("1.00") + Decimal("4.00") and marginal.above_top


def test_rebate_negative_or_zero_turnover_gives_zero():
    assert compute_rebate(Decimal(-500), TIERS).amount == 0
    zero = compute_rebate(Decimal(0), TIERS, marginal=True)
    assert zero.amount == 0 and zero.bands == ()


def test_rebate_rounds_to_cents():
    assert compute_rebate(
        Decimal("333.33"), [{"up_to": None, "rate": 3.5}]
    ).amount == Decimal("11.67")


def test_workbook_keeps_numbers_numeric():
    from io import BytesIO

    from openpyxl import load_workbook

    from app.services.client_reports.registry import Sheet, build_tabular_workbook

    row = order_sheet_row(
        _order(
            order_number="Z/1", total_value=Decimal("1234.5"), rate_client=Decimal(100)
        )
    )
    content = build_tabular_workbook(
        (Sheet("Zestawienie Zleceń", ("a",) * len(row), (row,), note="uwaga"),), "T"
    )
    ws = load_workbook(BytesIO(content))["Zestawienie Zleceń"]
    values = [cell.value for cell in ws[5]]
    assert values[0] == "Z/1" and values[5] == 1234.5 and values[7] == 100


def test_annual_spend_flags_period_older_than_ksef_invoices():
    from datetime import date

    from app.services.client_reports.generators.annual_spend import incomplete_from

    assert incomplete_from(date(2026, 8, 4), date(2026, 1, 1))
    assert not incomplete_from(date(2026, 1, 20), date(2026, 1, 1))
    assert not incomplete_from(date(2025, 3, 1), date(2026, 1, 1))


def test_headcount_counts_people_not_contracts():
    from datetime import date

    from app.services.client_reports.generators.common import ContractInPeriod
    from app.services.client_reports.generators.headcount import people_in_period

    def row(contract_id, candidate_id, start, end):
        return ContractInPeriod(
            contract_id,
            "Osoba",
            start,
            end,
            None,
            None,
            "Z1",
            None,
            None,
            None,
            candidate_id,
        )

    rows = [
        row(
            1, 7, date(2026, 1, 1), date(2026, 10, 15)
        ),  # zmiana stawki w połowie miesiąca
        row(2, 7, date(2026, 10, 16), None),
        row(3, 8, date(2026, 10, 20), None),  # weszła w październiku
        row(4, 9, date(2025, 1, 1), date(2026, 10, 31)),  # skończyła 31.10
    ]
    people, started, ended = people_in_period(
        rows, date(2026, 10, 1), date(2026, 10, 31)
    )
    assert (people, started, ended) == (3, 1, 1)
