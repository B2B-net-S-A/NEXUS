"""Przepięcie kontraktu na innego klienta (PR2) — testy na żywej bazie.

Pokrywa:

- podgląd → apply z odciskiem przenosi kontrakt, jego zamówienia i
  wygenerowane umowy B2B, zamyka otwarte alerty DL starego klienta;
- 409 z LISTĄ blokerów (linia zamówienia MD, umowa ramowa, PM innego
  klienta) i zablokowana próba w Historii zdarzeń bez nazwisk;
- 409 przy rozjeździe odcisku (świat zmienił się od podglądu);
- 422 dla tego samego klienta, 403 dla nie-admina;
- wpis Historii zdarzeń po wykonaniu bez nazwiska konsultanta.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.critical_event import CriticalEvent
from app.models.dl_alert import DlAlert
from app.models.user import UserRole
from tests.test_client_deletion import _client, _contract, _user

pytestmark = pytest.mark.asyncio


async def _preview(api: AsyncClient, headers, contract_id: int, client_id: int):
    return await api.get(
        f"/api/contracts/{contract_id}/client-reassign-preview",
        params={"client_id": client_id},
        headers=headers,
    )


async def _apply(api: AsyncClient, headers, contract_id: int, client_id: int, fp: str):
    return await api.post(
        f"/api/contracts/{contract_id}/client-reassign",
        json={"client_id": client_id, "fingerprint": fp},
        headers=headers,
    )


async def _events(contract_id: int) -> list[CriticalEvent]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(CriticalEvent)
            .where(
                CriticalEvent.entity_type == "contract",
                CriticalEvent.entity_id == contract_id,
                CriticalEvent.event_type == "contract.client_reassign",
            )
            .order_by(CriticalEvent.id)
        )
        return list(rows)


async def test_reassign_moves_contract_orders_documents_and_closes_alerts(
    app_client: AsyncClient,
):
    old_client = await _client("reassign-old")
    new_client = await _client("reassign-new")
    contract_id, order_id = await _contract(
        old_client, status=ContractStatus.active, order_status=ClientOrderStatus.active
    )
    admin_id, headers = await _user(app_client)
    async with AsyncSessionLocal() as db:
        doc = B2BGeneratedContract(
            year=2026,
            seq=900000 + int(uuid.uuid4().int % 90000),
            contract_number=f"T-{uuid.uuid4().hex[:6]}",
            partner_name="Partner Testowy",
            client_id=old_client,
            client_name="Stara Nazwa Klienta",
            contract_id=contract_id,
            render_payload={},
        )
        db.add(doc)
        alert = DlAlert(
            alert_type="periodic_order_ending",
            user_id=admin_id,
            client_id=old_client,
            order_id=order_id,
            title="Zamówienie się kończy",
            message="Zamówienie się kończy",
            dedupe_key=f"test-reassign-{uuid.uuid4().hex}",
            event_key=f"periodic_order_ending:order:{order_id}:{admin_id}",
        )
        db.add(alert)
        await db.commit()
        doc_id, alert_id = doc.id, alert.id

    preview = await _preview(app_client, headers, contract_id, new_client)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["can_apply"] is True
    assert [o["id"] for o in plan["orders"]] == [order_id]
    assert [d["id"] for d in plan["b2b_documents"]] == [doc_id]
    assert [a["id"] for a in plan["alerts"]] == [alert_id]

    applied = await _apply(
        app_client, headers, contract_id, new_client, plan["fingerprint"]
    )
    assert applied.status_code == 200, applied.text

    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).client_id == new_client
        assert (await db.get(ClientOrder, order_id)).client_id == new_client
        doc = await db.get(B2BGeneratedContract, doc_id)
        assert doc.client_id == new_client
        assert doc.client_name == "Stara Nazwa Klienta"  # treść dokumentu nietknięta
        alert = await db.get(DlAlert, alert_id)
        assert alert.status == "resolved" and alert.handled_by_user_id is None

    events = await _events(contract_id)
    assert [e.outcome for e in events] == ["executed"]
    assert events[0].entity_label == f"Kontrakt #{contract_id}"
    assert "Testowy" not in (events[0].reason or "") + str(events[0].details)


async def test_blockers_return_409_with_the_full_list(app_client: AsyncClient):
    old_client = await _client("reassign-blk-old")
    new_client = await _client("reassign-blk-new")
    contract_id, order_id = await _contract(
        old_client, status=ContractStatus.active, order_status=ClientOrderStatus.active
    )
    async with AsyncSessionLocal() as db:
        framework = ClientFrameworkContract(
            client_id=old_client,
            name=f"RAM-{uuid.uuid4().hex[:6]}",
            status=FrameworkContractStatus.active,
        )
        db.add(framework)
        group = ClientOrderGroup(
            client_id=old_client,
            order_number=f"MD-{uuid.uuid4().hex[:6]}",
            start_date=business_today() - timedelta(days=30),
            status="active",
            is_md_budget_based=False,
        )
        db.add(group)
        contact = Contact(client_id=old_client, name="Piotr Kontaktowy")
        db.add(contact)
        await db.flush()
        order = await db.get(ClientOrder, order_id)
        order.framework_contract_id = framework.id
        db.add(
            ClientOrder(
                client_id=old_client,
                contract_id=contract_id,
                order_group_id=group.id,
                title=f"Zamówienie {group.order_number}",
                status=ClientOrderStatus.active,
                start_date=business_today() - timedelta(days=30),
                rate_unit=RateUnit.daily,
            )
        )
        contract = await db.get(Contract, contract_id)
        contract.client_pm_contact_id = contact.id
        await db.commit()
    _, headers = await _user(app_client)

    preview = await _preview(app_client, headers, contract_id, new_client)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["can_apply"] is False
    codes = {b["code"] for b in plan["blockers"]}
    assert codes == {
        "order_framework_contract",
        "order_group_line",
        "pm_contact_other_client",
    }

    applied = await _apply(
        app_client, headers, contract_id, new_client, plan["fingerprint"]
    )
    assert applied.status_code == 409
    detail = applied.json()["detail"]
    assert detail["code"] == "contract_client_reassign_blocked"
    assert {b["code"] for b in detail["blockers"]} == codes

    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).client_id == old_client
    events = await _events(contract_id)
    assert [e.outcome for e in events] == ["blocked"]
    # Komunikaty cytują tytuły zamówień — w Historii zostają same kategorie.
    assert "Zamówienie MD-" not in (events[0].reason or "")


async def test_stale_fingerprint_is_409_and_changes_nothing(app_client: AsyncClient):
    old_client = await _client("reassign-fp-old")
    new_client = await _client("reassign-fp-new")
    contract_id, _ = await _contract(
        old_client, status=ContractStatus.active, order_status=ClientOrderStatus.active
    )
    _, headers = await _user(app_client)
    plan = (await _preview(app_client, headers, contract_id, new_client)).json()

    # Po podglądzie dochodzi drugie zamówienie — odcisk się zmienia.
    await _contract_extra_order(contract_id, old_client)

    applied = await _apply(
        app_client, headers, contract_id, new_client, plan["fingerprint"]
    )
    assert applied.status_code == 409
    assert applied.json()["detail"]["code"] == "fingerprint_mismatch"
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).client_id == old_client


async def _contract_extra_order(contract_id: int, client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                title=f"ZAM-extra-{uuid.uuid4().hex[:6]}",
                status=ClientOrderStatus.draft,
                order_type="periodic",
                rate_unit=RateUnit.hourly,
                start_date=business_today(),
            )
        )
        await db.commit()


async def test_same_client_is_422(app_client: AsyncClient):
    client_id = await _client("reassign-same")
    contract_id, _ = await _contract(client_id, status=ContractStatus.active)
    _, headers = await _user(app_client)
    resp = await _preview(app_client, headers, contract_id, client_id)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "same_client"


async def test_non_admin_is_403(app_client: AsyncClient):
    old_client = await _client("reassign-403-old")
    new_client = await _client("reassign-403-new")
    contract_id, _ = await _contract(old_client, status=ContractStatus.active)
    _, headers = await _user(app_client, role=UserRole.delivery_lead)
    resp = await _preview(app_client, headers, contract_id, new_client)
    assert resp.status_code == 403
    resp = await _apply(app_client, headers, contract_id, new_client, "0" * 64)
    assert resp.status_code == 403


async def test_live_contract_of_the_same_person_at_target_blocks(
    app_client: AsyncClient,
):
    """Audyt 25.09.2026: przepięcie nie sprawdzało, czy osoba ma już żywy
    kontrakt u klienta docelowego — dawało dwa kontrakty jednej osoby u jednego
    klienta (podwójne MRR), czego zwykłe zakładanie kontraktu nie pozwala."""
    old_client = await _client("reassign-dup-old")
    new_client = await _client("reassign-dup-new")
    contract_id, _ = await _contract(old_client, status=ContractStatus.active)
    async with AsyncSessionLocal() as db:
        moved = await db.get(Contract, contract_id)
        existing = Contract(
            candidate_id=moved.candidate_id,
            client_id=new_client,
            status=ContractStatus.draft,
            start_date=business_today(),
            rate_unit=RateUnit.hourly,
        )
        db.add(existing)
        await db.commit()
        existing_id = existing.id
    _, headers = await _user(app_client)

    preview = await _preview(app_client, headers, contract_id, new_client)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["can_apply"] is False
    [blocker] = plan["blockers"]
    assert blocker["code"] == "duplicate_contract_at_target"
    assert f"Kontrakt #{existing_id}" in blocker["message"]

    applied = await _apply(
        app_client, headers, contract_id, new_client, plan["fingerprint"]
    )
    assert applied.status_code == 409
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).client_id == old_client


def test_live_statuses_mirror_the_duplicate_guard():
    from app.api.contracts import _DUPLICATE_GUARD_STATUSES
    from app.services.contract_client_reassign import LIVE_CONTRACT_STATUSES

    assert set(LIVE_CONTRACT_STATUSES) == set(_DUPLICATE_GUARD_STATUSES)
