"""Hosted-Postgres acceptance tests for atomic writes and one-off protection."""

from datetime import date
from decimal import Decimal
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.order_mail import OrderMailDocument
from app.models.activity import Activity
from app.services.order_mail_apply import apply_document
from app.services.order_mail_cleanup import client_inventory, fingerprint


def document(client_id, name, number, *, start="2033-09-01", end="2033-11-30"):
    return OrderMailDocument(
        internet_message_id=f"<{uuid.uuid4()}@example.test>",
        client_id=client_id,
        outcome="needs_review",
        gate_verdict="auto",
        extraction={
            "title": number,
            "start_date": start,
            "end_date": end,
            "source": "claude",
            "uncertain": False,
            "confidence": {"title": 1.0},
            "consultant_rows": [
                {
                    "consultant_name": name,
                    "rate_client": "140.00",
                    "rate_unit": "hour",
                    "uncertain": False,
                }
            ],
        },
        proposal={"rows": [{"action": "new_draft"}]},
    )


@pytest.mark.asyncio
async def test_first_mail_creates_once_then_updates_draft_and_notifies_once(
    monkeypatch,
):
    from app.services import order_mail_apply as writer

    notify = AsyncMock()
    monkeypatch.setattr(writer, "_notify_new_draft", notify)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Mail lifecycle {uuid.uuid4().hex}")
        db.add(client)
        await db.flush()
        name = "Jan Testowy" + uuid.uuid4().hex[:8]
        first = document(client.id, name, "Zlecenie nr 22")
        db.add(first)
        await db.flush()
        result = await apply_document(db, first, actor_user_id=None)
        assert result.ok, result.as_dict()
        order = await db.get(ClientOrder, result.rows[0].order_id)
        assert order.status == ClientOrderStatus.draft
        assert order.rate_client == Decimal("140") and order.rate_candidate is None
        second = document(client.id, name, "Zlecenie nr 23")
        db.add(second)
        await db.flush()
        updated = await apply_document(db, second, actor_user_id=None)
        assert updated.ok, updated.as_dict()
        assert updated.rows[0].order_id == order.id
        assert order.title == "Zlecenie nr 23"
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Contract)
                .where(Contract.client_id == client.id)
            )
            == 1
        )
        notify.assert_awaited_once()
        await db.rollback()


@pytest.mark.asyncio
async def test_completed_order_is_updated_and_history_retained():
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Returning mail {uuid.uuid4().hex}")
        candidate = Candidate(name="Jan", lastname="Powrotny" + uuid.uuid4().hex[:8])
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            client_id=client.id,
            candidate_id=candidate.id,
            status=ContractStatus.ended,
            start_date=date(2033, 1, 1),
            end_date=date(2033, 7, 31),
            rate_candidate=Decimal("100"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="Old order",
            status=ClientOrderStatus.completed,
            start_date=date(2033, 1, 1),
            end_date=date(2033, 7, 31),
            rate_client=Decimal("140"),
            rate_candidate=Decimal("100"),
            rate_unit=RateUnit.hourly,
            order_type="periodic",
        )
        db.add(order)
        await db.flush()
        doc = document(client.id, f"{candidate.name} {candidate.lastname}", "New order")
        db.add(doc)
        await db.flush()
        result = await apply_document(db, doc, actor_user_id=None)
        assert result.ok, result.as_dict()
        assert result.rows[0].order_id == order.id
        assert order.status == ClientOrderStatus.active and order.title == "New order"
        assert "32 dniach" in order.notes
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "client_order",
                Activity.entity_id == order.id,
                Activity.action == "order_mail_reactivate",
            )
        )
        assert activity.details["before"]["title"] == "Old order"
        assert activity.details["before"]["end_date"] == "2033-07-31"
        await db.rollback()


