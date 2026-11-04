"""Nocne przywrócenie statusu zamówieniom okresowym z TRWAJĄCYM okresem.

Zgłoszenie 29.09.2026 (kafelki kontraktorów Erste): zamówienie ze statusem
``completed`` i datą końca w przyszłości sprawiało, że karta mówiła „Brak
aktywnego zamówienia" i chowała „Zakończ zamówienie", choć okres obejmował
dziś. Każda droga zamykająca zamówienie ucina jego datę końca do dnia
zamknięcia, więc ``completed`` z późniejszym końcem to rozjazd po edycji dat
sprzed #1638 — nocny skaner go domyka (``revive_stale_completed_periodic_orders``).

Baza testowa jest wspólna i nie jest czyszczona, a funkcja skanuje CAŁĄ bazę,
więc każdy test bierze „dziś" z dalekiego roku (inny rok na test), a asercje
dotyczą wyłącznie własnych wierszy.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.order_type import OrderType
from app.tasks import dl_portal_expiry_scanner as scanner
from app.tasks.dl_portal_expiry_scanner import (
    _revive_stale_completed_periodic_orders_safely,
    one_stale_order_per_contract,
    revive_stale_completed_periodic_orders,
    run_once,
)


def _far_today(year: int) -> date:
    """Losowy „dzisiejszy" dzień z jednego, wyłącznie tego testu, roku."""
    return date.fromordinal(
        random.randint(date(year, 1, 1).toordinal(), date(year, 12, 1).toordinal())
    )


# ── Wybór kandydata (bez bazy) ───────────────────────────────────────────────


def _row(order_id: int, **overrides) -> SimpleNamespace:
    values = dict(
        id=order_id,
        contract_id=1,
        client_id=103,
        order_type="periodic",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 9, 30),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_one_order_per_contract_prefers_latest_start_then_end_then_id():
    rows = [
        _row(1, start_date=date(2026, 7, 1)),
        _row(2, start_date=date(2026, 8, 1)),
        _row(3, start_date=date(2026, 8, 1), end_date=date(2026, 10, 31)),
        _row(4, start_date=date(2026, 8, 1), end_date=date(2026, 10, 31)),
        _row(5, contract_id=2),
    ]
    assert one_stale_order_per_contract(rows) == [4, 5]


def test_legacy_null_type_is_periodic_for_ordinary_clients_only(monkeypatch):
    # `conftest` zeruje mapę legacy, żeby seryjne id klientów testowych nie
    # zderzało się z prawdziwymi (Polkomtel = 15); tu przywracamy ją jawnie.
    monkeypatch.setattr(
        "app.services.order_types._LEGACY_NULL_ORDER_TYPES", {15: OrderType.md}
    )
    ordinary = _row(1, order_type=None, client_id=103)
    md_client = _row(2, order_type=None, client_id=15, contract_id=2)
    assert one_stale_order_per_contract([ordinary, md_client]) == [1]


@pytest.mark.parametrize("order_type", ["md", "cost"])
def test_budget_orders_keep_their_own_lifecycle(order_type):
    assert one_stale_order_per_contract([_row(1, order_type=order_type)]) == []


def test_no_candidates_no_ids():
    assert one_stale_order_per_contract([]) == []


# ── SQL na bazie ─────────────────────────────────────────────────────────────


async def _contract(
    *,
    today: date,
    status: ContractStatus = ContractStatus.active,
    end_date: date | None = None,
) -> dict[str, int]:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Revive {suffix}")
        candidate = Candidate(
            name="Jan",
            lastname=f"Revive-{suffix}",
            email=f"revive-{suffix}@example.com",
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=status,
            start_date=today - timedelta(days=300),
            end_date=end_date,
            rate_candidate=Decimal("110"),
            # Bez stawki przychodowej: wyceniony kontrakt wypycha cudzy wiersz
            # z globalnego rankingu marży (`test_contract_analytics`).
            rate_client=None,
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return {"client_id": client.id, "contract_id": contract.id}


async def _order(
    ids: dict[str, int],
    *,
    start: date | None,
    end: date | None,
    status: ClientOrderStatus = ClientOrderStatus.completed,
    **extra,
) -> int:
    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=ids["client_id"],
            contract_id=ids["contract_id"],
            title=f"REV-{uuid.uuid4().hex[:6]}",
            status=status,
            start_date=start,
            end_date=end,
            rate_unit=RateUnit.hourly,
            rate_client=Decimal("145"),
            rate_candidate=Decimal("110"),
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            currency="PLN",
            **extra,
        )
        db.add(order)
        await db.commit()
        return order.id


async def _revive(today: date) -> int:
    async with AsyncSessionLocal() as db:
        revived = await revive_stale_completed_periodic_orders(db, business_day=today)
        await db.commit()
        return revived


async def _status(order_id: int) -> ClientOrderStatus:
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        return order.status


