"""Runda 8 audytu (26.09.2026) — zamówienia MD: zamiana, zastępstwo, przywracanie.

Każdy test odtwarza jedno znalezisko (R8-N5-1..8). Dane zakłada ``_seed``
z ``test_order_line_takeover`` (CeZ-podobne zamówienie per osoba: Konrad
odchodzi, Kamila przychodzi).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.scheduling import business_today
from tests.test_order_line_takeover import (
    _enable_multi,
    _schedule_takeover,
    _seed,
    _takeover_url,
    _third_person_contract,
)


def _line_url(seed: dict, line_id: int, suffix: str = "") -> str:
    return (
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/lines/{line_id}{suffix}"
    )


def _group_url(seed: dict, suffix: str) -> str:
    return f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}{suffix}"


async def _drop_consumptions(line_id: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import ClientOrderMdConsumption

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientOrderMdConsumption).where(
                ClientOrderMdConsumption.order_id == line_id
            )
        )
        await db.commit()


async def _event_payloads(order_id: int) -> list[dict]:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroupEvent

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(ClientOrderGroupEvent.payload).where(
                    ClientOrderGroupEvent.order_id == order_id
                )
            )
        ).all()
    return [row or {} for row in rows]


# ── N5-1: druga zamiana z datą w przyszłości ───────────────────────────────


async def test_second_future_swap_of_the_same_line_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    body = {
        "rate_cost": 680,
        "rate_revenue": 800,
        "swap_date": (business_today() + timedelta(days=5)).isoformat(),
        "md_transfer_method": "one_to_one",
    }
    first = await app_client.post(
        _line_url(seed, seed["line_id"], "/swap"),
        json={**body, "contract_id": seed["kamila_contract_id"]},
        headers=app_auth_headers,
    )
    assert first.status_code == 201, first.text

    olga = await _third_person_contract(seed)
    second = await app_client.post(
        _line_url(seed, seed["line_id"], "/swap"),
        json={**body, "contract_id": olga},
        headers=app_auth_headers,
    )
    assert second.status_code == 409, second.text
    assert "zamianę" in second.json()["detail"]

    async with AsyncSessionLocal() as db:
        successors = (
            await db.scalars(
                select(ClientOrder.id).where(
                    ClientOrder.predecessor_order_id == seed["line_id"],
                    ClientOrder.status != ClientOrderStatus.cancelled,
                )
            )
        ).all()
    assert successors == [first.json()["id"]]


# ── N5-2: anulowany następca a „Przywróć" ──────────────────────────────────


async def test_reopen_brings_back_a_person_whose_takeover_was_cancelled(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    planned = await _schedule_takeover(app_client, app_auth_headers, seed)

    closed = await app_client.post(
        _group_url(seed, "/close"),
        json={"closure_date": business_today().isoformat()},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    reopened = await app_client.post(
        _group_url(seed, "/reopen"), headers=app_auth_headers
    )
    assert reopened.status_code == 200, reopened.text

    async with AsyncSessionLocal() as db:
        konrad = await db.get(ClientOrder, seed["line_id"])
        takeover = await db.get(ClientOrder, planned["id"])
    assert takeover.status == ClientOrderStatus.cancelled
    assert konrad.status == ClientOrderStatus.active


# ── N5-3: „Przywróć anulowane" a zakończona / unieważniona umowa ───────────


async def _cancel_group_with_active_line(seed: dict) -> None:
    """Stan po „Anuluj zamówienie": grupa i linia anulowane, zdarzenie z listą."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import (
        GROUP_STATUS_ACTIVE,
        GROUP_STATUS_CANCELLED,
        ClientOrderGroup,
        ClientOrderGroupEvent,
    )
    from app.services.multi_consultant_orders import EVENT_ORDER_CANCELLED

    async with AsyncSessionLocal() as db:
        group = await db.get(ClientOrderGroup, seed["group_id"])
        group.status = GROUP_STATUS_CANCELLED
        group.status_before_cancel = GROUP_STATUS_ACTIVE
        line = await db.get(ClientOrder, seed["line_id"])
        line.status = ClientOrderStatus.cancelled
        db.add(
            ClientOrderGroupEvent(
                group_id=group.id,
                event_type=EVENT_ORDER_CANCELLED,
                description="Anulowano zamówienie (test)",
                payload={"lines": [{"id": line.id, "previous_status": "active"}]},
            )
        )
        await db.commit()


