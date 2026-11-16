"""Rabat od pełnej kwoty, przeliczenie obrotu kursem NBP i marża per konsultant.

Decyzje Artura 16.11.2026: rabat liczy się od pełnej kwoty obrotu (po
przekroczeniu progu stawka wyższego progu dotyczy całego obrotu); faktury
w innej walucie niż progi przeliczamy kursem średnim NBP z dnia przed
wystawieniem. Wzór Cost z modelu marży Nordei (raport H1 2026).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.client_reports.generators.annual_spend import (
    compute_rebate,
    convert_turnover,
    fx_day,
)
from app.services.client_reports.generators.client_data import InvoiceRow
from app.services.client_reports.generators.margin_per_consultant import (
    ConsultantRate,
    MarginAssumptions,
    consultant_cost,
    margin_rows,
    portfolio_margin,
    run_rate,
)
from app.services.client_reports.registry import clean_params, get_generator

TIERS = [{"up_to": 15_000_000, "rate": 2.5}, {"up_to": None, "rate": 3}]
H1 = MarginAssumptions()


def invoice(amount: str, currency: str = "PLN", issued: date = date(2026, 8, 4)):
    return InvoiceRow("FV/1", "VAT", None, issued, issued, currency, Decimal(amount))


# ------------------------------------------------------ rabat od pełnej kwoty


def test_turnover_just_above_threshold_takes_higher_rate_on_whole_turnover():
    turnover = Decimal("15000000.01")
    rebate = compute_rebate(turnover, TIERS)
    assert rebate.rate == Decimal("3")
    assert rebate.amount == Decimal("450000.00")  # 3% × cały obrót, nie 2,5% + 0,5%
    assert len(rebate.bands) == 1 and rebate.bands[0].base == turnover


def test_rebate_param_defaults_to_full_amount():
    spec = {p.key: p for p in get_generator("annual_spend").params}["marginal"]
    assert spec.default is False


# ------------------------------------------------------- przeliczenie kursem


def test_fx_day_is_day_before_issue():
    assert fx_day(date(2026, 8, 4)) == date(2026, 8, 3)


def test_pln_invoices_converted_to_tier_currency_at_nbp_rate():
    day = fx_day(date(2026, 8, 4))
    rates = {day: {"PLN": Decimal(1), "EUR": Decimal("4.25")}}
    result = convert_turnover(
        [invoice("4250000.00"), invoice("1000.00", "EUR")], "EUR", rates
    )
    assert result.amount == Decimal("1001000.00")
    assert result.converted == 1 and result.missing == ()


def test_invoice_without_rate_is_left_out_and_reported():
    result = convert_turnover([invoice("100.00", "USD")], "EUR", {})
    assert result.amount == 0
    assert result.missing == ("USD",)


def test_correction_lowers_converted_turnover():
    day = fx_day(date(2026, 8, 4))
    rates = {day: {"PLN": Decimal(1), "EUR": Decimal("4")}}
    result = convert_turnover([invoice("400"), invoice("-40")], "EUR", rates)
    assert result.amount == Decimal("90.00")


def test_same_currency_needs_no_rate():
    result = convert_turnover([invoice("10.00")], "PLN", {})
    assert (result.amount, result.converted, result.missing) == (
        Decimal("10.00"),
        0,
        (),
    )


# ---------------------------------------------------------------- wzór Cost


def test_cost_matches_h1_example():
    # 220 + 648/168 + 50% × (231 − 220 − 648/168) = 227,43 → 227
    assert consultant_cost(Decimal(220), Decimal(231), H1) == Decimal(227)


def test_cost_rounds_half_up_like_excel():
    flat = MarginAssumptions(monthly_cost=Decimal(84), hours=Decimal(168))
    # 100 + 0,5 + 50% × (101 − 100,5) = 100,75 → 101; 100 + 0,5 + 0 = 100,5 → 101
    assert consultant_cost(Decimal(100), Decimal(101), flat) == Decimal(101)
    assert consultant_cost(Decimal(100), Decimal(100), flat) == Decimal(101)


def test_cost_share_never_negative():
    # stawka Nordei poniżej kosztu: MAX(0; …) — sam koszt konsultanta i narzut
    assert consultant_cost(Decimal(200), Decimal(150), H1) == Decimal(204)


# ------------------------------------------------------------------ marża


def person(name: str, k: str, d: str, role: str | None = "IT Developer - Senior"):
    return ConsultantRate(1, name, role, Decimal(k), Decimal(d))


def test_margin_after_rebate_and_portfolio_per_head():
    rows = margin_rows(
        [person("A", "220", "231"), person("B", "100", "200")], Decimal(3), H1
    )
    a, b = rows
    assert a.after_rebate == Decimal("224.07")
    assert a.margin == ((Decimal("224.07") - 227) / Decimal("224.07")).quantize(
        Decimal("0.0001")
    )
    assert a.margin < 0
    # każda osoba raz: (ΣE − ΣCost) / ΣE
    total_e = a.after_rebate + b.after_rebate
    expected = ((total_e - a.cost - b.cost) / total_e).quantize(Decimal("0.0001"))
    assert portfolio_margin(rows) == expected


def test_portfolio_margin_empty_is_none():
    assert portfolio_margin([]) is None


def test_run_rate_projects_year_from_covered_days():
    # 01.07–30.09 = 92 dni z faktur; rok 2026 = 365 dni
    assert run_rate(Decimal(920), date(2026, 7, 1), date(2026, 9, 30)) == Decimal(
        "3650.00"
    )
    assert run_rate(Decimal(920), date(2026, 9, 30), date(2026, 7, 1)) is None


def test_margin_params_validated():
    generator = get_generator("margin_per_consultant")
    assert generator.needs_amounts and generator.needs_client_rate
    cleaned = clean_params(
        generator,
        {"tiers": TIERS, "currency": "EUR", "monthly_cost": 648, "hours": 168},
    )
    assert cleaned["monthly_cost"] == 648 and cleaned["currency"] == "EUR"
    assert "marginal" not in {p.key for p in generator.params}
