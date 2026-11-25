"""Koszt linii zamówienia zbiorczego z harmonogramu kontraktu (próba IX–X 2026). Bez bazy.

Stawkę linii zbiorczej prowadzi Delivery Lead, a synchronizacja z kontraktem jej
nie zmienia. Po aneksie od połowy poprzedniego miesiąca linia została przy starej
stawce i rozliczenie całego kolejnego miesiąca miało za niski koszt ze stanem „ok”.
Kontraktor fakturuje według kontraktu, więc gdy przez cały miesiąc obowiązuje jedna
stawka harmonogramu w zł, koszt idzie z niej (decyzja Artura z 25.11.2026).
Stawki i MD fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from app.models.contract import Contract, RateUnit
from app.services.client_settlements import rules_catalog, service
from app.services.client_settlements.engine import Inputs, OrderState, compute

OCT = "2026-10"
#: Kontrakt od 17.03 po 100 zł/h, aneks od 17.09 na 105 zł/h.
STEPS = [(date(2026, 3, 17), D("100")), (date(2026, 9, 17), D("105"))]
GROUP_LINE = SimpleNamespace(order_group_id=7)


def _contract(
    unit: RateUnit = RateUnit.hourly, currency: str = "PLN", legacy: str = "105"
) -> Contract:
    return Contract(
        rate_unit=unit,
        rate_candidate=D(legacy),
        rate_candidate_currency=currency,
        currency=currency,
    )


def _state(rate_cost: str | None = "800") -> OrderState:
    return OrderState(
        order_id=1,
        number="ZAM-1",
        md_total=None,
        md_available=None,
        rate_cost=None if rate_cost is None else D(rate_cost),
        rate_revenue=D("1200"),
    )


def _cost(contract=None, order=GROUP_LINE, state=None, steps=STEPS, month=OCT):
    return service._contract_cost(
        _contract() if contract is None else contract,
        order,
        _state() if state is None else state,
        steps,
        month,
    )


def test_linia_zbiorcza_po_aneksie_liczy_koszt_z_kontraktu():
    state, note = _cost()
    assert state.rate_cost == D("840.00")
    assert state.rate_revenue == D("1200")
    assert note["title"] == "Stawka kontraktora"
    [check] = note["checks"]
    assert check["state"] == "ok"
    assert check["title"] == "Koszt ze stawki kontraktu: 840 zł/MD"
    assert "ZAM-1: 800 zł/MD" in check["detail"]
    assert "840 zł/MD (105 zł/h)" in check["detail"]


def test_koszt_i_status_w_silniku():
    """22 MD × 840 zł = 18 480 zł, a nie 22 × 800; stan bez zmian."""

    state, _note = _cost()
    rules = rules_catalog.effective({})
    before = compute(
        Inputs(
            md_regular=D("22"),
            md_extra=None,
            rules=rules,
            order=_state(),
            has_report=True,
        )
    )
    after = compute(
        Inputs(
            md_regular=D("22"), md_extra=None, rules=rules, order=state, has_report=True
        )
    )
    assert before.amount_cost == D("17600.00")
    assert after.amount_cost == D("18480.00")
    assert after.amount_revenue == before.amount_revenue
    assert after.status == before.status


def test_praca_dodatkowa_tez_ze_stawki_kontraktu():
    state, _note = _cost()
    rules = rules_catalog.effective(
        {"extra.multiplier": {"level": "warn", "params": {"pct": "150"}}}
    )
    result = compute(
        Inputs(
            md_regular=D("20"),
            md_extra=D("2"),
            rules=rules,
            order=state,
            has_report=True,
        )
    )
    assert {line["label"]: line["rate"] for line in result.lines} == {
        "Dni zwykłe": "840.00",
        "Praca dodatkowa": "840.00",
    }
    assert result.amount_cost == D("19320.00")


def test_zmiana_od_pierwszego_dnia_to_stawka_calego_miesiaca():
    steps = [(date(2026, 3, 17), D("100")), (date(2026, 10, 1), D("105"))]
    state, note = _cost(steps=steps)
    assert state.rate_cost == D("840.00")
    assert note is not None


def test_zmiana_od_pierwszego_dnia_z_linia_juz_po_nowej_stawce():
    steps = [(date(2026, 3, 17), D("100")), (date(2026, 10, 1), D("105"))]
    line = _state("840")
    state, note = _cost(state=line, steps=steps)
    assert state is line
    assert note is None


def test_linia_ustawiona_na_stawke_z_przyszlego_aneksu():
    """Linia dostała stawkę aneksu od 01.11, a w X kontrakt płaci jeszcze starą."""

    steps = [(date(2026, 4, 27), D("120")), (date(2026, 11, 1), D("125"))]
    state, _note = _cost(state=_state("1000"), steps=steps)
    assert state.rate_cost == D("960.00")


def test_linia_zgodna_z_kontraktem_bez_zmian():
    line = _state("840")
    state, note = _cost(state=line)
    assert state is line
    assert note is None


def test_grosz_roznicy_to_ta_sama_stawka():
    line = _state("840.004")
    state, note = _cost(state=line)
    assert state is line
    assert note is None


def test_waluta_obca_bez_zmian():
    """Linia trzyma koszt w zł po kursie, a kontrakt w EUR: bez kursu nie porównamy."""

    line = _state("747.33")
    state, note = _cost(
        contract=_contract(currency="EUR", legacy="22"),
        state=line,
        steps=[(date(2026, 1, 15), D("22"))],
    )
    assert state is line
    assert note is None


def test_zmiana_w_trakcie_miesiaca_zostaje_dla_podzialu_kosztu():
    """Wrzesień z aneksem od 17.09 dzieli ``_rate_change_checks`` (godziny z RCP)."""

    line = _state()
    state, note = _cost(state=line, month="2026-09")
    assert state is line
    assert note is None


def test_linia_bez_zamowienia_zbiorczego_bez_zmian():
    """Zwykłe zamówienie ma części kosztu z harmonogramu (``order_cost_steps``)."""

    line = _state()
    state, note = _cost(order=SimpleNamespace(order_group_id=None), state=line)
    assert state is line
    assert note is None


def test_kontrakt_miesieczny_bez_zmian():
    line = _state()
    state, note = _cost(
        contract=_contract(unit=RateUnit.monthly, legacy="17000"),
        state=line,
        steps=[(date(2026, 1, 1), D("17000"))],
    )
    assert state is line
    assert note is None


def test_linia_bez_stawki_kosztu_bez_zmian():
    line = _state(None)
    state, note = _cost(state=line)
    assert state is line
    assert note is None


def test_kontrakt_bez_harmonogramu_bierze_stawke_z_kontraktu():
    """Jak ``Contract.effective_candidate_rate``: bez kroków stawka z kolumny."""

    state, _note = _cost(
        contract=_contract(legacy="120"), state=_state("1000"), steps=[]
    )
    assert state.rate_cost == D("960.00")


def test_kontrakt_dzienny():
    state, note = _cost(
        contract=_contract(unit=RateUnit.daily, legacy="900"),
        steps=[(date(2026, 1, 1), D("900"))],
    )
    assert state.rate_cost == D("900.00")
    assert "zł/h" not in note["checks"][0]["detail"]
