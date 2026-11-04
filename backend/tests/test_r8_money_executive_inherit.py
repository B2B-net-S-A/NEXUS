"""Runda 8 (R8-N6-5): powrót po przerwie dziedziczy tylko TRWAJĄCĄ umowę wykonawczą.

Powrót po przerwie (przycisk „Powrót po przerwie” i mail z nowym okresem
po zakończonym zamówieniu) kopiował `executive_contract_id` poprzedniego
zamówienia bez sprawdzenia statusu umowy. Umowa zakończona po zamknięciu
poprzedniego zamówienia trafiała na nowe, żywe zamówienie — czego każda inna
ścieżka (`resolve_ezdrowie_assignment`) odmawia 422.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.models.client_executive_contract import (
    EXECUTIVE_CONTRACT_STATUS_ACTIVE,
    EXECUTIVE_CONTRACT_STATUS_ENDED,
)
from app.services.executive_contracts import inheritable_executive_contract_id

APP = Path(__file__).resolve().parents[1] / "app"


class _Db:
    def __init__(self, status):
        self.status = status
        self.calls = 0

    async def scalar(self, _stmt):
        self.calls += 1
        return self.status


@pytest.mark.asyncio
async def test_active_executive_contract_is_inherited():
    db = _Db(EXECUTIVE_CONTRACT_STATUS_ACTIVE)
    assert await inheritable_executive_contract_id(db, 7) == 7


@pytest.mark.asyncio
async def test_ended_or_missing_executive_contract_is_dropped():
    assert (
        await inheritable_executive_contract_id(_Db(EXECUTIVE_CONTRACT_STATUS_ENDED), 7)
        is None
    )
    assert await inheritable_executive_contract_id(_Db(None), 7) is None


@pytest.mark.asyncio
async def test_no_executive_contract_needs_no_query():
    db = _Db(EXECUTIVE_CONTRACT_STATUS_ACTIVE)
    assert await inheritable_executive_contract_id(db, None) is None
    assert db.calls == 0


@pytest.mark.parametrize(
    "relative",
    ["services/contract_return_after_break.py", "services/order_mail_apply.py"],
)
def test_return_paths_do_not_copy_the_executive_contract_raw(relative):
    """Obie ścieżki powrotu przechodzą przez `inheritable_executive_contract_id`
    — surowe `<poprzednie>.executive_contract_id` przepisane do nowego
    zamówienia okresowego to dokładnie ten błąd."""
    source = (APP / relative).read_text(encoding="utf-8")
    assert "inheritable_executive_contract_id" in source
    tree = ast.parse(source)
    raw = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.keyword, ast.Dict))
        for value in ([node.value] if isinstance(node, ast.keyword) else node.values)
        if isinstance(value, ast.Attribute)
        and value.attr == "executive_contract_id"
        and isinstance(value.value, ast.Name)
        and value.value.id in {"old", "previous"}
    ]
    assert raw == []
