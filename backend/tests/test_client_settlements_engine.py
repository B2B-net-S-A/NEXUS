"""Silnik rozliczenia E1: MD, nadgodziny, MD wdrożeniowe, brak MD, stawki.

Liczby z przykładu BNP z roadmapy (17 dni + 4,75 MD pracy dodatkowej × 120%),
stawki zmyślone, ale o tej samej skali.
"""

from __future__ import annotations

from decimal import Decimal as D

from app.services.client_settlements import rules_catalog
from app.services.client_settlements.engine import Inputs, OrderState, compute


def _rules(**overrides: dict) -> dict:
    stored = {
        "extra.multiplier": {"level": "warn", "params": {"pct": "120"}},
        "order.no_md_holds_invoice": {"level": "block", "params": {}},
        "order.onboarding_md": {"level": "off", "params": {"md": "2"}},
    }
    stored.update(overrides)
    return rules_catalog.effective(stored)


def _order(
    available: str | None = "32.5",
    cost: str | None = "1000",
    revenue: str | None = "1100",
) -> OrderState:
    return OrderState(
        order_id=1,
        number="ZAM_1_2026",
        md_total=D("220"),
        md_available=None if available is None else D(available),
        rate_cost=None if cost is None else D(cost),
        rate_revenue=None if revenue is None else D(revenue),
    )


def test_bez_md_czeka_na_liczbe():
    r = compute(Inputs(md_regular=None, md_extra=None, rules=_rules(), order=_order()))
    assert r.status == "checking"
    assert r.md_charged is None and r.amount_cost is None


def test_nadgodziny_z_mnoznikiem_w_koszcie_przychodzie_i_zejsciu():
    r = compute(
        Inputs(
            md_regular=D("17"),
            md_extra=D("4.75"),
            rules=_rules(),
            order=_order(),
            has_report=True,
        )
    )
    assert r.md_charged == D("22.700")
    assert r.md_remaining_after == D("9.800")
    assert r.amount_cost == D("22700.00")
    assert r.amount_revenue == D("24970.00")
    assert r.status == "ok"
    assert [line["label"] for line in r.lines] == ["Dni zwykłe", "Praca dodatkowa"]


def test_bez_pliku_rcp_ostrzega():
    r = compute(
        Inputs(md_regular=D("20"), md_extra=None, rules=_rules(), order=_order())
    )
    assert r.status == "warnings"


def test_md_wdrozeniowe_przechodza_na_kolejny_miesiac():
    rules = _rules(**{"order.onboarding_md": {"level": "block", "params": {"md": "2"}}})
    first = compute(
        Inputs(
            md_regular=D("1.5"),
            md_extra=None,
            rules=rules,
            order=_order(),
            has_report=True,
        )
    )
    assert first.md_onboarding == D("1.500")
    assert first.md_charged == D("0.000")
    assert first.amount_cost == D("1500.00")  # konsultant fakturuje pełną ilość
    assert first.amount_revenue == D("0.00")  # klient płaci 0 zł za MD wdrożeniowe
    second = compute(
        Inputs(
            md_regular=D("20"),
            md_extra=None,
            rules=rules,
            order=_order(),
            onboarding_used_before=D("1.5"),
            has_report=True,
        )
    )
    assert second.md_onboarding == D("0.500")
    assert second.md_charged == D("19.500")
    third = compute(
        Inputs(
            md_regular=D("20"),
            md_extra=None,
            rules=rules,
            order=_order(),
            onboarding_used_before=D("2"),
            has_report=True,
        )
    )
    assert third.md_onboarding == D("0.000")
    assert third.md_charged == D("20.000")


def test_brak_linii_zamowienia_blokuje_przy_poziomie_blokuje():
    r = compute(
        Inputs(
            md_regular=D("20"),
            md_extra=None,
            rules=_rules(),
            order=None,
            has_report=True,
        )
    )
    assert r.status == "no_md"
    assert r.amount_cost is None