async def test_completed_order_with_a_running_period_is_revived():
    """Sedno zgłoszenia: okres 01.09–30.09, dziś 29.09, a status `completed`."""
    today = _far_today(2091)
    ids = await _contract(today=today)
    order_id = await _order(
        ids, start=today - timedelta(days=28), end=today + timedelta(days=1)
    )

    assert await _revive(today) >= 1

    assert await _status(order_id) == ClientOrderStatus.active
    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "client_order",
                Activity.entity_id == order_id,
                Activity.action == "status_auto_changed",
            )
        )
    assert activity is not None and activity.user_id is None
    assert activity.details["from_status"] == "completed"
    assert activity.details["to_status"] == "active"
    assert activity.details["reason"] == "period_still_running"
    assert activity.details["contract_id"] == ids["contract_id"]


async def test_second_run_changes_nothing():
    today = _far_today(2092)
    ids = await _contract(today=today)
    order_id = await _order(
        ids, start=today - timedelta(days=10), end=today + timedelta(days=20)
    )
    await _revive(today)
    async with AsyncSessionLocal() as db:
        again = await revive_stale_completed_periodic_orders(db, business_day=today)
        await db.commit()
    assert again == 0
    assert await _status(order_id) == ClientOrderStatus.active


async def test_order_closed_today_stays_completed():
    """„Zakończ zamówienie" z datą dzisiejszą zostawia koniec == dziś."""
    today = _far_today(2093)
    ids = await _contract(today=today)
    order_id = await _order(ids, start=today - timedelta(days=30), end=today)

    await _revive(today)

    assert await _status(order_id) == ClientOrderStatus.completed


async def test_period_that_has_not_started_or_is_missing_a_date_stays_completed():
    today = _far_today(2094)
    ids = await _contract(today=today)
    not_started = await _order(
        ids, start=today + timedelta(days=5), end=today + timedelta(days=40)
    )
    no_start = await _order(ids, start=None, end=today + timedelta(days=40))
    open_ended = await _order(ids, start=today - timedelta(days=40), end=None)

    await _revive(today)

    assert await _status(not_started) == ClientOrderStatus.completed
    assert await _status(no_start) == ClientOrderStatus.completed
    # Zamknięte bez daty końca to historia, nie rozjazd okresu.
    assert await _status(open_ended) == ClientOrderStatus.completed


async def test_duplicate_of_a_live_order_stays_in_history():
    """Kontrakt #479: stary `completed` z importu obok aktywnego zamówienia
    tego samego okresu. Przywrócenie dałoby dwa aktywne wiersze."""
    today = _far_today(2095)
    ids = await _contract(today=today)
    start, end = today - timedelta(days=90), today + timedelta(days=1)
    stale = await _order(ids, start=start, end=end)
    live = await _order(ids, start=start, end=end, status=ClientOrderStatus.active)

    await _revive(today)

    assert await _status(stale) == ClientOrderStatus.completed
    assert await _status(live) == ClientOrderStatus.active


async def test_paused_order_covering_today_also_counts_as_served():
    today = _far_today(2096)
    ids = await _contract(today=today)
    stale = await _order(
        ids, start=today - timedelta(days=30), end=today + timedelta(days=10)
    )
    await _order(
        ids,
        start=today - timedelta(days=30),
        end=today + timedelta(days=10),
        status=ClientOrderStatus.paused,
    )

    await _revive(today)

    assert await _status(stale) == ClientOrderStatus.completed


async def test_live_order_that_does_not_cover_today_does_not_block_the_revive():
    """Aktywne zamówienie z PRZYSZŁOŚCI nie obsługuje kontraktora dziś."""
    today = _far_today(2097)
    ids = await _contract(today=today)
    stale = await _order(
        ids, start=today - timedelta(days=30), end=today + timedelta(days=3)
    )
    await _order(
        ids,
        start=today + timedelta(days=4),
        end=today + timedelta(days=90),
        status=ClientOrderStatus.active,
    )

    await _revive(today)

    assert await _status(stale) == ClientOrderStatus.active


async def test_only_one_of_two_stale_duplicates_is_revived():
    today = _far_today(2098)
    ids = await _contract(today=today)
    start, end = today - timedelta(days=60), today + timedelta(days=2)
    older = await _order(ids, start=start, end=end)
    newer = await _order(ids, start=start, end=end)

    assert await _revive(today) >= 1

    statuses = {await _status(older), await _status(newer)}
    assert statuses == {ClientOrderStatus.active, ClientOrderStatus.completed}
    assert await _status(newer) == ClientOrderStatus.active  # wyższe id wygrywa

    # Kolejny bieg widzi już „obsłużony" kontrakt i nie rusza drugiego.
    await _revive(today)
    assert await _status(older) == ClientOrderStatus.completed


async def test_ending_contract_gets_its_order_back():
    """Kontrakt #437 (`ending`): konsultant pracuje do końca umowy."""
    today = _far_today(2099)
    ids = await _contract(
        today=today,
        status=ContractStatus.ending,
        end_date=today + timedelta(days=1),
    )
    order_id = await _order(
        ids, start=today - timedelta(days=90), end=today + timedelta(days=1)
    )

    await _revive(today)

    assert await _status(order_id) == ClientOrderStatus.active


