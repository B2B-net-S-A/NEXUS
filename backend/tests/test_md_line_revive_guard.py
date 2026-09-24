"""Zaległe rozliczenie nie wskrzesza linii czekającej na decyzję offboardingu.

Odkąd import zużycia przyjmuje linie zakończone
(``client_order_lines.line_settles_in_month``), ``recompute_remaining`` biegnie
także na liniach domkniętych zakończeniem współpracy. ``sync_md_line_status``
umie wskrzesić linię ``completed`` z dodatnim budżetem — i dla linii, której
data zejścia wypada DZIŚ, sam warunek okresu by jej nie zatrzymał. Wskrzeszona
linia wróciłaby na aktywną obsadę i cofnęła decyzję o zakończeniu współpracy,
zanim Delivery Lead zdążył ją rozstrzygnąć.

Drugi test pilnuje migawki puli: to z niej liczy się przeniesienie MD na inną
osobę, więc MD zaraportowane PO zejściu muszą ją zmniejszyć — inaczej system
przeniósłby dni, które odchodzący już wypracował.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio


async def _seed_line(*, remaining: Decimal, with_case: bool):
    """Linia MD zakończona DZIŚ, opcjonalnie ze sprawą offboardingu."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup
    from app.models.client_order_offboarding import (
        OFFBOARDING_STATUS_PENDING,
        ClientOrderOffboardingCase,
    )
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"ReviveGuard-{suffix}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        cand = Candidate(
            name="Ewa",
            lastname=f"Guard-{suffix}",
            email=f"revive-{suffix}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=90),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        group = ClientOrderGroup(
            client_id=client.id,
            order_number=f"RG-{suffix}",
            start_date=business_today() - timedelta(days=90),
            order_type="md",
            md_budget_mode="per_person",
            status="active",
        )
        db.add(group)
        await db.commit()
        await db.refresh(group)

        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            order_group_id=group.id,
            title=f"Linia {group.order_number}",
            status=ClientOrderStatus.completed,
            start_date=business_today() - timedelta(days=90),
            # Zejście „na dziś": okres nadal obejmuje dzisiejszy dzień, więc
            # sam warunek daty w `sync_md_line_status` linii nie zatrzyma.
            end_date=business_today(),
            md_total=Decimal("100.000000"),
            md_remaining=remaining,
            md_manual_adjustment=Decimal("0"),
            md_input_mode="md",
            md_input_value=Decimal("100.000000"),
            md_rate_cost=Decimal("1000.00"),
            md_rate_revenue=Decimal("1200.00"),
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)

        case_id = None
        if with_case:
            case = ClientOrderOffboardingCase(
                contract_id=contract.id,
                order_id=order.id,
                order_group_id=group.id,
                client_id=client.id,
                effective_date=business_today(),
                status=OFFBOARDING_STATUS_PENDING,
                uses_shared_md_pool=False,
                remaining_md_snapshot=Decimal("100.000000"),
                order_number_snapshot=group.order_number,
            )
            db.add(case)
            await db.commit()
            await db.refresh(case)
            case_id = case.id

        return order.id, case_id


async def test_an_open_offboarding_case_keeps_the_line_ended():
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.services.client_order_lines import recompute_remaining

    order_id, _ = await _seed_line(remaining=Decimal("100.000000"), with_case=True)

    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        await recompute_remaining(db, order)
        await db.commit()
        await db.refresh(order)

    assert order.status == ClientOrderStatus.completed


async def test_without_a_case_the_budget_still_revives_the_line():
    """Kontrola negatywna: strażnik nie może unieruchomić wskrzeszania."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.services.client_order_lines import recompute_remaining

    order_id, _ = await _seed_line(remaining=Decimal("100.000000"), with_case=False)

    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        await recompute_remaining(db, order)
        await db.commit()
        await db.refresh(order)

    assert order.status == ClientOrderStatus.active


async def test_late_consumption_shrinks_the_open_case_snapshot():
    """Migawka puli podąża za realną pozostałością, póki sprawa jest otwarta."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_offboarding import ClientOrderOffboardingCase
    from app.services.client_order_lines import (
        recompute_remaining,
        upsert_consumption,
    )

    order_id, case_id = await _seed_line(
        remaining=Decimal("100.000000"), with_case=True
    )
    month = (business_today() - timedelta(days=40)).strftime("%Y-%m")

    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        await upsert_consumption(
            db, order=order, period_month=month, md_reported=Decimal("21")
        )
        await recompute_remaining(db, order)
        await db.commit()

    async with AsyncSessionLocal() as db:
        case = await db.get(ClientOrderOffboardingCase, case_id)
        order = await db.get(ClientOrder, order_id)

    assert order.md_remaining == Decimal("79.000000")
    assert Decimal(str(case.remaining_md_snapshot)) == Decimal("79.000000")
