"""Zakładka „Konsultanci” w profilu klienta (18.11.2026): bieżące zamówienie
i znaczniki „Wymaga uwagi” liczone istniejącymi regułami — bez bazy.

`no_current_order` = reguła flagi „bez projektu” dla COMPASS (przeniesiona do
`services/consultant_order_state.py`), `order_ending` = reguła pigułki
„Bez kontynuacji 30 dni” w Zamówieniach (`ending_without_successor`).
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from app.models.client_order import ClientOrderStatus
from app.models.contract import ContractStatus
from app.services.consultant_order_state import (
    ATTENTION_NO_CURRENT_ORDER,
    ATTENTION_NOTICE,
    ATTENTION_ORDER_ENDING,
    consultant_order_state,
    lacks_current_order,
)

TODAY = date(2026, 11, 18)


def _order(
    order_id: int,
    *,
    start: date | None,
    end: date | None,
    status: ClientOrderStatus = ClientOrderStatus.active,
    group: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        status=status,
        start_date=start,
        end_date=end,
        order_group_id=group.id if group is not None else None,
        order_group=group,
        md_total=None,
        md_remaining=None,
        rate_client=100,
        md_rate_revenue=None,
    )


def _contract(
    *orders: SimpleNamespace, status: ContractStatus = ContractStatus.active
) -> SimpleNamespace:
    return SimpleNamespace(status=status, client_orders=list(orders))


def test_live_contract_without_any_order_needs_attention():
    state = consultant_order_state(_contract(), TODAY, is_current=True)
    assert state.attention == (ATTENTION_NO_CURRENT_ORDER,)
    assert state.order_start_date is None and state.order_end_date is None


def test_lapsed_order_stays_in_the_column_and_flags_the_gap():
    ended = _order(
        1,
        start=date(2026, 1, 1),
        end=date(2026, 10, 31),
        status=ClientOrderStatus.completed,
    )
    state = consultant_order_state(_contract(ended), TODAY, is_current=True)
    assert state.attention == (ATTENTION_NO_CURRENT_ORDER,)
    # Najnowsze zamówienie zostaje w kolumnie — widać, od kiedy brakuje.
    assert state.order_end_date == date(2026, 10, 31)


def test_order_ending_within_30_days_without_successor():
    current = _order(1, start=date(2026, 9, 1), end=TODAY + timedelta(days=12))
    state = consultant_order_state(_contract(current), TODAY, is_current=True)
    assert state.attention == (ATTENTION_ORDER_ENDING,)
    assert state.order_ending_on == TODAY + timedelta(days=12)
    assert state.order_end_date == TODAY + timedelta(days=12)


def test_successor_order_clears_the_ending_flag():
    current = _order(1, start=date(2026, 9, 1), end=TODAY + timedelta(days=12))
    successor = _order(
        2,
        start=TODAY + timedelta(days=13),
        end=date(2027, 6, 30),
        status=ClientOrderStatus.draft,
    )
    state = consultant_order_state(
        _contract(current, successor), TODAY, is_current=True
    )
    assert state.attention == ()
    # Kolumna pokazuje zamówienie, które obowiązuje dziś, nie przyszłe.
    assert state.order_end_date == TODAY + timedelta(days=12)


def test_notice_comes_first_and_planned_contract_is_not_flagged_for_orders():
    notice = consultant_order_state(
        _contract(status=ContractStatus.ending), TODAY, is_current=True
    )
    assert notice.attention == (ATTENTION_NOTICE, ATTENTION_NO_CURRENT_ORDER)

    planned = consultant_order_state(_contract(), TODAY, is_current=False)
    assert planned.attention == ()

    draft = consultant_order_state(
        _contract(status=ContractStatus.draft), TODAY, is_current=True
    )
    assert draft.attention == ()


def test_md_line_without_own_dates_reads_the_group_period():
    group = SimpleNamespace(
        id=7, start_date=date(2026, 11, 1), end_date=date(2026, 12, 31)
    )
    line = _order(1, start=None, end=None, group=group)
    contract = _contract(line)
    assert lacks_current_order(contract, TODAY) is False
    state = consultant_order_state(contract, TODAY, is_current=True)
    assert state.attention == ()
    assert state.order_start_date == date(2026, 11, 1)
    assert state.order_end_date == date(2026, 12, 31)


def test_cancelled_order_is_neither_shown_nor_coverage():
    cancelled = _order(
        1, start=date(2026, 11, 1), end=None, status=ClientOrderStatus.cancelled
    )
    state = consultant_order_state(_contract(cancelled), TODAY, is_current=True)
    assert state.attention == (ATTENTION_NO_CURRENT_ORDER,)
    assert state.order_start_date is None


def test_draft_order_covers_the_day_but_is_marked_as_draft():
    draft = _order(1, start=date(2026, 11, 3), end=None, status=ClientOrderStatus.draft)
    state = consultant_order_state(_contract(draft), TODAY, is_current=True)
    # Szkic liczy się jako pokrycie (zaślepka z hooka zatrudnienia)…
    assert state.attention == ()
    # …ale wiersz mówi, że zamówienie jest do uzupełnienia.
    assert state.order_status == "draft"
    assert state.order_start_date == date(2026, 11, 3)
