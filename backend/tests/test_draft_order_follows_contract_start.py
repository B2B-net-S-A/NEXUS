"""Szkic zamówienia idzie za startem umowy, dopóki nikt go nie ustawił sam.

Zgłoszenie 19.11.2026 (Finanse → Zmiany w zamówieniach → Wejścia): hook
„Zatrudniony” założył umowę i szkic zamówienia ze startem „dziś” (04.11),
dwa dni później start umowy zmieniono na 01.02.2027, a szkic został przy
04.11 — i osoba z wejściem w lutym stała w Wejściach za listopad.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.contracts import _move_order_drafts_with_contract_start
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract

OLD = date(2026, 11, 4)
NEW = date(2027, 2, 1)


def _draft(order_id: int, start: date | None, end: date | None = None) -> ClientOrder:
    return ClientOrder(
        id=order_id,
        client_id=7,
        contract_id=31,
        title=f"PO-{order_id}",
        status=ClientOrderStatus.draft,
        start_date=start,
        end_date=end,
    )


def _db(drafts: list[ClientOrder]) -> SimpleNamespace:
    return SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: drafts))
    )


@pytest.mark.asyncio
async def test_draft_with_the_old_contract_start_follows_the_new_one() -> None:
    contract = Contract(id=31, start_date=NEW)
    draft = _draft(904, OLD)

    moved = await _move_order_drafts_with_contract_start(
        _db([draft]), contract, previous_start=OLD
    )

    assert moved == 1
    assert draft.start_date == NEW


@pytest.mark.asyncio
async def test_draft_without_start_takes_the_contract_start() -> None:
    contract = Contract(id=31, start_date=NEW)
    draft = _draft(905, None)

    assert (
        await _move_order_drafts_with_contract_start(
            _db([draft]), contract, previous_start=OLD
        )
        == 1
    )
    assert draft.start_date == NEW


@pytest.mark.asyncio
async def test_draft_dated_by_hand_or_with_an_end_stays_put() -> None:
    contract = Contract(id=31, start_date=NEW)
    by_hand = _draft(906, date(2026, 12, 1))
    with_end = _draft(907, OLD, end=date(2026, 12, 31))

    moved = await _move_order_drafts_with_contract_start(
        _db([by_hand, with_end]), contract, previous_start=OLD
    )

    assert moved == 0
    assert by_hand.start_date == date(2026, 12, 1)
    assert with_end.start_date == OLD


@pytest.mark.asyncio
async def test_unchanged_or_cleared_contract_start_touches_nothing() -> None:
    db = _db([_draft(908, OLD)])

    assert (
        await _move_order_drafts_with_contract_start(
            db, Contract(id=31, start_date=OLD), previous_start=OLD
        )
        == 0
    )
    assert (
        await _move_order_drafts_with_contract_start(
            db, Contract(id=31, start_date=None), previous_start=OLD
        )
        == 0
    )
    db.scalars.assert_not_awaited()
