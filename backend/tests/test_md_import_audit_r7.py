"""Runda 7 audytu (26.09.2026) — import zużycia MD.

* R7-N4-2: „Importy MD" na profilu klienta pokazywały wiersz niezaksięgowany
  innego klienta, gdy dowolna liczba z „Uwag" równała się cyfrom numeru
  zamówienia klienta („delegacja 445" przy „CP 445").
* R7-V4-5: klient kosztowy osoby z numerami z samych cyfr (Polkomtel)
  włączał regułę „≥ 7 cyfr wiąże" dla wiersza MD u BNP — NIP w „Uwagach"
  blokował dopasowanie po nazwisku.
* R7-N2-1: replay Polkomtela nadpisywał zużycie linii sumą samych wierszy
  z numerem i gubił MD wierszy tej paczki zaksięgowanych po nazwisku.

Testy bez bazy: logika jest w czystych funkcjach.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.client_md_imports import _ClientScope
from app.api.md_consumption import (
    _REPROCESS_MD_LINE,
    _ReasonContext,
    _build_polkomtel_reprocess_plan,
    _match_per_consultant_md_row,
    _unmatched_reason,
)
from app.models.client_order import ClientOrderStatus
from app.models.contract import ContractStatus
from app.models.md_consumption import (
    IMPORT_ROW_APPLIED,
    IMPORT_ROW_UNMATCHED,
    MdConsumptionImportRow,
)
from app.services import finance_order_matching
from app.services.client_order_lines import LineMatch, name_tokens

POLKOMTEL = 15
CP = 38339
BNP = 12


@pytest.fixture(autouse=True)
def _polkomtel_is_client_15(monkeypatch):
    """conftest odpina bramkę Polkomtela (id −3) — te testy pytają wprost o nią."""
    monkeypatch.setattr(finance_order_matching, "POLKOMTEL_CLIENT_ID", POLKOMTEL)


# ── R7-N4-2 ────────────────────────────────────────────────────────────────


def _unmatched(name: str, hint: str) -> MdConsumptionImportRow:
    return MdConsumptionImportRow(
        import_id=1,
        row_number=2,
        consultant_name=name,
        md_reported=Decimal("5"),
        status=IMPORT_ROW_UNMATCHED,
        order_number_hint=hint,
    )


def _scope(client_id: int, numbers: dict[int, str], people: list[str]):
    return _ClientScope(
        {},
        numbers,
        client_id=client_id,
        people=frozenset(name_tokens(p) for p in people),
    )


def test_a_stray_number_in_notes_does_not_show_another_clients_row():
    scope = _scope(CP, {77: "CP 445"}, ["Anna Nasza"])

    assert not scope.touches(_unmatched("Jan Obcy", "445"))


def test_a_person_without_a_line_at_the_client_is_not_its_row():
    scope = _scope(BNP + 1, {77: "4500012345"}, ["Anna Nasza"])

    assert not scope.touches(_unmatched("Jan Obcy", "4500012345"))


def test_a_number_that_does_not_bind_is_not_this_clients_order():
    # „445" nie jest numerem zamówienia „CP 445" według reguły importu.
    scope = _scope(CP, {77: "CP 445"}, ["Anna Nasza"])

    assert not scope.touches(_unmatched("Anna Nasza", "445"))


def test_binding_number_and_person_on_the_order_show_the_row():
    scope = _scope(BNP + 1, {77: "4500012345"}, ["Anna Nasza"])

    assert scope.touches(_unmatched("Nasza Anna", "4500012345"))


# ── R7-V4-5 ────────────────────────────────────────────────────────────────


def _line(order_id: int, client_id: int, number: str, name: str) -> LineMatch:
    return LineMatch(
        order=SimpleNamespace(id=order_id, status=ClientOrderStatus.active),
        group=SimpleNamespace(
            id=order_id * 10, client_id=client_id, order_number=number
        ),
        consultant_name=name,
    )


def _index():
    return finance_order_matching.build_order_number_index(
        [(BNP, "87_2026"), (POLKOMTEL, "SAP 4500012345")]
    )


def test_cost_client_does_not_make_a_nip_bind_a_bnp_md_row():
    bnp = _line(1, BNP, "87_2026", "Ewa Dwojga")

    picked = _match_per_consultant_md_row(
        parsed_row=SimpleNamespace(
            consultant_name="Ewa Dwojga", notes_raw="NIP 5261040828"
        ),
        candidates=[bnp],
        order_numbers=_index(),
        other_client_ids={POLKOMTEL},
    )

    assert picked == [bnp]


def test_known_number_of_the_cost_order_still_binds():
    bnp = _line(1, BNP, "87_2026", "Ewa Dwojga")

    picked = _match_per_consultant_md_row(
        parsed_row=SimpleNamespace(
            consultant_name="Ewa Dwojga", notes_raw="faktura SAP 4500012345"
        ),
        candidates=[bnp],
        order_numbers=_index(),
        other_client_ids={POLKOMTEL},
    )

    assert picked == []


def test_reason_mirror_does_not_widen_to_the_cost_client():
    def order(oid: int, client_id: int, group_id: int):
        return SimpleNamespace(
            id=oid,
            client_id=client_id,
            order_group_id=group_id,
            status=ClientOrderStatus.active,
            contract=SimpleNamespace(status=ContractStatus.active),
            start_date=None,
            end_date=None,
        )

    groups = {
        10: SimpleNamespace(
            id=10, client_id=BNP, order_number="87_2026", is_cost_based=False
        ),
        20: SimpleNamespace(
            id=20,
            client_id=POLKOMTEL,
            order_number="SAP 4500012345",
            is_cost_based=True,
        ),
    }
    context = _ReasonContext(
        index=_index(),
        groups=groups,
        lines_by_person={
            name_tokens("Ewa Dwojga"): [order(1, BNP, 10), order(2, POLKOMTEL, 20)]
        },
    )
    row = SimpleNamespace(
        status=IMPORT_ROW_UNMATCHED,
        cost_status=None,
        consultant_name="Ewa Dwojga",
        notes_raw="NIP 5261040828",
    )

    assert _unmatched_reason(row, "2026-08", context) is None


# ── R7-N2-1 ────────────────────────────────────────────────────────────────


def _import_row(row_id: int, **fields):
    base = dict(
        id=row_id,
        consultant_name="Piotr Replay",
        notes_raw=None,
        status=IMPORT_ROW_UNMATCHED,
        matched_order_id=None,
        matched_group_id=None,
        md_reported=Decimal("0"),
        invoice_amount=None,
        cost_status=None,
    )
    base.update(fields)
    return SimpleNamespace(**base)


def test_polkomtel_replay_keeps_rows_booked_by_name_in_the_same_batch():
    line = _line(5, POLKOMTEL, "SAP 87020188", "Piotr Replay")
    numbered = _import_row(101, notes_raw="87020188", md_reported=Decimal("4"))
    by_name = _import_row(
        102,
        status=IMPORT_ROW_APPLIED,
        matched_order_id=5,
        md_reported=Decimal("6"),
    )

    plans, conflicts = _build_polkomtel_reprocess_plan(
        [numbered, by_name],
        md_candidates=[line],
        shared_md_candidates=[],
        cost_candidates=[],
    )

    assert conflicts == []
    assert len(plans) == 1
    plan = plans[0]
    assert plan.kind == _REPROCESS_MD_LINE
    assert plan.expected_value == Decimal("10")
    assert [row.id for row in plan.rows_to_update] == [101]


def test_polkomtel_replay_ignores_rows_booked_on_another_line():
    line = _line(5, POLKOMTEL, "SAP 87020188", "Piotr Replay")
    numbered = _import_row(101, notes_raw="87020188", md_reported=Decimal("4"))
    elsewhere = _import_row(
        103,
        status=IMPORT_ROW_APPLIED,
        matched_order_id=9,
        md_reported=Decimal("7"),
    )

    plans, _ = _build_polkomtel_reprocess_plan(
        [numbered, elsewhere],
        md_candidates=[line],
        shared_md_candidates=[],
        cost_candidates=[],
    )

    assert plans[0].expected_value == Decimal("4")
