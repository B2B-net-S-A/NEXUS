"""Silnik rozliczenia: podział miesiąca na zamówienia z maila klienta. Bez bazy.

Układ jak w próbie IX–X 2026: tabela klienta „osoba × numer SAP” (trzy
zamówienia bez puli MD, jedno z inną stawką) i linie „<numer>: 40h” (zamówienie
zakończone w NEXUS-ie i drugie z pulą na wyczerpaniu). Numery i stawki zmyślone.
"""

from __future__ import annotations

from decimal import Decimal as D

from app.services.client_settlements import rules_catalog
from app.services.client_settlements.engine import (
    Inputs,
    OrderState,
    SplitPart,
    compute,
)


def _rules(**overrides: dict) -> dict:
    stored = {
        "order.no_md_holds_invoice": {"level": "warn", "params": {}},
        "order.onboarding_md": {"level": "off", "params": {"md": "2"}},
    }
    stored.update(overrides)
    return rules_catalog.effective(stored)


def _order(
    order_id: int,
    number: str,
    *,
    available: str | None = None,
    cost: str | None = "500",
    revenue: str | None = "800",
) -> OrderState:
    return OrderState(
        order_id=order_id,
        number=number,
        md_total=None if available is None else D("40"),
        md_available=None if available is None else D(available),
        rate_cost=None if cost is None else D(cost),
        rate_revenue=None if revenue is None else D(revenue),
    )


A = _order(11, "SAP 4500011111")
B = _order(12, "SAP 4500022222", revenue="700")
C = _order(13, "SAP 4500033333")


def _inputs(md: str, split: tuple[SplitPart, ...], **kw) -> Inputs:
    return Inputs(
        md_regular=D(md),
        md_extra=kw.pop("md_extra", None),
        rules=kw.pop("rules", _rules()),
        order=kw.pop("order", C),
        has_report=True,
        split=split,
        **kw,
    )


def _titles(result) -> list[str]:
    return [c["title"] for g in result.checks for c in g["checks"]]


def test_trzy_zamowienia_bez_puli_linia_i_stawka_kazdego():
    r = compute(
        _inputs(
            "22",
            (SplitPart(A, D("7")), SplitPart(B, D("1.75")), SplitPart(C, D("13.25"))),
        )
    )

    assert r.status == "ok"
    assert r.md_charged == D("22.000")
    assert [(line["label"], line["md"], line["order_id"]) for line in r.lines] == [
        ("Dni zwykłe, zamówienie SAP 4500011111", "7.000", 11),
        ("Dni zwykłe, zamówienie SAP 4500022222", "1.750", 12),
        ("Dni zwykłe, zamówienie SAP 4500033333", "13.250", 13),
    ]
    # Koszt 22 × 500; przychód 7 × 800 + 1,75 × 700 + 13,25 × 800.
    assert r.amount_cost == D("11000.00")
    assert r.amount_revenue == D("17425.00")
    assert [(o["order_id"], o["md"], o["main"]) for o in r.orders] == [
        (11, "7.000", False),
        (12, "1.750", False),
        (13, "13.250", True),
    ]
    assert r.orders[1]["amount_revenue"] == "1225.00"
    assert r.md_over is None and r.md_remaining_after is None
    assert "Podział według maila klienta" in _titles(r)


def test_zamowienie_zakonczone_i_ponad_pule_ida_jak_w_mailu_z_uwaga():
    closed = _order(21, "4500044444", available="0")
    almost = _order(22, "4500055555", available="1")
    r = compute(
        _inputs(
            "22",
            (SplitPart(closed, D("5"), closed=True), SplitPart(almost, D("17"))),
            order=almost,
        )
    )

    # Decyzja Artura z 24.11.2026: bez blokady i bez nadwyżki czekającej na Finanse.
    assert r.status == "warnings"
    assert r.md_charged == D("22.000")
    assert r.md_over is None
    assert r.amount_revenue == D("17600.00")
    assert [(o["order_id"], o["md"], o["remaining_after"]) for o in r.orders] == [
        (21, "5.000", "-5.000"),
        (22, "17.000", "-16.000"),
    ]
    assert r.md_remaining_after == D("-16.000")  # zamówienie z większą częścią
    titles = _titles(r)
    assert "Zamówienie zakończone w NEXUS-ie" in titles
    assert "Ponad pulę zamówienia o 16 MD" in titles
    assert not any("Ponad zamówienie, bez zapłaty" == line["label"] for line in r.lines)


def test_blokujaca_regula_puli_nie_blokuje_podzialu():
    closed = _order(21, "4500044444", available="0")
    rules = _rules(**{"order.no_md_holds_invoice": {"level": "block", "params": {}}})
    r = compute(
        _inputs("5", (SplitPart(closed, D("5"), closed=True),), rules=rules, order=None)
    )

    assert r.status == "warnings"
    assert r.md_charged == D("5.000")


