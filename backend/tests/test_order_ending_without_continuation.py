"""Jedna reguła „zamówienie kończy się bez kontynuacji" (audyt 24.09.2026).

* W2 — porzucony szkic (bez daty końca i bez stawki przychodowej, np. szkic
  z podpisu umowy) nie jest następcą; szkic uzupełniony nadal jest.
* N2 — zamówienie zakończone z datą końca w przyszłości nie jest następcą.
* S1 — pole liczone na serwerze dla pigułki „Bez kontynuacji 30d" i ta sama
  reguła w SQL (panel „Moi klienci", dzwonek, kafelek pulpitu).
* S2 — kontrakt ``ended``/``void`` sam wystarcza jako zamiar zakończenia.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.services.order_continuation import (
    ending_without_successor,
    order_ending_without_continuation,
)
from app.services.order_facts import OrderFact, covers_after, successor_of

_TODAY = date(2026, 9, 24)


def _fact(order_id: int, **overrides) -> OrderFact:
    values = dict(
        order_id=order_id,
        order_group_id=None,
        contract_id=1,
        candidate_id=5,
        client_id=10,
        client_name="Klient",
        consultant_name="Jan Nowak",
        status="active",
        start=date(2026, 1, 1),
        end=date(2026, 8, 31),
        number=f"NB-{order_id}",
        order_type="periodic",
        rate_cost=Decimal("100"),
        rate_revenue=Decimal("150"),
        rate_unit="hourly",
        currency="PLN",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    values.update(overrides)
    return OrderFact(**values)


def _order(order_id: int, **overrides) -> ClientOrder:
    values = dict(
        id=order_id,
        client_id=10,
        contract_id=1,
        title=f"Z-{order_id}",
        status=ClientOrderStatus.active,
        start_date=date(2026, 1, 1),
        end_date=_TODAY + timedelta(days=10),
        rate_client=Decimal("150"),
        rate_unit=RateUnit.hourly,
        order_group_id=None,
    )
    values.update(overrides)
    return ClientOrder(**values)


# ── W2 / N2: kto jest następcą ───────────────────────────────────────────────


def test_empty_signing_draft_is_not_a_successor():
    """Szkic z podpisu: start umowy, brak końca, brak stawki klienta."""
    ended = _fact(1)
    shell = _fact(
        2, status="draft", start=date(2026, 1, 1), end=None, rate_revenue=None
    )

    assert not covers_after(shell, ended.end, today=_TODAY)
    assert successor_of(ended, [ended, shell]) is None


def test_filled_draft_is_still_a_planned_continuation():
    ended = _fact(1)
    with_rate = _fact(2, status="draft", start=None, end=None)
    with_end = _fact(
        3, status="draft", start=None, end=date(2026, 12, 31), rate_revenue=None
    )

    assert successor_of(ended, [ended, with_rate]) == with_rate
    assert successor_of(ended, [ended, with_end]) == with_end


def test_completed_order_ending_in_the_future_is_not_a_successor():
    ended = _fact(1, end=_TODAY + timedelta(days=5))
    closed_early = _fact(
        2,
        status="completed",
        start=_TODAY + timedelta(days=6),
        end=_TODAY + timedelta(days=60),
    )

    assert not covers_after(closed_early, ended.end, today=_TODAY)
    # Zakończone w PRZESZŁOŚCI nadal jest historycznym następcą (Finanse →
    # Zejścia za miniony miesiąc).
    past = _fact(3, status="completed", start=date(2026, 9, 1), end=date(2026, 9, 20))
    assert covers_after(past, date(2026, 8, 31), today=_TODAY)


# ── S1: pole dla pigułki ─────────────────────────────────────────────────────


def test_ending_order_without_successor_is_reported_with_days_left():
    found = ending_without_successor([_order(1)], today=_TODAY)
    assert found is not None
    assert (found.order_id, found.days_left) == (1, 10)


def test_ending_order_with_added_extension_is_not_reported():
    orders = [
        _order(1),
        _order(
            2,
            status=ClientOrderStatus.draft,
            start_date=_TODAY + timedelta(days=11),
            end_date=_TODAY + timedelta(days=100),
        ),
    ]
    assert ending_without_successor(orders, today=_TODAY) is None


def test_active_md_budget_order_counts_as_continuation_like_the_sql_rule():
    """Pigułka i karta DL liczą tak samo: aktywne zamówienie z pozostałym
    budżetem MD pracuje po dacie końca (przegląd integracji 24.09.2026)."""
    orders = [
        _order(1),
        _order(
            2,
            start_date=date(2026, 1, 1),
            end_date=_TODAY - timedelta(days=60),
            md_total=Decimal("40"),
            md_remaining=Decimal("5"),
        ),
    ]
    assert ending_without_successor(orders, today=_TODAY) is None


def test_empty_signing_draft_does_not_hide_the_ending_order():
    orders = [
        _order(1),
        _order(
            2,
            status=ClientOrderStatus.draft,
            end_date=None,
            rate_client=None,
        ),
    ]
    found = ending_without_successor(orders, today=_TODAY)
    assert found is not None and found.order_id == 1


def test_group_lines_and_orders_outside_the_window_are_ignored():
    assert ending_without_successor([_order(1, order_group_id=7)], today=_TODAY) is None
    assert (
        ending_without_successor(
            [_order(1, end_date=_TODAY + timedelta(days=31))], today=_TODAY
        )
        is None
    )
    assert (
        ending_without_successor(
            [_order(1, end_date=_TODAY - timedelta(days=1))], today=_TODAY
        )
        is None
    )


def test_sql_rule_excludes_empty_drafts_and_future_completed_successors():
    """Predykat SQL niesie oba wyjątki (lustro ``covers_after``)."""
    from sqlalchemy import select

    sql = str(
        select(ClientOrder.id)
        .where(
            order_ending_without_continuation(
                _TODAY,
                _TODAY + timedelta(days=30),
                extended_client_ids=frozenset({12}),
                today=_TODAY,
            )
        )
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "coalesce(client_orders_1.rate_client, client_orders_1.md_rate_revenue" in (
        sql
    )
    assert "'2026-09-24'" in sql
    assert "client_order_groups.status = 'active'" in sql


# ── S2: kontrakt zakończony sam jest zamiarem ───────────────────────────────


@pytest.mark.asyncio
async def test_ended_contract_is_an_ending_intent_even_if_it_ends_after_the_order():
    """Kontrakt ended z końcem 31.08, zamówienie do 30.08 → zamiar zakończenia."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.services.order_facts import (
        INTENT_CONTRACT_ENDED,
        load_ending_intents,
        load_facts,
    )

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Intent {suffix}")
        candidate = Candidate(
            name="Jan", lastname=f"Intent-{suffix}", email=f"i-{suffix}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.ended,
            start_date=date(2031, 1, 1),
            end_date=date(2031, 8, 31),
            rate_candidate=Decimal("100.000"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"Z-{suffix}",
            status=ClientOrderStatus.completed,
            start_date=date(2031, 1, 1),
            end_date=date(2031, 8, 30),
            rate_client=Decimal("150.000"),
            rate_unit=RateUnit.hourly,
        )
        db.add(order)
        await db.flush()
        facts = await load_facts(db, ClientOrder.id == order.id)
        intents = await load_ending_intents(db, facts)
        await db.rollback()

    assert intents == {facts[0].order_id: INTENT_CONTRACT_ENDED}


@pytest.mark.asyncio
async def test_contractor_list_carries_the_server_side_ending_flag(
    app_client, app_auth_headers
):
    """Pigułka „Bez kontynuacji 30d" czyta pole z serwera (S1)."""
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.candidate import Candidate
    from app.models.client import Client

    today = business_today()
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Ending {suffix}")
        candidate = Candidate(
            name="Ewa", lastname=f"Ending-{suffix}", email=f"e-{suffix}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=today - timedelta(days=200),
            rate_candidate=Decimal("100.000"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.flush()
        ending = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"Z-{suffix}",
            status=ClientOrderStatus.active,
            start_date=today - timedelta(days=100),
            end_date=today + timedelta(days=12),
            rate_client=Decimal("150.000"),
            rate_unit=RateUnit.hourly,
        )
        shell = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="(bez numeru)",
            status=ClientOrderStatus.draft,
            start_date=today - timedelta(days=200),
            rate_unit=RateUnit.hourly,
        )
        db.add_all([ending, shell])
        await db.commit()
        client_id, ending_id = client.id, ending.id

    resp = await app_client.get(
        f"/api/clients/{client_id}/orders", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    [card] = resp.json()["contractors"]
    assert card["ending_without_successor_order_id"] == ending_id
    assert card["ending_without_successor_days"] == 12
