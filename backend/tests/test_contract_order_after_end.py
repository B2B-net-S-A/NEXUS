"""„Klient zamówił okres po zakończeniu” — konflikt do decyzji i blokada linii.

Decyzja Artura z 19.11.2026 po sprawdzeniu produkcji:

* kontrakt „Kończący się” z wypowiedzeniem na 30.11.2026 i szkicem z maila
  na 01.12.2026–31.05.2027 — szkic czekał bez sygnału, a kontrakt pokazywał
  koniec zamówienia u klienta 31.05.2027;
* umowa zlecenie zakończona 31.10.2026 z aktywną linią MD od 02.11.2026 —
  osoby nie było w aktywnych kontraktach ani w MRR.

Testy: konflikt na karcie i w kubełku listy, brak konfliktu dla zamówienia
w okresie i dla zakończonego zamówienia, okres kontraktu bez szkicu
wstrzymanego wypowiedzeniem, 422 przy żywej linii po końcu umowy nie-B2B
i dzwonek DL-a raz na zamówienie.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.services.contract_order_after_end import (
    OrderAfterEnd,
    ended_agreement_block,
    order_after_end_message,
)
from app.services.contract_order_sync import sync_contract_from_orders
from tests.test_contract_order_sync import _FakeDb, _contract, _order
from tests.test_multi_consultant_orders import (
    _create_group,
    _enable_for,
    _line_payload,
    _seed_client_with_contracts,
)

pytestmark = pytest.mark.asyncio


# ── Synchronizacja: okres bez szkicu wstrzymanego wypowiedzeniem ─────────────


def _terminated_contract(end: date) -> Contract:
    return _contract(
        status=ContractStatus.ending,
        start_date=date(2026, 1, 1),
        end_date=end,
        terminated_at=end,
        termination_reason="project_ended",
        rate_client=Decimal("150.000"),
    )


async def test_period_skips_draft_held_by_termination():
    """#209: szkic z maila po wypowiedzeniu nie jest okresem zamówienia."""
    contract = _terminated_contract(date(2026, 11, 30))
    active = _order(647, start_date=date(2026, 6, 1), end_date=date(2026, 11, 30))
    held = _order(
        894,
        status=ClientOrderStatus.draft,
        start_date=date(2026, 12, 1),
        end_date=date(2027, 5, 31),
    )

    await sync_contract_from_orders(
        _FakeDb(), contract, [active, held], actor_id=None, today=date(2026, 11, 20)
    )

    assert (contract.client_order_start_date, contract.client_order_end_date) == (
        date(2026, 6, 1),
        date(2026, 11, 30),
    )


async def test_only_held_draft_leaves_no_period():
    contract = _terminated_contract(date(2026, 11, 30))
    contract.client_order_start_date = date(2026, 12, 1)
    contract.client_order_end_date = date(2027, 5, 31)
    held = _order(
        894,
        status=ClientOrderStatus.draft,
        start_date=date(2026, 12, 1),
        end_date=date(2027, 5, 31),
    )

    outcome = await sync_contract_from_orders(
        _FakeDb(), contract, [held], actor_id=None, today=date(2026, 11, 20)
    )

    assert contract.client_order_start_date is None
    assert contract.client_order_end_date is None
    assert outcome.period_changed


async def test_draft_within_the_notice_period_still_sets_the_period():
    """Szkic mieszczący się przed końcem umowy wolno aktywować — okres zostaje."""
    contract = _terminated_contract(date(2026, 11, 30))
    draft = _order(
        900,
        status=ClientOrderStatus.draft,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )

    await sync_contract_from_orders(
        _FakeDb(), contract, [draft], actor_id=None, today=date(2026, 11, 20)
    )

    assert (contract.client_order_start_date, contract.client_order_end_date) == (
        date(2026, 11, 1),
        date(2026, 11, 30),
    )


async def test_reopened_contract_takes_the_period_from_the_draft_again():
    """„Cofnij zakończenie” bez daty końca: wypowiedzenie już nie obowiązuje."""
    contract = _terminated_contract(date(2026, 11, 30))
    contract.end_date = None
    contract.status = ContractStatus.active
    held_before = _order(
        894,
        status=ClientOrderStatus.draft,
        start_date=date(2026, 12, 1),
        end_date=date(2027, 5, 31),
    )

    await sync_contract_from_orders(
        _FakeDb(), contract, [held_before], actor_id=None, today=date(2026, 11, 20)
    )

    assert contract.client_order_end_date == date(2027, 5, 31)