@pytest.mark.asyncio
async def test_error_in_second_person_rolls_back_first_person(monkeypatch):
    from app.services import order_mail_apply as writer

    monkeypatch.setattr(writer, "_notify_new_draft", AsyncMock())
    original = writer._new_person_contract
    calls = 0

    async def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("synthetic conflict in second row")
        return await original(*args)

    monkeypatch.setattr(writer, "_new_person_contract", fail_second)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Atomic mail {uuid.uuid4().hex}")
        db.add(client)
        await db.flush()
        cid = client.id
        doc = document(cid, "Jan Atomowy" + uuid.uuid4().hex[:8], "Atomic")
        doc.extraction = {
            **doc.extraction,
            "consultant_rows": [
                *doc.extraction["consultant_rows"],
                {
                    "consultant_name": "Anna Atomowa" + uuid.uuid4().hex[:8],
                    "rate_client": "140",
                    "rate_unit": "hour",
                },
            ],
        }
        db.add(doc)
        await db.flush()
        result = await apply_document(db, doc, actor_user_id=None)
        assert not result.ok and "synthetic conflict" in result.error
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Contract)
                .where(Contract.client_id == cid)
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ClientOrder)
                .where(ClientOrder.client_id == cid)
            )
            == 0
        )
        assert doc.applied_order_id is None
        await db.rollback()


@pytest.mark.asyncio
async def test_cleanup_uses_effective_inactive_tab_and_preserves_all_relations():
    async with AsyncSessionLocal() as db:
        no_history = Client(name=f"Inactive membership {uuid.uuid4().hex}")
        history = Client(
            name=f"Inactive history {uuid.uuid4().hex}",
            notes="Previous sales discussion",
        )
        active = Client(name=f"Active protected {uuid.uuid4().hex}")
        db.add_all([no_history, history, active])
        await db.flush()
        for client in (no_history, history, active):
            db.add(
                ClientPortfolioScope(
                    client_id=client.id,
                    category=PortfolioCategory.active,
                    category_override=PortfolioCategory.inactive
                    if client != active
                    else None,
                )
            )
        await db.flush()
        before = set(db.dirty), set(db.deleted)
        plan = await client_inventory(db)
        assert no_history.id in [r["id"] for r in plan["blocked"]]
        assert history.id in [r["id"] for r in plan["preserved"]]
        assert active.id not in [r["id"] for values in plan.values() for r in values]
        assert any(
            r["table"] == "client_portfolio_scopes"
            for c in plan["blocked"]
            if c["id"] == no_history.id
            for r in c["dependencies"]
        )
        assert (set(db.dirty), set(db.deleted)) == before
        assert fingerprint(plan) == fingerprint(await client_inventory(db))
        await db.rollback()


@pytest.mark.asyncio
async def test_signature_completes_mail_draft_with_agreement_cost(monkeypatch):
    from app.services import order_mail_apply as writer
    from app.services import order_mail_signature as signature

    monkeypatch.setattr(writer, "_notify_new_draft", AsyncMock())
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Signature mail {uuid.uuid4().hex}")
        db.add(client)
        await db.flush()
        doc = document(
            client.id, "Jan Podpisany" + uuid.uuid4().hex[:8], "Signed order"
        )
        db.add(doc)
        await db.flush()
        result = await apply_document(db, doc, actor_user_id=None)
        assert result.ok, result.as_dict()
        order = await db.get(ClientOrder, result.rows[0].order_id)
        contract = await db.get(Contract, order.contract_id)
        assert order.status == ClientOrderStatus.draft
        doc.applied_order_id = order.id
        doc.proposal = {"apply_result": result.as_dict()}
        contract.rate_candidate = Decimal("100")
        contract.rate_candidate_currency = "PLN"
        await db.flush()
        monkeypatch.setattr(
            signature, "can_activate_mail_order", AsyncMock(return_value=True)
        )
        assert await signature.complete_signed_mail_drafts(db, contract.id) == 1
        assert order.rate_candidate == Decimal("100")
        assert order.status == ClientOrderStatus.active
        assert await signature.complete_signed_mail_drafts(db, contract.id) == 0
        await db.rollback()
