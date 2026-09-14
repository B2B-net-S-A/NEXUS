"""Finanse → Zmiany w zamówieniach: dziennik zmian, Braki i widok miesiąca.

Baza testowa jest wspólna dla całego przebiegu i nie jest czyszczona, więc
każdy test pracuje na własnym kliencie i na datach losowanych z dalekich lat —
a asercje filtrują wyniki po swoim kliencie.
"""

from __future__ import annotations

import io
import random
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.services.order_facts import OrderFact, covers_after, previous_of, successor_of

pytestmark = pytest.mark.asyncio


def _far_day(first_year: int, last_year: int) -> date:
    """Losowy dzień z dalekich lat — sąsiednie testy nie trafią w ten sam."""
    start = date(first_year, 1, 1).toordinal()
    end = date(last_year, 12, 20).toordinal()
    return date.fromordinal(random.randint(start, end))


# ── Reguły następcy (bez bazy) ──────────────────────────────────────────────


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


def test_successor_counts_active_future_and_draft_but_not_cancelled_or_finished():
    ended = _fact(1)
    future = _fact(2, start=date(2026, 10, 1), end=date(2026, 12, 31))
    draft = _fact(3, status="draft", start=None, end=None)
    cancelled = _fact(4, status="cancelled", start=date(2026, 9, 1), end=None)
    finished_undated = _fact(5, status="completed", start=None, end=None)

    assert successor_of(ended, [ended, future]) == future
    assert successor_of(ended, [ended, draft]) == draft
    assert successor_of(ended, [ended, cancelled]) is None
    assert successor_of(ended, [ended, finished_undated]) is None
    assert not covers_after(_fact(6, end=date(2026, 8, 31)), date(2026, 8, 31))


def test_successor_ignores_the_order_itself_unless_it_was_extended():
    ended = _fact(1)
    extended = replace(ended, end=date(2026, 12, 31))
    assert successor_of(ended, [ended]) is None
    assert successor_of(ended, [extended], include_self=True) == extended


def test_continuation_means_previous_order_ended_within_a_month_before_start():
    new = _fact(2, start=date(2026, 9, 1), end=date(2026, 12, 31))
    recent = _fact(1, end=date(2026, 8, 31))
    long_ago = _fact(3, end=date(2026, 6, 30))
    assert previous_of(new, [new, recent]) == recent
    assert previous_of(new, [new, long_ago]) is None


# ── Dane w bazie ────────────────────────────────────────────────────────────


async def _seed(
    *,
    start: date,
    end: date,
    status: ClientOrderStatus = ClientOrderStatus.active,
    contract_status: ContractStatus = ContractStatus.active,
    client_name: str | None = None,
) -> dict[str, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=client_name or f"FinOrders {suffix}")
        candidate = Candidate(
            name="Jan", lastname=f"Nowak-{suffix}", email=f"foc-{suffix}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=contract_status,
            start_date=start,
            rate_candidate=Decimal("960.000"),
            rate_client=Decimal("1340.000"),
            rate_unit=RateUnit.daily,
            currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.flush()
        order = _order(client.id, contract.id, start=start, end=end, status=status)
        db.add(order)
        await db.commit()
        return {
            "client_id": client.id,
            "candidate_id": candidate.id,
            "contract_id": contract.id,
            "order_id": order.id,
        }


def _order(
    client_id: int,
    contract_id: int,
    *,
    start: date | None,
    end: date | None,
    status: ClientOrderStatus = ClientOrderStatus.active,
    title: str | None = None,
    **extra,
) -> ClientOrder:
    return ClientOrder(
        client_id=client_id,
        contract_id=contract_id,
        title=title or f"NB-{uuid.uuid4().hex[:6]}",
        status=status,
        start_date=start,
        end_date=end,
        rate_unit=RateUnit.daily,
        rate_client=Decimal("1340.000"),
        rate_candidate=Decimal("960.000"),
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
        currency="PLN",
        **extra,
    )


async def _add_order(ids: dict[str, int], **kwargs) -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        order = _order(ids["client_id"], ids["contract_id"], **kwargs)
        db.add(order)
        await db.commit()
        return order.id


async def _gap_for(order_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.order_gap import OrderGap

    async with AsyncSessionLocal() as db:
        return await db.scalar(select(OrderGap).where(OrderGap.order_id == order_id))


async def _detect(monkeypatch, *, tracking_start: date, today: date) -> None:
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.services.order_gaps import detect_order_gaps

    monkeypatch.setattr(settings, "ORDER_GAP_TRACKING_START", tracking_start)
    async with AsyncSessionLocal() as db:
        await detect_order_gaps(db, today=today)
        await db.commit()


async def _seed_dl(client_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"foc-dl-{suffix}@example.com",
            password_hash=hash_password(f"T3st_{suffix}!PassX"),
            name="DL Zamówień",
            role=UserRole.delivery_lead,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                client_id=client_id, delivery_lead_user_id=user.id
            )
        )
        await db.commit()
        return user.id


async def _login(app_client: AsyncClient, role: str) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    email = f"foc-{role}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Foc {role}",
                role=UserRole(role),
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── Dziennik zmian ──────────────────────────────────────────────────────────


async def _events(order_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.order_change_event import OrderChangeEvent

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(OrderChangeEvent)
                    .where(OrderChangeEvent.order_id == order_id)
                    .order_by(OrderChangeEvent.id)
                )
            ).all()
        )