# ── Blokada linii: komunikat ─────────────────────────────────────────────────


def _agreement(**overrides) -> Contract:
    values = {
        "id": 436,
        "client_id": 10,
        "contract_type": ContractType.uzlecenie,
        "status": ContractStatus.ended,
        "start_date": date(2026, 5, 1),
        "end_date": date(2026, 10, 31),
        "terminated_at": None,
    }
    values.update(overrides)
    return Contract(**values)


def test_ended_umowa_zlecenie_refuses_a_live_line():
    reason = ended_agreement_block(
        _agreement(), line_start=date(2026, 11, 2), today=date(2026, 11, 20)
    )
    assert reason == (
        "Umowa zlecenie zakończyła się 31.10.2026 — przedłuż ją aneksem albo "
        "załóż nowy kontrakt"
    )


def test_ending_umowa_zlecenie_refuses_a_line_after_its_end_only():
    ending = _agreement(status=ContractStatus.ending, end_date=date(2026, 11, 30))
    today = date(2026, 11, 20)
    assert ended_agreement_block(ending, line_start=date(2026, 12, 1), today=today) == (
        "Umowa zlecenie kończy się 30.11.2026 — przedłuż ją aneksem albo załóż "
        "nowy kontrakt"
    )
    assert ended_agreement_block(ending, line_start=date(2026, 11, 30)) is None
    assert ended_agreement_block(ending, line_start=date(2026, 11, 2)) is None


def test_umowa_o_prace_has_its_own_label_and_b2b_is_never_refused():
    uop = _agreement(contract_type=ContractType.uop)
    assert ended_agreement_block(
        uop, line_start=date(2026, 11, 2), today=date(2026, 11, 20)
    ).startswith("Umowa o pracę zakończyła się 31.10.2026")
    b2b = _agreement(contract_type=ContractType.b2b)
    assert ended_agreement_block(b2b, line_start=date(2026, 11, 2)) is None


def test_ended_agreement_without_any_date_still_explains_the_remedy():
    reason = ended_agreement_block(
        _agreement(end_date=None), line_start=date(2026, 11, 2)
    )
    assert reason == (
        "Umowa zlecenie jest zakończona — przedłuż ją aneksem albo załóż nowy kontrakt"
    )


def test_bell_message_names_the_decision():
    contract = _terminated_contract(date(2026, 11, 30))
    conflict = OrderAfterEnd(
        contract_id=1,
        order_id=894,
        client_id=10,
        order_group_id=None,
        order_number="4500123456",
        status="draft",
        start_date=date(2026, 12, 1),
        end_date=date(2027, 5, 31),
        held_by_termination=True,
    )
    message = order_after_end_message(contract, conflict)
    assert message.startswith(
        "Współpraca kończy się 30.11.2026, a szkic zamówienia 4500123456 "
        "obejmuje 01.12.2026–31.05.2027."
    )
    assert message.endswith(
        "cofnij zakończenie, przypisz zamówienie innej osobie albo anuluj szkic."
    )

    line = _agreement()
    line_conflict = OrderAfterEnd(
        contract_id=436,
        order_id=951,
        client_id=10,
        order_group_id=108,
        order_number="108/2026",
        status="active",
        start_date=date(2026, 11, 2),
        end_date=date(2027, 3, 31),
        held_by_termination=False,
    )
    line_message = order_after_end_message(line, line_conflict)
    assert line_message.startswith("Współpraca zakończyła się 31.10.2026")
    assert "linia zamówienia zbiorczego 108/2026" in line_message
    assert line_message.endswith(
        "przedłuż umowę aneksem albo przypisz zamówienie innej osobie."
    )


# ── Konflikt na karcie i w kubełku listy (baza) ──────────────────────────────