def test_inna_suma_niz_md_rozliczenia_idzie_na_jedno_zamowienie():
    r = compute(_inputs("22", (SplitPart(A, D("7")), SplitPart(B, D("14")))))

    assert r.orders == ()
    assert r.status == "warnings"
    assert [line["label"] for line in r.lines] == ["Dni zwykłe"]
    assert r.amount_revenue == D("17600.00")  # 22 × stawka zamówienia rozliczenia
    assert "Podział z maila klienta nie wszedł" in _titles(r)


def test_praca_dodatkowa_wylacza_podzial():
    r = compute(
        _inputs(
            "20",
            (SplitPart(A, D("10")), SplitPart(B, D("10"))),
            md_extra=D("2"),
            rules=_rules(
                **{"extra.multiplier": {"level": "warn", "params": {"pct": "120"}}}
            ),
        )
    )

    assert r.orders == ()
    assert "Podział z maila klienta nie wszedł" in _titles(r)


def test_zamowienie_bez_stawki_daje_uwage_i_brak_kwot():
    no_rate = _order(14, "SAP 4500066666", cost=None, revenue=None)
    r = compute(_inputs("10", (SplitPart(A, D("4")), SplitPart(no_rate, D("6")))))

    assert r.status == "warnings"
    assert r.amount_cost is None and r.amount_revenue is None
    assert r.orders[0]["amount_revenue"] == "3200.00"
    assert r.orders[1]["amount_revenue"] is None
    assert "Linia zamówienia bez stawki MD" in _titles(r)


def test_pula_wystarcza_zostaje_reszta():
    pooled = _order(15, "4500077777", available="30")
    r = compute(_inputs("12", (SplitPart(pooled, D("12")),), order=pooled))

    assert r.status == "ok"
    assert r.md_remaining_after == D("18.000")
    assert "Zejdzie 12 MD, zostanie 18 MD" in _titles(r)


def test_reszta_z_zaokraglenia_idzie_na_glowne_zamowienie():
    # 12,5 h + 163,5 h = 176 h = 22 MD; części po 3 miejscach dałyby 22,001 MD.
    r = compute(
        _inputs("22", (SplitPart(A, D("12.5") / 8), SplitPart(B, D("163.5") / 8)))
    )

    assert [o["md"] for o in r.orders] == ["1.563", "20.437"]
    assert sum(D(o["md"]) for o in r.orders) == r.md_charged == D("22.000")
    assert r.amount_cost == D("11000.00")  # 22 × 500, jak na jednym zamówieniu


def test_jednostka_tabeli_raz_dla_calej_tabeli():
    from app.services.client_settlements import order_split, service

    split = order_split.Split(
        kind=order_split.TABLE,
        rows=(
            order_split.Row(
                "Testowy Jan", (order_split.Part("4500011111", D("16"), None),)
            ),
            order_split.Row(
                "Inna Anna", (order_split.Part("4500011111", D("176"), None),)
            ),
        ),
        month="2026-09",
        subject="",
        author="",
        approved=False,
    )
    # Bez MD rozliczenia: 176 w jednym wierszu to godziny, więc w całej tabeli.
    assert service._row_unit(split, split.rows[0], None, D("8")) == order_split.HOURS
    # Przy MD rozliczenia decyduje suma wiersza osoby.
    assert service._row_unit(split, split.rows[0], D("2"), D("8")) == order_split.HOURS
    assert service._row_unit(split, split.rows[0], D("16"), D("8")) == order_split.MD


def test_podzial_z_pul_ma_wlasny_tytul_i_bez_uwagi():
    old = _order(21, "ZAM-STARE", available="10")
    new = _order(22, "ZAM-NOWE", available="40", revenue="900")
    r = compute(
        _inputs(
            "15", (SplitPart(old, D("10")), SplitPart(new, D("5"))), split_auto=True
        )
    )

    assert r.status == "ok"
    assert "Podział na kolejne zamówienia kontraktu" in _titles(r)
    assert "Podział według maila klienta" not in _titles(r)
    assert [o["md"] for o in r.orders] == ["10.000", "5.000"]


def test_podzial_z_pul_przy_pracy_dodatkowej_wraca_po_cichu_na_jedno_zamowienie():
    old = _order(21, "ZAM-STARE", available="10")
    new = _order(22, "ZAM-NOWE", available="40")
    r = compute(
        _inputs(
            "15",
            (SplitPart(old, D("10")), SplitPart(new, D("5"))),
            split_auto=True,
            md_extra=D("1"),
            order=new,
        )
    )

    assert not r.orders
    assert "Podział z maila klienta nie wszedł" not in _titles(r)
