"""Koszt z dwóch stawek kontraktora w jednym miesiącu (próba IX–X 2026). Bez bazy.

Harmonogram kontraktu zmienił stawkę w trakcie miesiąca, a linia zamówienia ma
jedną stawkę. Kontraktor fakturuje dni przed zmianą starą stawką, od zmiany nową.
Stawki i godziny fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from app.services.client_settlements import rate_split
from app.services.client_settlements.engine import Inputs, OrderState, compute
from app.services.client_settlements.rate_split import CostPart

SEPT_FIRST, SEPT_LAST = date(2026, 9, 1), date(2026, 9, 30)
#: Wrzesień 2026 po 8 h w dni robocze, 28.09 wolne: 21 dni, 168 h. RCP BNP ma
#: 31 kolumn, więc ostatnia to 1. dzień następnego miesiąca.
WORKDAYS = {1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 21, 22, 23, 24, 25, 29, 30}
HOURS = tuple(D("8") if day in WORKDAYS else D("0") for day in range(1, 32))
STEPS = [(date(2026, 3, 17), D("120")), (date(2026, 9, 17), D("126"))]


def _segments(*parts: tuple[int, str]) -> list[tuple[date, D]]:
    return [(date(2026, 9, day), D(rate)) for day, rate in parts]


# ── zmiana stawki w harmonogramie ────────────────────────────────────────────


def test_zmiana_w_srodku_miesiaca():
    assert rate_split.changes(STEPS, SEPT_FIRST, SEPT_LAST) == [
        rate_split.Change(date(2026, 9, 17), D("120"), D("126"))
    ]


def test_zmiana_pierwszego_dnia_to_jedna_stawka_na_miesiac():
    steps = [(date(2026, 3, 17), D("120")), (date(2026, 9, 1), D("126"))]
    assert rate_split.changes(steps, SEPT_FIRST, SEPT_LAST) == []
    assert rate_split.rate_on(steps, SEPT_FIRST) == D("126")


def test_pierwszy_krok_przy_starcie_kontraktu_to_nie_zmiana():
    """Kontrakt zaczęty 29.10 ma jedyny krok 29.10: stawka przed nim jest ta sama
    (jak ``Contract.effective_candidate_rate``), więc bez uwagi „? → 50”."""

    steps = [(date(2026, 10, 29), D("50"))]
    assert rate_split.changes(steps, date(2026, 10, 1), date(2026, 10, 31)) == []


def test_krok_z_ta_sama_stawka_to_nie_zmiana():
    steps = [(date(2025, 8, 18), D("125")), (date(2026, 8, 29), D("125"))]
    assert rate_split.changes(steps, date(2026, 8, 1), date(2026, 8, 31)) == []


def test_ten_sam_dzien_wygrywa_pozniejszy_wpis():
    steps = [
        (date(2026, 3, 17), D("120")),
        (date(2026, 9, 17), D("125")),
        (date(2026, 9, 17), D("126")),
    ]
    assert rate_split.changes(steps, SEPT_FIRST, SEPT_LAST)[0].new == D("126")


# ── podział MD według godzin z RCP ───────────────────────────────────────────


def test_podzial_wedlug_dni_z_rcp():
    parts = rate_split.parts(
        _segments((1, "960"), (17, "1008")),
        HOURS,
        last=SEPT_LAST,
        md=D("21"),
        per_md=D("8"),
    )
    assert parts == [
        CostPart(date(2026, 9, 1), date(2026, 9, 16), D("12.000"), D("960")),
        CostPart(date(2026, 9, 17), date(2026, 9, 30), D("9.000"), D("1008")),
    ]
    assert sum(p.net for p in parts) == D("20592.00")


def test_zmiana_ostatniego_dnia_z_praca_tego_dnia():
    parts = rate_split.parts(
        _segments((1, "960"), (30, "1008")),
        HOURS,
        last=SEPT_LAST,
        md=D("21"),
        per_md=D("8"),
    )
    assert [(p.md, p.rate) for p in parts] == [
        (D("20.000"), D("960")),
        (D("1.000"), D("1008")),
    ]


def test_zmiana_ostatniego_dnia_bez_pracy_to_jedna_stawka():
    hours = tuple(h if day != 30 else D("0") for day, h in enumerate(HOURS, start=1))
    parts = rate_split.parts(
        _segments((1, "960"), (30, "1008")),
        hours,
        last=SEPT_LAST,
        md=D("20"),
        per_md=D("8"),
    )
    assert [(p.md, p.rate) for p in parts] == [(D("20.000"), D("960"))]


def test_dzien_spoza_miesiaca_w_rcp_nie_liczy_sie():
    hours = HOURS[:30] + (D("8"),)
    parts = rate_split.parts(
        _segments((1, "960"), (17, "1008")),
        hours,
        last=SEPT_LAST,
        md=D("21"),
        per_md=D("8"),
    )
    assert isinstance(parts, list) and sum(p.md for p in parts) == D("21")


def test_bez_godzin_dzien_po_dniu_uwaga_zostaje():
    reason = rate_split.parts(
        _segments((1, "960"), (17, "1008")),
        (),
        last=SEPT_LAST,
        md=D("21"),
        per_md=D("8"),
    )
    assert isinstance(reason, str) and "dzień po dniu" in reason


def test_godziny_inne_niz_md_rozliczenia_uwaga_zostaje():
    reason = rate_split.parts(
        _segments((1, "960"), (17, "1008")),
        HOURS,
        last=SEPT_LAST,
        md=D("22"),
        per_md=D("8"),
    )
    assert isinstance(reason, str) and "168 h" in reason


def test_ulamkowe_md_reszta_idzie_na_ostatnia_czesc():
    hours = tuple(D("7") if day in WORKDAYS else D("0") for day in range(1, 32))
    parts = rate_split.parts(
        _segments((1, "960"), (17, "1008")),
        hours,
        last=SEPT_LAST,
        md=D("18.375"),
        per_md=D("8"),
    )
    assert [p.md for p in parts] == [D("10.500"), D("7.875")]


# ── silnik ───────────────────────────────────────────────────────────────────

RULES = {
    "extra.multiplier": {"level": "off", "params": {}},
    "order.onboarding_md": {"level": "off", "params": {}},
    "order.no_md_holds_invoice": {"level": "warn", "params": {}},
    "cl.protocol_amount": {"level": "off", "params": {}},
}
PARTS = (
    CostPart(date(2026, 9, 1), date(2026, 9, 16), D("12"), D("960")),
    CostPart(date(2026, 9, 17), date(2026, 9, 30), D("9"), D("1008")),
)


def _order(available: str | None = "100") -> OrderState:
    return OrderState(
        order_id=1,
        number="ZAM-1",
        md_total=D("100"),
        md_available=None if available is None else D(available),
        rate_cost=D("960"),
        rate_revenue=D("1500"),
    )


def test_silnik_liczy_koszt_z_czesci_a_przychod_jak_dotad():
    result = compute(
        Inputs(
            md_regular=D("21"),
            md_extra=None,
            rules=RULES,
            order=_order(),
            has_report=True,
            cost_parts=PARTS,
        )
    )
    assert result.amount_cost == D("20592.00")
    assert result.amount_revenue == D("31500.00")
    assert [(line["label"], line["net"]) for line in result.lines] == [
        ("Dni zwykłe 01.09–16.09", "11520.00"),
        ("Dni zwykłe 17.09–30.09", "9072.00"),
    ]


def test_silnik_bez_czesci_liczy_jedna_stawka():
    result = compute(
        Inputs(
            md_regular=D("21"),
            md_extra=None,
            rules=RULES,
            order=_order(),
            has_report=True,
        )
    )
    assert result.amount_cost == D("20160.00")
    assert [line["label"] for line in result.lines] == ["Dni zwykłe"]


def test_md_ponad_pule_ida_stawka_ostatniej_czesci():
    result = compute(
        Inputs(
            md_regular=D("21"),
            md_extra=None,
            rules=RULES,
            order=_order(available="20"),
            has_report=True,
            cost_parts=PARTS,
        )
    )
    assert result.md_over == D("1.000")
    assert result.amount_cost == D("19584.00")  # 20 592 − 1 MD × 1008
    assert result.lines[-1]["rate"] == "1008.00"
