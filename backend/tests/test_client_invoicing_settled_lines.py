"""„Do faktury” zamówienia okresowego z przyjętego rozliczenia (27.11.2026), bez bazy.

Przed zmianą linia okresowa liczyła stawkę × 168 h z zamówienia także wtedy,
gdy rozliczenie osoby było przyjęte z innymi dniami — w październiku (22 dni
robocze) „Wystaw za miesiąc” rozjeżdżało się z fakturą Finansów o 1 MD.
Osoby i kwoty zmyślone.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.client_invoicing import billing, issue, settled_lines

D = Decimal


def _order_line(**patch) -> billing.BillingLine:
    base = {
        "order_id": 7,
        "consultant": "Jan Przykładowy",
        "basis": "days",
        "quantity": D("21.00"),
        "unit_price": D("1000"),
        "net": D("21000.00"),
        "currency": "PLN",
        "note": "21 dni w miesiącu wg zamówienia",
    }
    base.update(patch)
    return billing.BillingLine(**base)


def _row(state: str, positions: list[dict], contract_id: int = 3, order_id=7) -> dict:
    return {
        "contract_id": contract_id,
        "order_id": order_id,
        "state": state,
        "positions": positions,
    }


BASE = {
    "name": "Usługi IT; Jan Przykładowy",
    "unit": "MD",
    "quantity": "22",
    "unit_price": "1000.00",
    "net": "22000.00",
    "kind": "base",
    "currency": "PLN",
}
OVERTIME = {
    **BASE,
    "name": "Usługi IT; Jan Przykładowy_nadgodziny",
    "quantity": "1.5",
    "unit_price": "1500.00",
    "net": "2250.00",
    "kind": "overtime",
}


def test_accepted_settlement_replaces_the_order_estimate():
    settled = settled_lines.settled_from_rows([_row("ready", [BASE])])
    lines = billing.with_settlement(_order_line(), settled_lines.find(settled, 3, 7))
    assert len(lines) == 1
    line = lines[0]
    assert (line.basis, line.quantity, line.net) == ("md", D("22"), D("22000.00"))
    assert line.source == "settlement" and line.awaiting is None


def test_overtime_becomes_a_second_line_with_a_suffix():
    settled = settled_lines.settled_from_rows([_row("ready", [BASE, OVERTIME])])
    lines = billing.with_settlement(_order_line(), settled_lines.find(settled, 3, 7))
    assert [ln.suffix for ln in lines] == [None, "nadgodziny"]
    assert sum(ln.net for ln in lines) == D("24250.00")


def test_person_without_accepted_report_waits_and_blocks_the_draft():
    settled = settled_lines.settled_from_rows([_row("waiting", [])])
    lines = billing.with_settlement(_order_line(), settled_lines.find(settled, 3, 7))
    assert lines[0].net == D("21000.00")  # podgląd z zamówienia zostaje
    assert lines[0].awaiting == "czeka na przyjęte rozliczenie (RCP)"
    row = billing.BillingRow(
        client_id=1,
        kind="periodic",
        group_id=None,
        order_id=7,
        order_number="Z/1",
        currency="PLN",
        lines=lines,
    )
    assert "Jan Przykładowy" in issue._row_block(row)


def test_hours_not_approved_in_t4t_wait_too():
    settled = settled_lines.settled_from_rows([_row("awaiting_t4t", [BASE])])
    lines = billing.with_settlement(_order_line(), settled_lines.find(settled, 3, 7))
    assert lines[0].awaiting == "czeka na godziny zatwierdzone w T4T"


def test_contract_outside_settlements_keeps_the_order_line():
    settled = settled_lines.settled_from_rows([_row("ready", [BASE], contract_id=99)])
    line = _order_line()
    assert billing.with_settlement(line, settled_lines.find(settled, 3, 7)) == (line,)


def test_row_without_order_line_is_used_only_when_it_is_the_only_one():
    one = settled_lines.settled_from_rows([_row("ready", [BASE], order_id=None)])
    assert settled_lines.find(one, 3, 7) is not None
    two = settled_lines.settled_from_rows(
        [
            _row("ready", [BASE], order_id=None),
            {**_row("ready", [BASE], order_id=None), "contract_id": 3},
        ]
    )
    # Ten sam klucz nadpisuje — jeden wiersz kontraktu bez linii.
    assert settled_lines.find(two, 3, 7) is not None


def test_hours_unit_from_t4t_maps_to_hours():
    pos = settled_lines.position_from({**BASE, "unit": "godz.", "quantity": "168"})
    assert pos is not None and pos.basis == "hours"
