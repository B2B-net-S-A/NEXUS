"""Rozliczenie ponad zamówienie i stawka linii: odczyt, kontrola, bez bazy.

Dane fikcyjne (osoby, numery, stawki). Układ jak w próbie IX–X 2026: część
miesiąca na zamówieniu zakończonym w NEXUS-ie, część ponad pulę, a linia
z inną stawką niż kontrakt i ostatnia faktura za tę osobę.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.client_settlements import line_rate, order_issues
from app.services.client_settlements.engine import OrderState, Result


def _settlement(
    meta: dict, *, order_id: int | None = 7, md: str = "20"
) -> SimpleNamespace:
    return SimpleNamespace(
        checks=[{"title": "RCP", "checks": []}, {"remaining_after": None, **meta}],
        order_id=order_id,
        md_regular=Decimal(md),
        status="warnings",
    )


def _line(rate: str | None, order_id: int = 7) -> OrderState:
    return OrderState(
        order_id=order_id,
        number="ZAM-1",
        md_total=Decimal("40"),
        md_available=Decimal("10"),
        rate_cost=Decimal("500"),
        rate_revenue=None if rate is None else Decimal(rate),
    )


def _result(status: str = "ok") -> Result:
    return Result(status, None, Decimal("10"), None, None, None, [], [])


# ── problemy z zamówieniem w zapisanym przeliczeniu ───────────────────────────


def test_jedno_zamowienie_ponad_pule_to_jeden_problem() -> None:
    issues = order_issues.issues_of(_settlement({"md_over": "6.375"}))
    assert issues == [
        order_issues.OrderIssue(order_issues.OVER, 7, None, Decimal("6.375"))
    ]


def test_pula_wystarcza_brak_problemu() -> None:
    assert order_issues.issues_of(_settlement({"md_over": None})) == []
    assert order_issues.issues_of(_settlement({})) == []


def test_podzial_zamkniete_i_ponad_pule_osobno_na_kazde_zamowienie() -> None:
    meta = {
        "orders": [
            {
                "order_id": 1,
                "number": "A",
                "md": "6",
                "remaining_after": "-6",
                "closed": True,
            },
            {
                "order_id": 2,
                "number": "B",
                "md": "16",
                "remaining_after": "-15",
                "closed": False,
            },
            {
                "order_id": 3,
                "number": "C",
                "md": "2",
                "remaining_after": "8",
                "closed": False,
            },
        ],
        # Przy podziale nadwyżka nie idzie do ``md_over``: liczą się części.
        "md_over": "99",
    }
    issues = order_issues.issues_of(_settlement(meta))
    assert [(i.kind, i.order_id, i.md) for i in issues] == [
        (order_issues.CLOSED, 1, Decimal("6")),
        (order_issues.OVER, 2, Decimal("15")),
    ]


def test_podzial_w_puli_brak_problemu_mimo_md_over() -> None:
    meta = {
        "orders": [{"order_id": 3, "number": "C", "md": "2", "remaining_after": "8"}],
        "md_over": "5",
    }
    assert order_issues.issues_of(_settlement(meta)) == []


def test_przeliczenie_tylko_rozliczen_z_problemem_zamowienia() -> None:
    assert order_issues.needs_refresh(_settlement({"md_over": "2"}))
    assert order_issues.needs_refresh(_settlement({}, order_id=None))
    assert not order_issues.needs_refresh(_settlement({}))
    rate = {line_rate.META_KEY: [{"order_id": 7, "line": "900.00"}]}
    assert order_issues.needs_refresh(_settlement(rate))
    no_md = _settlement({})
    no_md.md_regular = None
    assert not order_issues.needs_refresh(no_md)


def test_okno_miesiecy_jak_automat() -> None:
    assert order_issues.month_floor(date(2026, 11, 24)) == "2026-08"
    assert order_issues.month_floor(date(2026, 2, 3)) == "2025-11"


# ── stawka linii a kontrakt i ostatnia faktura ────────────────────────────────


def _invoice(price: str, *, prices: tuple[str, ...] = (), hourly: bool = False):
    return line_rate.InvoicePrice(
        number="FS 1/2026",
        period="2026-09",
        prices=tuple(Decimal(p) for p in (prices or (price,))),
        main=Decimal(price),
        hourly=hourly,
    )


def test_stawka_jak_kontrakt_i_faktura_bez_uwagi() -> None:
    ref = line_rate.Reference(
        contract=Decimal("900"),
        invoice=_invoice("900"),
        contract_at_invoice=Decimal("900"),
    )
    assert line_rate.judge(_line("900"), ref) is None


def test_stawka_nizsza_niz_kontrakt_i_faktura_uwaga() -> None:
    ref = line_rate.Reference(
        contract=Decimal("900"),
        invoice=_invoice("900"),
        contract_at_invoice=Decimal("900"),
    )
    found = line_rate.judge(_line("850"), ref)
    assert found == {
        "order_id": 7,
        "number": "ZAM-1",
        "line": "850.00",
        "contract": "900.00",
        "invoice": "900.00",
        "invoice_number": "FS 1/2026",
        "invoice_period": "2026-09",
    }


def test_sama_faktura_inna_daje_uwage() -> None:
    ref = line_rate.Reference(contract=None, invoice=_invoice("900"))
    found = line_rate.judge(_line("850"), ref)
    assert found is not None and found["contract"] is None
    assert found["invoice"] == "900.00"


def test_kontrakt_godzinowy_zaokraglenie_do_4_zl_bez_uwagi() -> None:
    ref = line_rate.Reference(contract=Decimal("944"), contract_hourly=True)
    assert line_rate.judge(_line("945"), ref) is None
    ref_daily = line_rate.Reference(contract=Decimal("944"))
    assert line_rate.judge(_line("945"), ref_daily) is not None


def test_faktura_sprzed_podwyzki_w_kontrakcie_nie_jest_wzorem() -> None:
    ref = line_rate.Reference(
        contract=Decimal("950"),
        invoice=_invoice("900"),
        contract_at_invoice=Decimal("900"),
    )
    assert line_rate.judge(_line("950"), ref) is None


def test_faktura_z_nadgodzinami_wystarczy_jedna_zgodna_cena() -> None:
    ref = line_rate.Reference(invoice=_invoice("900", prices=("900", "1080")))
    assert line_rate.judge(_line("900"), ref) is None


def test_linia_bez_stawki_bez_uwagi() -> None:
    ref = line_rate.Reference(contract=Decimal("900"))
    assert line_rate.judge(_line(None), ref) is None


def _sales(number: str, period: tuple[int, int], items: list[dict], currency="PLN"):
    return SimpleNamespace(
        invoice_number=number,
        period_year=period[0],
        period_month=period[1],
        currency=currency,
        items=items,
    )


def test_cena_z_najnowszej_faktury_z_ta_osoba_i_jednostka_czasu() -> None:
    invoices = [
        # Najnowsza wymienia inną osobę.
        _sales(
            "FS 3",
            (2026, 10),
            [
                {
                    "name": "Usługi, Inna Osoba",
                    "unit": "MD",
                    "quantity": "5",
                    "unit_price": "700",
                }
            ],
        ),
        # Pozycja w sztukach nie mówi, za ile MD jest cena.
        _sales(
            "FS 2",
            (2026, 9),
            [
                {
                    "name": "Usługi, Jan Testowy",
                    "unit": "szt.",
                    "quantity": "1",
                    "unit_price": "18000",
                }
            ],
        ),
        _sales(
            "FS 1",
            (2026, 8),
            [
                {
                    "name": "Usługi, Jan Testowy",
                    "unit": "godz.",
                    "quantity": "160",
                    "unit_price": "110",
                },
                {
                    "name": "Nadgodziny, Jan Testowy",
                    "unit": "godz.",
                    "quantity": "8",
                    "unit_price": "132",
                },
            ],
        ),
    ]
    found = line_rate.invoice_price(invoices, "Jan Testowy")
    assert found is not None
    assert (found.number, found.period, found.main, found.hourly) == (
        "FS 1",
        "2026-08",
        Decimal("880"),
        True,
    )
    assert found.prices == (Decimal("880"), Decimal("1056"))


def test_faktura_w_euro_i_pozycja_przed_korekta_pomijane() -> None:
    invoices = [
        _sales(
            "FS E",
            (2026, 10),
            [
                {
                    "name": "Jan Testowy",
                    "unit": "MD",
                    "quantity": "5",
                    "unit_price": "200",
                }
            ],
            "EUR",
        ),
        _sales(
            "FS K",
            (2026, 9),
            [
                {
                    "name": "Jan Testowy",
                    "unit": "MD",
                    "quantity": "5",
                    "unit_price": "800",
                    "before_correction": True,
                },
                {
                    "name": "Jan Testowy",
                    "unit": "MD",
                    "quantity": "5",
                    "unit_price": "900",
                },
            ],
        ),
    ]
    found = line_rate.invoice_price(invoices, "Jan Testowy")
    assert (
        found is not None
        and found.number == "FS K"
        and found.prices == (Decimal("900"),)
    )


def test_uwaga_zmienia_bez_uwag_na_z_uwagami_i_zapisuje_rozjazd() -> None:
    item = line_rate.judge(_line("850"), line_rate.Reference(contract=Decimal("900")))
    result = line_rate.with_mismatches(_result("ok"), [item])
    assert result.status == "warnings"
    group = result.checks[-1]
    assert group["title"] == line_rate.GROUP_TITLE
    assert group["checks"][0]["state"] == "warn"
    assert "kontrakt 900 zł/MD" in group["checks"][0]["detail"]
    assert result.meta[line_rate.META_KEY][0]["order_id"] == 7
    # Bez rozjazdu wynik bez zmian; inny status niż „ok” zostaje.
    assert line_rate.with_mismatches(_result("ok"), []) == _result("ok")
    assert line_rate.with_mismatches(_result("no_md"), [item]).status == "no_md"


def test_faktura_godzinowa_tolerancja_grosza_nie_pol_zlotego() -> None:
    # 0,50 zł/h różnicy (4 zł/MD) to inna stawka, nie zaokrąglenie.
    off = line_rate.Reference(invoice=_invoice("900", hourly=True))
    assert line_rate.judge(_line("904"), off) is not None
    # Cena godzinowa z groszami × 8 h: do 0,10 zł/MD.
    near = line_rate.Reference(invoice=_invoice("945.04", hourly=True))
    assert line_rate.judge(_line("945"), near) is None


def test_uwagi_o_zamowieniu_maja_stale_klucze_rule() -> None:
    from app.services.client_settlements import engine
    from app.services.client_settlements.engine import Inputs, SplitPart, compute
    from app.services.client_settlements import rules_catalog

    rules = rules_catalog.effective(
        {"order.no_md_holds_invoice": {"level": "warn", "params": {}}}
    )
    over = compute(
        Inputs(
            md_regular=Decimal("15"),
            md_extra=None,
            rules=rules,
            order=_line("900"),
            has_report=True,
            onboarding_eligible=False,
        )
    )
    keys = {c.get("rule") for g in over.checks for c in g["checks"]}
    assert engine.RULE_MD_OVER in keys
    closed = compute(
        Inputs(
            md_regular=Decimal("10"),
            md_extra=None,
            rules=rules,
            order=_line("900"),
            has_report=True,
            onboarding_eligible=False,
            split=(
                SplitPart(_line("900", order_id=1), Decimal("4"), closed=True),
                SplitPart(_line("900", order_id=2), Decimal("6")),
            ),
        )
    )
    keys = {c.get("rule") for g in closed.checks for c in g["checks"]}
    assert engine.RULE_ORDER_CLOSED in keys