async def _end_contract(contract_id: int, status: str, end) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.status = ContractStatus(status)
        contract.end_date = end
        contract.terminated_at = end
        await db.commit()


async def test_restore_does_not_revive_a_line_of_an_ended_contract(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_offboarding import (
        OFFBOARDING_STATUS_PENDING,
        ClientOrderOffboardingCase,
    )

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    await _cancel_group_with_active_line(seed)
    yesterday = business_today() - timedelta(days=1)
    await _end_contract(seed["konrad_contract_id"], "ended", yesterday)

    resp = await app_client.post(_group_url(seed, "/restore"), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        konrad = await db.get(ClientOrder, seed["line_id"])
        cases = (
            await db.scalars(
                select(ClientOrderOffboardingCase).where(
                    ClientOrderOffboardingCase.order_id == seed["line_id"]
                )
            )
        ).all()
    assert konrad.status == ClientOrderStatus.completed
    assert konrad.end_date == yesterday
    # Pula osoby czeka na decyzję DL, jak po każdym zakończeniu współpracy.
    assert [c.status for c in cases] == [OFFBOARDING_STATUS_PENDING]
    assert Decimal(str(cases[0].remaining_md_snapshot)) == Decimal("187")


async def test_restore_keeps_a_line_of_a_void_contract_cancelled(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    await _cancel_group_with_active_line(seed)
    await _end_contract(seed["konrad_contract_id"], "void", None)

    resp = await app_client.post(_group_url(seed, "/restore"), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        konrad = await db.get(ClientOrder, seed["line_id"])
    assert konrad.status == ClientOrderStatus.cancelled


# ── N5-4: nocne wejście, któremu nie udało się przenieść puli ───────────────


async def _depart(seed: dict, *, end, adjustment: Decimal = Decimal("0")) -> None:
    """Odchodzący zakończył pracę: linia ``completed``, kontrakt ``ended``."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
        line.status = ClientOrderStatus.completed
        line.end_date = end
        line.md_manual_adjustment = adjustment
        contract = await db.get(Contract, seed["konrad_contract_id"])
        contract.status = ContractStatus.ended
        await db.commit()


async def test_failed_nightly_transfer_cancels_the_scheduled_takeover(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.services import order_line_takeover
    from app.services.order_line_takeover import (
        TAKEOVER_CANCEL_TRANSFER_FAILED,
        TakeoverError,
        activate_due_takeovers,
    )

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    planned = await _schedule_takeover(app_client, app_auth_headers, seed)
    entry = seed["departure"] + timedelta(days=1)
    await _depart(seed, end=seed["departure"])

    async def _refuse(*args, **kwargs):
        raise TakeoverError("Przeliczenie dało zero MD — sprawdź stawki.")

    monkeypatch.setattr(order_line_takeover, "apply_takeover_transfer", _refuse)

    async with AsyncSessionLocal() as db:
        assert await activate_due_takeovers(db, today=entry) == 0
        await db.commit()

    async with AsyncSessionLocal() as db:
        takeover = await db.get(ClientOrder, planned["id"])
    assert takeover.status == ClientOrderStatus.cancelled
    codes = [p.get("cancel_reason") for p in await _event_payloads(planned["id"])]
    assert TAKEOVER_CANCEL_TRANSFER_FAILED in codes


# ── N5-5: rozstrzygnięte „przywróć" a nowe zastępstwo ──────────────────────


async def test_restored_case_does_not_block_a_later_takeover(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.client_order_offboarding import (
        OFFBOARDING_RESOLUTION_RESTORE,
        OFFBOARDING_STATUS_RESOLVED,
        ClientOrderOffboardingCase,
    )

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrderOffboardingCase(
                contract_id=seed["konrad_contract_id"],
                order_id=seed["line_id"],
                order_group_id=seed["group_id"],
                client_id=seed["client_id"],
                effective_date=business_today() - timedelta(days=90),
                status=OFFBOARDING_STATUS_RESOLVED,
                resolution=OFFBOARDING_RESOLUTION_RESTORE,
                resolved_at=datetime.now(timezone.utc),
                version=2,
                uses_shared_md_pool=False,
                remaining_md_snapshot=Decimal("187"),
            )
        )
        await db.commit()

    planned = await _schedule_takeover(app_client, app_auth_headers, seed)
    assert planned["status"] == "draft"


# ── N5-6: pula wyczerpana przed dniem wejścia ──────────────────────────────


async def test_pool_used_up_before_entry_is_the_cancel_reason(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.services.order_line_takeover import (
        TAKEOVER_CANCEL_ENTRY_NOT_AFTER_DEPARTURE,
        TAKEOVER_CANCEL_POOL_USED_UP,
        activate_due_takeovers,
    )

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    planned = await _schedule_takeover(app_client, app_auth_headers, seed)
    entry = seed["departure"] + timedelta(days=1)
    # Linia domknięta budżetem niesie datę końca zamówienia (po dniu wejścia),
    # a pula jest wyzerowana: 190 + 170 − 173 − 187 = 0.
    await _depart(seed, end=entry + timedelta(days=60), adjustment=Decimal("-187"))

    async with AsyncSessionLocal() as db:
        assert await activate_due_takeovers(db, today=entry) == 0
        await db.commit()

    async with AsyncSessionLocal() as db:
        takeover = await db.get(ClientOrder, planned["id"])
    assert takeover.status == ClientOrderStatus.cancelled
    codes = [p.get("cancel_reason") for p in await _event_payloads(planned["id"])]
    assert TAKEOVER_CANCEL_POOL_USED_UP in codes
    assert TAKEOVER_CANCEL_ENTRY_NOT_AFTER_DEPARTURE not in codes


# ── N5-7: natychmiastowe przejęcie bez sprawy ──────────────────────────────


async def test_immediate_takeover_does_not_close_and_reopen_the_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroupEvent
    from app.services.multi_consultant_orders import (
        EVENT_ORDER_CLOSED,
        EVENT_ORDER_REOPENED,
    )

    seed = await _seed(with_case=False)
    _enable_multi(monkeypatch, seed["client_id"])
    resp = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": (seed["departure"] + timedelta(days=1)).isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(str(resp.json()["md_remaining"])) == Decimal("187")

    async with AsyncSessionLocal() as db:
        kinds = set(
            (
                await db.scalars(
                    select(ClientOrderGroupEvent.event_type).where(
                        ClientOrderGroupEvent.group_id == seed["group_id"]
                    )
                )
            ).all()
        )
    assert EVENT_ORDER_CLOSED not in kinds
    assert EVENT_ORDER_REOPENED not in kinds


# ── N5-8: usunięcie osoby z zaplanowanym zastępstwem ───────────────────────


async def test_deleting_a_line_with_a_scheduled_takeover_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    planned = await _schedule_takeover(app_client, app_auth_headers, seed)
    # Bez rozliczeń — inaczej 409 dałaby blokada rozliczeń, nie ta reguła.
    await _drop_consumptions(seed["line_id"])

    resp = await app_client.delete(
        _line_url(seed, seed["line_id"]), headers=app_auth_headers
    )
    assert resp.status_code == 409, resp.text
    assert "zaplanowane zastępstwo" in resp.json()["detail"]

    async with AsyncSessionLocal() as db:
        takeover = await db.get(ClientOrder, planned["id"])
    assert takeover.status == ClientOrderStatus.draft
    assert takeover.predecessor_order_id == seed["line_id"]