async def _seed_contract(
    *,
    contract_type: ContractType = ContractType.b2b,
    status: ContractStatus = ContractStatus.ending,
    end_date: date | None,
    terminated_at: date | None,
) -> tuple[int, int, str]:
    from app.models.candidate import Candidate
    from app.models.client import Client

    suffix = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"PoKoncuKlient-{suffix}")
        db.add(client)
        await db.flush()
        lastname = f"Pokoncu{suffix}"
        candidate = Candidate(
            name="Ola", lastname=lastname, email=f"po-koncu-{suffix}@example.com"
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=contract_type,
            status=status,
            start_date=business_today() - timedelta(days=200),
            end_date=end_date,
            terminated_at=terminated_at,
            termination_reason="project_ended" if terminated_at else None,
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id, lastname


async def _seed_order(
    client_id: int,
    contract_id: int,
    *,
    status: ClientOrderStatus,
    start: date,
    end: date | None,
) -> int:
    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title=f"PO-{uuid.uuid4().hex[:8]}",
            status=status,
            start_date=start,
            end_date=end,
            rate_client=Decimal("1200.000"),
            rate_unit=RateUnit.daily,
            currency="PLN",
        )
        db.add(order)
        await db.commit()
        return order.id


async def _bucket_ids(app_client, headers, lastname: str) -> set[int]:
    resp = await app_client.get(
        "/api/contracts",
        params={"bucket": "order_after_end", "q": lastname},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()["items"]}


