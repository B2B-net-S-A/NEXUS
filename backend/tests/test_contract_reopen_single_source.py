"""Powrót `ended`/`ending` → `active` ma JEDNO źródło i zostawia audyt.

Regresja jest tu maksymalnie cicha: kontrakt ląduje we właściwym stanie, więc
UI wygląda poprawnie, a znika wyłącznie wiersz `Activity` `contract_reopened`.
Zauważa to dopiero ktoś, kto po miesiącach odtwarza ze śladu audytowego,
dlaczego kontrakt był w danym miesiącu aktywny — i znajduje aktywację oraz
terminację, ale nie powrót. To przejście jest najściślej powiązane z
przychodem (zakończony konsultant wraca do pracy, bo współpracę przedłużono).

Dlatego test pilnuje dwóch rzeczy: zachowania samej funkcji cyklu życia ORAZ
tego, że obie ścieżki przedłużania w routerze faktycznie przez nią przechodzą,
zamiast trzymać własną kopię reguły (`contracts.py` miał takie dwie).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.contract import ContractStatus
from app.services import contract_lifecycle as lifecycle

BACKEND = Path(__file__).resolve().parents[1]
CONTRACTS_API = BACKEND / "app/api/contracts.py"


class _CollectingDB:
    """Sesja-atrapa: interesuje nas wyłącznie, co trafia do `db.add`."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


def _contract(status: ContractStatus) -> SimpleNamespace:
    return SimpleNamespace(id=7, status=status)


@pytest.mark.asyncio
@pytest.mark.parametrize("start", [ContractStatus.ended, ContractStatus.ending])
async def test_reopen_flips_to_active_and_writes_audit(start: ContractStatus):
    db = _CollectingDB()
    contract = _contract(start)

    changed = await lifecycle.reopen_contract(db, contract, actor_id=42)

    assert changed is True
    assert contract.status == ContractStatus.active
    assert len(db.added) == 1, "brak wiersza audytu contract_reopened"
    activity = db.added[0]
    assert activity.action == "contract_reopened"
    assert activity.details["from_status"] == start.value
    assert activity.details["to_status"] == ContractStatus.active.value


@pytest.mark.asyncio
async def test_reopen_is_a_noop_for_an_already_active_contract():
    """Przedłużenie żywego kontraktu nie może produkować szumu w feedzie."""
    db = _CollectingDB()
    contract = _contract(ContractStatus.active)

    changed = await lifecycle.reopen_contract(db, contract, actor_id=42)

    assert changed is False
    assert contract.status == ContractStatus.active
    assert db.added == []


@pytest.mark.asyncio
async def test_reopen_leaves_a_voided_contract_alone():
    """`void` jest terminalny — przedłużenie nie może go wskrzesić po cichu.

    Reguła leczy WYŁĄCZNIE `ended`/`ending`; wszystko inne jest brakiem zmiany,
    a nie błędem — tak samo zachowywały się usunięte kopie inline.
    """
    db = _CollectingDB()
    contract = _contract(ContractStatus.void)

    changed = await lifecycle.reopen_contract(db, contract, actor_id=42)

    assert changed is False
    assert contract.status == ContractStatus.void
    assert db.added == []


def test_extension_paths_call_the_lifecycle_helper():
    source = CONTRACTS_API.read_text(encoding="utf-8")
    tree = ast.parse(source)

    handlers = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name in {"bulk_extend_contracts", "create_contract_amendment"}
    }
    assert set(handlers) == {"bulk_extend_contracts", "create_contract_amendment"}, (
        "Ścieżka przedłużania zmieniła nazwę — zaktualizuj ten test razem z nią, "
        "inaczej przestaje czegokolwiek pilnować."
    )

    for name, fn in handlers.items():
        called = {
            node.value.func.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Await)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        }
        assert "reopen_contract" in called, (
            f"{name}() nie woła reopen_contract() — powrót na `active` znowu "
            "omija `assert_transition` i nie zapisuje audytu."
        )


def test_no_handwritten_copy_of_the_reopen_rule_came_back():
    """Trzecia kopia reguły wróciłaby jako przypisanie `status = active`
    pod warunkiem na `ending`/`ended` — dokładnie w tym kształcie żyły obie
    usunięte."""
    source = CONTRACTS_API.read_text(encoding="utf-8")
    pattern = re.compile(
        r"if\s+\w+\.status\s+in\s+\(\s*ContractStatus\.ending,\s*"
        r"ContractStatus\.ended,?\s*\)\s*:\s*\n\s*\w+\.status\s*=\s*"
        r"ContractStatus\.active"
    )
    assert not pattern.search(source), (
        "W contracts.py wróciła ręczna kopia reguły reopen — użyj "
        "contract_lifecycle.reopen_contract()."
    )