async def test_ended_contract_is_never_touched():
    """Wskrzeszanie umów jest decyzją ludzi, nie efektem ubocznym naprawy."""
    today = _far_today(2100)
    ids = await _contract(
        today=today,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=5),
    )
    order_id = await _order(
        ids, start=today - timedelta(days=90), end=today + timedelta(days=10)
    )

    await _revive(today)

    assert await _status(order_id) == ClientOrderStatus.completed


async def test_contract_past_its_end_date_is_left_to_the_contract_cron():
    """Umowa z minioną datą końca, której cron jeszcze nie zamknął: przywrócone
    zamówienie zmieniałoby status dwa razy w ciągu doby."""
    today = _far_today(2103)
    ids = await _contract(
        today=today,
        status=ContractStatus.active,
        end_date=today - timedelta(days=2),
    )
    order_id = await _order(
        ids, start=today - timedelta(days=90), end=today + timedelta(days=10)
    )

    await _revive(today)

    assert await _status(order_id) == ClientOrderStatus.completed


async def test_order_that_outlives_its_ending_contract_is_left_alone():
    """Zamówienie nie przeżywa umowy: przywrócone po dacie końca umowy mogłoby
    — gdy nocny reconcile wyprzedzi cron umów — wskrzesić wypowiedzianą umowę."""
    today = _far_today(2104)
    ids = await _contract(
        today=today,
        status=ContractStatus.ending,
        end_date=today + timedelta(days=3),
    )
    order_id = await _order(
        ids, start=today - timedelta(days=90), end=today + timedelta(days=10)
    )

    await _revive(today)

    assert await _status(order_id) == ClientOrderStatus.completed


async def _group_line(
    ids: dict[str, int], *, today: date, status: ClientOrderStatus
) -> None:
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=ids["client_id"],
            order_number=f"G-{uuid.uuid4().hex[:6]}",
            order_type="md",
            status="active",
            start_date=today - timedelta(days=60),
            end_date=None,
        )
        db.add(group)
        await db.commit()
        group_id = group.id
    await _order(
        ids,
        start=today - timedelta(days=60),
        end=None,
        status=status,
        order_group_id=group_id,
    )


async def test_person_on_an_open_group_line_keeps_the_stale_order_in_history():
    """Okresowe obok żywej linii MD/kosztowej to drugi zapis tej samej
    współpracy — aplikacja odmawia go przy ręcznym zakładaniu."""
    today = _far_today(2105)
    ids = await _contract(today=today)
    stale = await _order(
        ids, start=today - timedelta(days=30), end=today + timedelta(days=10)
    )
    await _group_line(ids, today=today, status=ClientOrderStatus.active)

    await _revive(today)

    assert await _status(stale) == ClientOrderStatus.completed


async def test_finished_group_line_does_not_block_the_revive():
    """Tylko OTWARTA linia (draft/active/paused) blokuje; historia nie."""
    today = _far_today(2106)
    ids = await _contract(today=today)
    stale = await _order(
        ids, start=today - timedelta(days=30), end=today + timedelta(days=10)
    )
    await _group_line(ids, today=today, status=ClientOrderStatus.completed)

    await _revive(today)

    assert await _status(stale) == ClientOrderStatus.active


async def test_budget_orders_and_cancelled_orders_are_left_alone():
    today = _far_today(2101)
    ids = await _contract(today=today)
    span = dict(start=today - timedelta(days=30), end=today + timedelta(days=10))
    md = await _order(ids, order_type="md", **span)
    cost = await _order(ids, order_type="cost", **span)
    cancelled = await _order(ids, status=ClientOrderStatus.cancelled, **span)

    await _revive(today)

    assert await _status(md) == ClientOrderStatus.completed
    assert await _status(cost) == ClientOrderStatus.completed
    assert await _status(cancelled) == ClientOrderStatus.cancelled


async def test_order_of_another_client_than_its_contract_is_left_alone():
    """`client_orders.client_id` bywa rozjechane z klientem umowy — wtedy nie
    zgadujemy, czyje to zamówienie."""
    today = _far_today(2102)
    ids = await _contract(today=today)
    async with AsyncSessionLocal() as db:
        other = Client(name=f"Revive other {uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        other_id = other.id
    order_id = await _order(
        {"client_id": other_id, "contract_id": ids["contract_id"]},
        start=today - timedelta(days=30),
        end=today + timedelta(days=10),
    )

    await _revive(today)

    assert await _status(order_id) == ClientOrderStatus.completed


async def test_failure_of_the_revive_step_is_isolated(monkeypatch):
    """Błąd naprawy nie może zatrzymać przejść statusów i alertów po niej."""

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(scanner, "revive_stale_completed_periodic_orders", boom)
    async with AsyncSessionLocal() as db:
        assert await _revive_stale_completed_periodic_orders_safely(db) == 0
        # Transakcja żyje: kolejny krok skanera może z niej korzystać.
        assert await db.scalar(select(1)) == 1


async def test_run_once_revives_the_order_and_reports_it():
    today = business_today()
    ids = await _contract(today=today)
    order_id = await _order(
        ids, start=today - timedelta(days=28), end=today + timedelta(days=1)
    )

    summary = await run_once()

    assert summary["orders_revived"] >= 1
    assert await _status(order_id) == ClientOrderStatus.active