async def test_draft_after_project_end_is_a_conflict(app_client, app_auth_headers):
    today = business_today()
    end = today + timedelta(days=10)
    client_id, contract_id, lastname = await _seed_contract(
        end_date=end, terminated_at=end
    )
    await _seed_order(
        client_id,
        contract_id,
        status=ClientOrderStatus.active,
        start=today - timedelta(days=60),
        end=end,
    )
    draft_id = await _seed_order(
        client_id,
        contract_id,
        status=ClientOrderStatus.draft,
        start=end + timedelta(days=1),
        end=end + timedelta(days=182),
    )

    detail = await app_client.get(
        f"/api/contracts/{contract_id}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    conflicts = detail.json()["order_after_end"]
    assert [c["order_id"] for c in conflicts] == [draft_id]
    assert conflicts[0]["status"] == "draft"
    assert conflicts[0]["held_by_termination"] is True
    assert conflicts[0]["start_date"] == (end + timedelta(days=1)).isoformat()

    assert contract_id in await _bucket_ids(app_client, app_auth_headers, lastname)
    listing = await app_client.get(
        "/api/contracts", params={"q": lastname}, headers=app_auth_headers
    )
    row = next(i for i in listing.json()["items"] if i["id"] == contract_id)
    assert row["order_after_end"]["order_id"] == draft_id
    assert row["order_after_end"]["count"] == 1


async def test_b2b_ending_with_order_within_the_period_has_no_conflict(
    app_client, app_auth_headers
):
    today = business_today()
    end = today + timedelta(days=10)
    client_id, contract_id, lastname = await _seed_contract(
        end_date=end, terminated_at=end
    )
    await _seed_order(
        client_id,
        contract_id,
        status=ClientOrderStatus.active,
        start=today - timedelta(days=60),
        end=end,
    )

    detail = await app_client.get(
        f"/api/contracts/{contract_id}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["order_after_end"] == []
    assert contract_id not in await _bucket_ids(app_client, app_auth_headers, lastname)


async def test_completed_order_after_the_end_is_history_not_a_conflict(
    app_client, app_auth_headers
):
    """#465/#470: rozliczone zamówienie dłuższe niż umowa to historia."""
    today = business_today()
    end = today - timedelta(days=90)
    client_id, contract_id, lastname = await _seed_contract(
        status=ContractStatus.ended, end_date=end, terminated_at=None
    )
    await _seed_order(
        client_id,
        contract_id,
        status=ClientOrderStatus.completed,
        start=end - timedelta(days=30),
        end=end + timedelta(days=60),
    )
    await _seed_order(
        client_id,
        contract_id,
        status=ClientOrderStatus.cancelled,
        start=end + timedelta(days=1),
        end=None,
    )

    detail = await app_client.get(
        f"/api/contracts/{contract_id}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["order_after_end"] == []
    assert contract_id not in await _bucket_ids(app_client, app_auth_headers, lastname)


async def test_open_ended_active_order_on_an_ended_contract_is_a_conflict(
    app_client, app_auth_headers
):
    """Koniec zamówienia pusty = „bez daty końca”, czyli po końcu projektu."""
    today = business_today()
    end = today - timedelta(days=20)
    client_id, contract_id, _ = await _seed_contract(
        contract_type=ContractType.uzlecenie,
        status=ContractStatus.ended,
        end_date=end,
        terminated_at=None,
    )
    order_id = await _seed_order(
        client_id,
        contract_id,
        status=ClientOrderStatus.active,
        start=end + timedelta(days=2),
        end=None,
    )

    detail = await app_client.get(
        f"/api/contracts/{contract_id}", headers=app_auth_headers
    )
    conflicts = detail.json()["order_after_end"]
    assert [c["order_id"] for c in conflicts] == [order_id]
    assert conflicts[0]["held_by_termination"] is False


# ── Blokada linii zamówienia zbiorczego (baza) ───────────────────────────────


async def _make_umowa_zlecenie(
    contract_id: int, *, status: ContractStatus, end_date: date
) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        contract.contract_type = ContractType.uzlecenie
        contract.status = status
        contract.end_date = end_date
        await db.commit()


def _expected_refusal(end: date) -> str:
    verb = "kończy się" if end >= business_today() else "zakończyła się"
    return (
        f"Umowa zlecenie {verb} {end.strftime('%d.%m.%Y')} — przedłuż ją "
        "aneksem albo załóż nowy kontrakt"
    )


async def _line_ids(group_id: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        return set(
            (
                await db.scalars(
                    select(ClientOrder.id).where(ClientOrder.order_group_id == group_id)
                )
            ).all()
        )


async def test_live_line_on_ended_umowa_zlecenie_is_refused(
    app_client, app_auth_headers, monkeypatch
):
    """#436: linia od 02.11 na umowie zlecenie zakończonej 31.10 = 422."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    ended_on = business_today() - timedelta(days=20)
    await _make_umowa_zlecenie(
        contracts[1], status=ContractStatus.ended, end_date=ended_on
    )
    before = await _line_ids(group["id"])

    added = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json=_line_payload(contracts[1]),
        headers=app_auth_headers,
    )
    assert added.status_code == 422, added.text
    assert added.json()["detail"] == _expected_refusal(ended_on)
    assert await _line_ids(group["id"]) == before

    created = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"PO-KONCU-{uuid.uuid4().hex[:4]}",
            "start_date": (business_today() - timedelta(days=10)).isoformat(),
            "lines": [_line_payload(contracts[1])],
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 422, created.text
    assert created.json()["detail"] == _expected_refusal(ended_on)

    swapped = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": business_today().isoformat(),
        },
        headers=app_auth_headers,
    )
    assert swapped.status_code == 422, swapped.text
    assert swapped.json()["detail"] == _expected_refusal(ended_on)

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contracts[1])
        assert contract.status == ContractStatus.ended
        assert contract.end_date == ended_on


async def test_line_starting_after_the_end_of_ending_umowa_zlecenie_is_refused(
    app_client, app_auth_headers, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    end = business_today() + timedelta(days=5)
    await _make_umowa_zlecenie(contracts[1], status=ContractStatus.ending, end_date=end)

    after_end = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json=_line_payload(
            contracts[1], start_date=(end + timedelta(days=1)).isoformat()
        ),
        headers=app_auth_headers,
    )
    assert after_end.status_code == 422, after_end.text
    assert after_end.json()["detail"] == _expected_refusal(end)

    within = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json=_line_payload(contracts[1], start_date=business_today().isoformat()),
        headers=app_auth_headers,
    )
    assert within.status_code == 201, within.text


async def test_historical_line_on_ended_umowa_zlecenie_stays_allowed(
    app_client, app_auth_headers, monkeypatch
):
    """Zapis historyczny opisuje przeszłość — blokada go nie dotyczy."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    ended_on = business_today() - timedelta(days=5)
    await _make_umowa_zlecenie(
        contracts[1], status=ContractStatus.ended, end_date=ended_on
    )

    added = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json=_line_payload(
            contracts[1], historical=True, end_date=ended_on.isoformat()
        ),
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["status"] == "completed"


async def test_draft_line_activation_on_ended_umowa_zlecenie_is_refused(
    app_client, app_auth_headers, monkeypatch
):
    """Materializacja szkicu linii (``update_line``) ma tę samą blokadę."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0]), _line_payload(contracts[1])],
    )
    line_id = next(
        line["id"] for line in group["lines"] if line["contract_id"] == contracts[1]
    )
    ended_on = business_today() - timedelta(days=3)
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        line.status = ClientOrderStatus.draft
        await db.commit()
    await _make_umowa_zlecenie(
        contracts[1], status=ContractStatus.ended, end_date=ended_on
    )

    updated = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{line_id}",
        json={"rate_revenue": 1300},
        headers=app_auth_headers,
    )
    assert updated.status_code == 422, updated.text
    assert updated.json()["detail"] == _expected_refusal(ended_on)
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        assert line.status == ClientOrderStatus.draft


# ── Dzwonek Delivery Leada: raz na zamówienie ────────────────────────────────


async def test_delivery_lead_bell_once_per_order(app_client):
    from app.models.notification import Notification, NotificationType
    from app.services.delivery_alert_recipients import (
        load_delivery_alert_recipient_scope,
    )
    from app.tasks.contract_alerts import _notify_orders_after_end

    today = business_today()
    end = today + timedelta(days=10)
    client_id, contract_id, _ = await _seed_contract(end_date=end, terminated_at=end)
    await _seed_order(
        client_id,
        contract_id,
        status=ClientOrderStatus.draft,
        start=end + timedelta(days=1),
        end=end + timedelta(days=182),
    )

    async def bells() -> list[Notification]:
        async with AsyncSessionLocal() as db:
            return list(
                (
                    await db.scalars(
                        select(Notification).where(
                            Notification.notification_type
                            == NotificationType.contract_ending,
                            Notification.link == f"/contracts/{contract_id}",
                            Notification.title.like(
                                "Klient zamówił okres po zakończeniu:%"
                            ),
                        )
                    )
                ).all()
            )

    for _ in range(2):
        async with AsyncSessionLocal() as db:
            scope = await load_delivery_alert_recipient_scope(db)
            await _notify_orders_after_end(db, scope)
            await db.commit()

    async with AsyncSessionLocal() as db:
        scope = await load_delivery_alert_recipient_scope(db)
        recipients = scope.bell_recipients(client_id, NotificationType.contract_ending)
    rows = await bells()
    assert recipients, "klient bez DL-a: zapasem są admini"
    assert len(rows) == len(recipients), "drugi przebieg nie dubluje dzwonka"
    assert rows[0].link == f"/contracts/{contract_id}"
    assert rows[0].title.startswith("Klient zamówił okres po zakończeniu: ")
    assert "anuluj szkic" in rows[0].message


async def test_daily_cycle_corrects_a_period_taken_from_a_held_draft(app_client):
    """Okres zapisany przed zmianą reguły poprawia dobowy przebieg (#209)."""
    from app.services.contract_order_after_end import open_order_after_end
    from app.tasks.contract_alerts import _resync_held_draft_periods

    today = business_today()
    end = today + timedelta(days=10)
    client_id, contract_id, _ = await _seed_contract(end_date=end, terminated_at=end)
    await _seed_order(
        client_id,
        contract_id,
        status=ClientOrderStatus.active,
        start=today - timedelta(days=60),
        end=end,
    )
    held_start, held_end = end + timedelta(days=1), end + timedelta(days=182)
    await _seed_order(
        client_id,
        contract_id,
        status=ClientOrderStatus.draft,
        start=held_start,
        end=held_end,
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.client_order_start_date = held_start
        contract.client_order_end_date = held_end
        await db.commit()

    async with AsyncSessionLocal() as db:
        conflicts = await open_order_after_end(db)
        assert contract_id in {c.contract_id for c in conflicts}
        assert await _resync_held_draft_periods(db, conflicts) >= 1
        await db.commit()

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert (contract.client_order_start_date, contract.client_order_end_date) == (
            today - timedelta(days=60),
            end,
        )