async def test_rate_and_end_date_change_is_recorded_with_old_and_new_value(
    app_client: AsyncClient, app_auth_headers: dict
):
    day = _far_day(2081, 2084)
    ids = await _seed(start=day, end=day + timedelta(days=90))

    resp = await app_client.patch(
        f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}",
        json={
            "rate_client": "1400",
            "end_date": (day + timedelta(days=180)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    events = {event.field: event for event in await _events(ids["order_id"])}
    revenue = events["rate_revenue"]
    assert (revenue.old_amount, revenue.new_amount) == (
        Decimal("1340"),
        Decimal("1400"),
    )
    assert (revenue.old_unit, revenue.new_unit) == ("daily", "daily")
    assert revenue.source == "user" and revenue.created_by_user_id is not None
    end = events["end_date"]
    assert (end.old_date, end.new_date) == (
        day + timedelta(days=90),
        day + timedelta(days=180),
    )
    assert "rate_cost" not in events, "stawka kosztowa się nie zmieniła"


async def test_filling_a_draft_is_not_a_change(
    app_client: AsyncClient, app_auth_headers: dict
):
    day = _far_day(2081, 2084)
    ids = await _seed(
        start=day, end=day + timedelta(days=90), status=ClientOrderStatus.draft
    )

    resp = await app_client.patch(
        f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}",
        json={
            "rate_client": "1500",
            "end_date": (day + timedelta(days=120)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert await _events(ids["order_id"]) == []


async def test_system_write_without_logged_user_is_marked_as_system():
    from app.core.database import AsyncSessionLocal

    day = _far_day(2081, 2084)
    ids = await _seed(start=day, end=day + timedelta(days=90))
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, ids["order_id"])
        order.rate_candidate = Decimal("1000")
        await db.commit()

    [event] = await _events(ids["order_id"])
    assert event.field == "rate_cost" and event.source == "system"
    assert event.created_by_user_id is None


async def test_rate_reverted_by_contract_sync_in_the_same_request_is_not_a_change(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Stan pośredni (100 → 120 → 100 przez synchronizację) nie jest zmianą."""
    day = _far_day(2081, 2084)
    ids = await _seed(start=day, end=day + timedelta(days=90))

    resp = await app_client.patch(
        f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}",
        # Koszt należy do umowy — synchronizacja przywraca 960 przed commitem.
        json={"rate_candidate": "999"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(str(resp.json()["rate_candidate"])) == Decimal("960")
    assert [event.field for event in await _events(ids["order_id"])] == []


# ── Braki ───────────────────────────────────────────────────────────────────


async def test_order_ended_without_successor_becomes_an_open_gap_with_dl_alert(
    monkeypatch,
):
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_ORDER_MISSING_SUCCESSOR, DlAlert
    from app.models.notification import Notification, NotificationType

    end = _far_day(2085, 2088)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    dl_id = await _seed_dl(ids["client_id"])

    await _detect(monkeypatch, tracking_start=end, today=end + timedelta(days=1))

    gap = await _gap_for(ids["order_id"])
    assert gap is not None and gap.status == "open"
    assert gap.detected_on == end + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        alerts = (
            await db.scalars(
                select(DlAlert).where(
                    DlAlert.user_id == dl_id,
                    DlAlert.alert_type == ALERT_ORDER_MISSING_SUCCESSOR,
                )
            )
        ).all()
        bell = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == dl_id,
                    Notification.notification_type
                    == NotificationType.order_missing_successor,
                )
            )
        ).all()
    assert (
        len(alerts) == 1
        and alerts[0].link == f"/clients/{ids['client_id']}?tab=zamowienia"
    )
    assert len(bell) == 1

    # Drugi przebieg nie dubluje ani braku, ani powiadomień.
    await _detect(monkeypatch, tracking_start=end, today=end + timedelta(days=2))
    async with AsyncSessionLocal() as db:
        again = (
            await db.scalars(select(Notification).where(Notification.user_id == dl_id))
        ).all()
    assert len(again) == 1


async def test_gap_is_not_detected_on_the_last_day_of_the_order(monkeypatch):
    end = _far_day(2085, 2088)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    await _detect(monkeypatch, tracking_start=end, today=end)
    assert await _gap_for(ids["order_id"]) is None


async def test_draft_successor_counts_as_planned(monkeypatch):
    end = _far_day(2085, 2088)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    await _add_order(ids, start=None, end=None, status=ClientOrderStatus.draft)
    await _detect(monkeypatch, tracking_start=end, today=end + timedelta(days=1))
    assert await _gap_for(ids["order_id"]) is None


async def test_terminated_contract_is_a_deliberate_end_not_a_gap(monkeypatch):
    from app.core.database import AsyncSessionLocal

    end = _far_day(2085, 2088)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["contract_id"])
        contract.terminated_at = end - timedelta(days=20)
        contract.end_date = end
        await db.commit()
    await _detect(monkeypatch, tracking_start=end, today=end + timedelta(days=1))
    assert await _gap_for(ids["order_id"]) is None


async def test_replaced_consultant_is_not_a_gap(monkeypatch):
    end = _far_day(2085, 2088)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    other = await _seed(start=end + timedelta(days=1), end=end + timedelta(days=90))
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        replacement = await db.get(ClientOrder, other["order_id"])
        replacement.predecessor_order_id = ids["order_id"]
        await db.commit()
    await _detect(monkeypatch, tracking_start=end, today=end + timedelta(days=1))
    assert await _gap_for(ids["order_id"]) is None


async def test_successor_added_after_the_day_of_detection_is_recorded_as_late(
    monkeypatch,
):
    """Przebieg po deployu: następca jest, ale dodany po terminie."""
    end = _far_day(2001, 2020)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    late_id = await _add_order(
        ids, start=end + timedelta(days=10), end=end + timedelta(days=100)
    )
    await _detect(monkeypatch, tracking_start=end, today=end + timedelta(days=30))

    gap = await _gap_for(ids["order_id"])
    assert gap is not None and gap.status == "filled_late"
    assert gap.resolved_order_id == late_id


async def test_adding_the_order_later_keeps_the_gap_as_filled_late(
    monkeypatch, app_client: AsyncClient, app_auth_headers: dict
):
    """Zapis zamówienia przez API zamyka brak od razu — wpis zostaje."""
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_ORDER_MISSING_SUCCESSOR, DlAlert

    end = _far_day(2085, 2088)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    await _seed_dl(ids["client_id"])
    await _detect(monkeypatch, tracking_start=end, today=end + timedelta(days=1))
    assert (await _gap_for(ids["order_id"])).status == "open"

    resp = await app_client.patch(
        f"/api/clients/{ids['client_id']}/orders/{ids['order_id']}",
        json={"end_date": (end + timedelta(days=90)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    gap = await _gap_for(ids["order_id"])
    assert gap.status == "filled_late" and gap.resolved_at is not None
    async with AsyncSessionLocal() as db:
        statuses = set(
            (
                await db.scalars(
                    select(DlAlert.status).where(
                        DlAlert.order_id == ids["order_id"],
                        DlAlert.alert_type == ALERT_ORDER_MISSING_SUCCESSOR,
                    )
                )
            ).all()
        )
    assert statuses == {"handled"}


# ── Widok miesiąca ──────────────────────────────────────────────────────────


async def test_month_view_lists_entries_exits_and_gaps_with_matching_counts(
    monkeypatch, app_client: AsyncClient, app_auth_headers: dict
):
    month_day = _far_day(2089, 2094)
    first = month_day.replace(day=1)
    # Osoba A: zamówienie kończy się 10. dnia, kolejne od 11. (kontynuacja).
    a = await _seed(start=first - timedelta(days=60), end=first + timedelta(days=9))
    a_next = await _add_order(
        a, start=first + timedelta(days=10), end=first + timedelta(days=120)
    )
    # Osoba B: kończy się 5. dnia i nic dalej (brak).
    b = await _seed(start=first - timedelta(days=60), end=first + timedelta(days=4))
    # Osoba A zaczyna w tym miesiącu projekt u innego klienta.
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        other_client = Client(name=f"FinOrders inny {uuid.uuid4().hex[:6]}")
        db.add(other_client)
        await db.flush()
        other_contract = Contract(
            candidate_id=a["candidate_id"],
            client_id=other_client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=first,
            rate_candidate=Decimal("960.000"),
            rate_unit=RateUnit.daily,
            currency="PLN",
        )
        db.add(other_contract)
        await db.flush()
        extra = _order(
            other_client.id,
            other_contract.id,
            start=first + timedelta(days=14),
            end=first + timedelta(days=60),
        )
        db.add(extra)
        await db.commit()
        extra_id = extra.id

    await _detect(monkeypatch, tracking_start=first, today=first + timedelta(days=20))

    resp = await app_client.get(
        f"/api/finance/order-changes?year={first.year}&month={first.month}",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    counts = body["counts"]
    assert counts == {
        "changes": len(body["changes"]),
        "entries": len(body["entries"]),
        "exits": len(body["exits"]),
        "gaps": len(body["gaps"]),
    }

    ours = {a["client_id"], b["client_id"], other_client.id}
    entries = {e["order_id"]: e for e in body["entries"] if e["client_id"] in ours}
    assert entries[a_next]["is_continuation"] is True
    assert entries[a_next]["rate_revenue"] == 1340.0
    assert entries[a_next]["order_type"] == "periodic"
    assert entries[extra_id]["is_continuation"] is False
    assert entries[extra_id]["additional_project"] is True

    exits = {e["order_id"]: e for e in body["exits"] if e["client_id"] in ours}
    assert exits[a["order_id"]]["verdict"] == "continuation"
    assert exits[b["order_id"]]["verdict"] == "no_successor"

    gaps = [g for g in body["gaps"] if g["client_id"] in ours]
    assert [g["order_id"] for g in gaps] == [b["order_id"]]
    assert gaps[0]["status"] == "open"

    additional = [
        c
        for c in body["changes"]
        if c["kind"] == "additional_project" and c["client_id"] in ours
    ]
    assert [c["order_id"] for c in additional] == [extra_id]
    assert additional[0]["other_client_names"] and additional[0]["effective_date"]

    export = await app_client.get(
        f"/api/finance/order-changes/export?year={first.year}&month={first.month}",
        headers=app_auth_headers,
    )
    assert export.status_code == 200, export.text
    workbook = load_workbook(io.BytesIO(export.content))
    assert [name.split(" (")[0] for name in workbook.sheetnames] == [
        "Zmiany",
        "Wejścia",
        "Zejścia",
        "Braki",
    ]


async def test_month_view_requires_the_finance_section(app_client: AsyncClient):
    finance = await _login(app_client, "finance")
    recruiter = await _login(app_client, "recruiter")

    allowed = await app_client.get("/api/finance/order-changes", headers=finance)
    denied = await app_client.get("/api/finance/order-changes", headers=recruiter)

    assert allowed.status_code == 200, allowed.text
    assert denied.status_code == 403


async def test_md_line_still_billing_after_its_end_date_is_not_a_gap(monkeypatch):
    """Linia MD pracuje po dacie końca, dopóki ma budżet — to nie brak."""
    from app.core.database import AsyncSessionLocal

    end = _far_day(2085, 2088)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, ids["order_id"])
        order.md_total = Decimal("100")
        order.md_remaining = Decimal("20")
        order.md_rate_revenue = Decimal("1340")
        order.md_input_mode = "md"
        order.md_input_value = Decimal("100")
        await db.commit()
    await _detect(monkeypatch, tracking_start=end, today=end + timedelta(days=1))
    assert await _gap_for(ids["order_id"]) is None


async def test_successor_on_a_contract_without_a_person_is_seen(monkeypatch):
    from app.core.database import AsyncSessionLocal

    end = _far_day(2085, 2088)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["contract_id"])
        contract.candidate_id = None
        await db.commit()
    await _add_order(ids, start=end + timedelta(days=1), end=end + timedelta(days=90))
    await _detect(monkeypatch, tracking_start=end, today=end + timedelta(days=1))
    assert await _gap_for(ids["order_id"]) is None


async def test_old_endings_outside_the_lookback_window_are_not_backfilled(monkeypatch):
    end = _far_day(2085, 2088)
    ids = await _seed(start=end - timedelta(days=60), end=end)
    await _detect(
        monkeypatch,
        tracking_start=end - timedelta(days=400),
        today=end + timedelta(days=90),
    )
    assert await _gap_for(ids["order_id"]) is None