def test_brak_linii_przy_ostrzezeniu_i_wylaczonej_regule():
    warn = compute(
        Inputs(
            md_regular=D("20"),
            md_extra=None,
            rules=_rules(**{"order.no_md_holds_invoice": {"level": "warn"}}),
            order=None,
            has_report=True,
        )
    )
    assert warn.status == "warnings"
    off = compute(
        Inputs(
            md_regular=D("20"),
            md_extra=None,
            rules=_rules(**{"order.no_md_holds_invoice": {"level": "off"}}),
            order=None,
            has_report=True,
        )
    )
    assert off.status == "ok"


def test_za_malo_md_na_zamowieniu_przyjmuje_do_wysokosci_puli():
    """Rozliczenia 10.11.2026: nie „nie wystawiaj”, tylko „zafakturuj tyle, ile
    zostało”; nadwyżka czeka na decyzję Finansów, bez obietnicy zamówienia."""
    r = compute(
        Inputs(
            md_regular=D("21"),
            md_extra=D("1"),
            rules=_rules(),
            order=_order(available="20"),
            has_report=True,
        )
    )
    assert r.status == "warnings"
    assert r.md_charged == D("20.000") and r.md_over == D("2.200")
    assert r.md_remaining_after == D("0.000")
    assert r.amount_cost == D("20000.00") and r.amount_revenue == D("22000.00")
    titles = [c["title"] for g in r.checks for c in g["checks"]]
    assert "Ponad zamówienie o 2,2 MD" in titles


def test_pusta_pula_nadal_brak_md():
    r = compute(
        Inputs(
            md_regular=D("5"),
            md_extra=None,
            rules=_rules(),
            order=_order(available="0"),
            has_report=True,
        )
    )
    assert r.status == "no_md" and r.md_charged == D("0.000")


def test_klient_bez_regul_liczy_bez_mnoznika_i_bez_blokad():
    r = compute(
        Inputs(
            md_regular=D("20"),
            md_extra=D("2"),
            rules=rules_catalog.effective(None),
            order=None,
            has_report=True,
        )
    )
    assert r.md_charged == D("22.000")
    assert r.status == "ok"


def test_brak_stawki_daje_ostrzezenie_i_puste_kwoty():
    r = compute(
        Inputs(
            md_regular=D("20"),
            md_extra=None,
            rules=_rules(),
            order=_order(cost=None),
            has_report=True,
        )
    )
    assert r.status == "warnings"
    assert r.amount_cost is None
    assert r.amount_revenue == D("22000.00")


def test_md_wdrozeniowe_tylko_dla_nowego_konsultanta():
    """Konsultant pracujący od dawna nie dostaje 2 MD za 0 zł tylko dlatego,
    że nie ma jeszcze rozliczeń w NEXUS-ie (błąd znaleziony na kopii 09.11)."""

    rules = _rules(**{"order.onboarding_md": {"level": "block", "params": {"md": "2"}}})
    r = compute(
        Inputs(
            md_regular=D("20"),
            md_extra=None,
            rules=rules,
            order=_order(),
            has_report=True,
            onboarding_eligible=False,
        )
    )
    assert r.md_onboarding == D("0")
    assert r.md_charged == D("20.000")


def test_nowy_konsultant_to_start_w_tym_albo_poprzednim_miesiacu():
    from datetime import date
    from types import SimpleNamespace

    from app.services.client_settlements.service import _onboarding_eligible

    def contract(start):
        return SimpleNamespace(start_date=start)

    assert _onboarding_eligible(contract(date(2026, 10, 15)), "2026-10")
    assert _onboarding_eligible(contract(date(2026, 9, 20)), "2026-10")
    assert not _onboarding_eligible(contract(date(2026, 8, 31)), "2026-10")
    assert not _onboarding_eligible(contract(None), "2026-10")
    assert _onboarding_eligible(contract(date(2025, 12, 1)), "2026-01")
