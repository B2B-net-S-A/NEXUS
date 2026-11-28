"""„Rozstrzygnij w oknie zamówienia": typ i kontrakt bierze się z planu dokumentu.

Zgłoszenie 28.11.2026: dokument z maila z powrotem po przerwie na zamówieniu
okresowym (plan ``reactivate``, ``order_type = periodic``, istniejący kontrakt)
otwierał okno jako zamówienie MD, bo ``order-target`` znał tylko MD i kosztowe,
a brak takiego wiersza zamieniał na „md". Po przełączeniu na „Okresowe" okno
proponowało założenie NOWEJ umowy obok istniejącej.

Czyste funkcje na planie — bez bazy. Nazwiska i numery zmyślone.
"""

from types import SimpleNamespace

import pytest

from app.api.order_mail_queue import _existing_contract_of, _order_type_of


def _doc(*rows: dict) -> SimpleNamespace:
    return SimpleNamespace(proposal={"rows": list(rows)})


def _row(action: str, order_type: str = "periodic", contract_id=None) -> dict:
    return {
        "row_index": 0,
        "row_name": "Jan Testowy",
        "action": action,
        "order_type": order_type,
        "contract_id": contract_id,
    }


def test_periodic_return_after_break_stays_periodic():
    doc = _doc(_row("reactivate", "periodic", contract_id=501))
    assert _order_type_of(doc) == "periodic"


@pytest.mark.parametrize("order_type", ["md", "cost"])
def test_md_and_cost_plans_keep_their_type(order_type):
    assert _order_type_of(_doc(_row("decide_person", order_type))) == order_type


def test_plan_without_rows_has_no_type_of_its_own():
    # Typ podaje wtedy historia klienta (``most_common_order_type``), nie „md".
    assert _order_type_of(_doc()) is None
    assert _order_type_of(SimpleNamespace(proposal=None)) is None


@pytest.mark.parametrize(
    "action", ["reactivate", "revision", "group", "overlap", "unchanged", "future"]
)
def test_plan_on_an_existing_contract_points_to_it(action):
    assert _existing_contract_of(_doc(_row(action, contract_id=501))) == 501


@pytest.mark.parametrize("action", ["decide_person", "new_draft", "skip"])
def test_person_to_decide_or_new_has_no_contract_to_continue(action):
    assert _existing_contract_of(_doc(_row(action, contract_id=501))) is None


def test_several_people_do_not_point_to_one_contract():
    doc = _doc(
        _row("reactivate", contract_id=501),
        {**_row("revision", contract_id=502), "row_index": 1},
    )
    assert _existing_contract_of(doc) is None


def test_same_contract_on_two_rows_is_still_that_contract():
    doc = _doc(
        _row("reactivate", contract_id=501),
        {**_row("skip", contract_id=None), "row_index": 1},
        {**_row("revision", contract_id=501), "row_index": 2},
    )
    assert _existing_contract_of(doc) == 501
