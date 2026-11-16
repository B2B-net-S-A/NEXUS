"""Aneks stawki klienta zmienia zamówienie od swojego dnia (ticket Finansów 16.11.2026).

Zgłoszenie: aneks w kontrakcie podniósł stawkę przychodową od 01.11.2026, a
linia zamówienia MD została przy starej stawce, więc „Do faktury” za
listopad liczyłoby się po starej. Ręczna zmiana linii przeliczyłaby też
miesiące sprzed aneksu. Dane fikcyjne (``tests/client_invoicing/helpers.py``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.api.contracts import (
    apply_contract_amendment,
    preview_annex_client_rate_impact,
)
from app.core.database import AsyncSessionLocal
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroupEvent
from app.models.client_order_revenue_step import ClientOrderRevenueStep
from app.models.contract import Contract, RateUnit
from app.models.contract_amendment import ContractAmendmentType
from app.models.md_consumption import ClientOrderMdConsumption
from app.schemas.contract_amendment import ContractAmendmentCreate
from app.services.client_invoicing.billing import billing_rows
from app.services.client_settlements.service import _order_for
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio

ANNEX_DAY = date(2026, 11, 1)


async def _seed():
    """Linia MD 1200 zł/MD (kontrakt 150 zł/h) ze zużyciem w październiku i listopadzie."""

    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Klient Aneksowy", None)
        admin = await fx.make_user(db, "admin")
        group_id, (line_id,) = await fx.md_group(
            db, client_id, "AN-2026-1", people=[("Ola", "Aneksowa", "1200", "20")]
        )
        line = await db.get(ClientOrder, line_id)
        line.rate_unit = RateUnit.daily
        line.rate_client = Decimal("1200")
        contract = await db.get(Contract, line.contract_id)
        contract.rate_unit = RateUnit.hourly
        contract.rate_client = Decimal("150")
        db.add(
            ClientOrderMdConsumption(
                order_id=line_id,
                period_month="2026-11",
                md_reported=Decimal("10"),
                source="import",
            )
        )
        await db.commit()
        return client_id, group_id, line_id, contract.id, admin


async def _annex(contract_id: int, admin, rate: str, day: date = ANNEX_DAY) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.merge(admin)
        await apply_contract_amendment(
            contract_id=contract_id,
            data=ContractAmendmentCreate(
                amendment_type=ContractAmendmentType.rate_change,
                effective_date=day,
                new_rate_client=Decimal(rate),
                reason="Aneks stawki klienta",
            ),
            current_user=user,
            db=db,
        )
        await db.commit()


async def _net(client_id: int, month: int) -> Decimal:
    async with AsyncSessionLocal() as db:
        (row,) = await billing_rows(db, year=2026, month=month, client_ids=[client_id])
    return row.expected_net


async def test_annex_changes_the_order_from_its_day_and_keeps_earlier_months():
    client_id, group_id, line_id, contract_id, admin = await _seed()
    assert await _net(client_id, 10) == Decimal("24000.00")

    # 162,5 zł/h × 8 = 1300 zł/MD od 01.11.
    await _annex(contract_id, admin, "162.5")

    assert await _net(client_id, 10) == Decimal("24000.00")  # 20 × 1200
    assert await _net(client_id, 11) == Decimal("13000.00")  # 10 × 1300
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        # Kolumna zostaje stawką ze startu — nic, co nie zna kroków, nie liczy
        # października po nowej stawce.
        assert line.md_rate_revenue == Decimal("1200.000")
        (step,) = (
            await db.scalars(
                select(ClientOrderRevenueStep).where(
                    ClientOrderRevenueStep.order_id == line_id
                )
            )
        ).all()
        assert (step.effective_from, step.md_rate_revenue) == (
            ANNEX_DAY,
            Decimal("1300.000"),
        )
        assert step.contract_amendment_id is not None
        events = (
            await db.scalars(
                select(ClientOrderGroupEvent).where(
                    ClientOrderGroupEvent.group_id == group_id,
                    ClientOrderGroupEvent.order_id == line_id,
                )
            )
        ).all()
        history = [
            e for e in events if (e.payload or {}).get("kind") == "revenue_rate_step"
        ]
        assert len(history) == 1
        assert "1200.00 → 1300.00 zł/MD" in history[0].description
        # Rozliczenia (KEŚU, faktura klienta) czytają stawkę z miesiąca.
        november = await _order_for(db, contract_id, "2026-11")
        october = await _order_for(db, contract_id, "2026-10")
        assert november.md_rate_revenue == Decimal("1300.000")
        assert october.md_rate_revenue == Decimal("1200.000")


async def test_hourly_rate_copied_from_screen_gives_md_in_grosze():
    client_id, _group_id, line_id, contract_id, admin = await _seed()
    # Stawka przepisana z ekranu z trzema miejscami: 162,501 × 8 = 1300,008.
    await _annex(contract_id, admin, "162.501")
    async with AsyncSessionLocal() as db:
        step = await db.scalar(
            select(ClientOrderRevenueStep).where(
                ClientOrderRevenueStep.order_id == line_id
            )
        )
    assert step.md_rate_revenue == Decimal("1300.010")


async def test_second_annex_on_the_same_day_corrects_the_step():
    client_id, _group_id, line_id, contract_id, admin = await _seed()
    await _annex(contract_id, admin, "162.5")
    await _annex(contract_id, admin, "175")
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(ClientOrderRevenueStep).where(
                    ClientOrderRevenueStep.order_id == line_id
                )
            )
        ).all()
    assert [r.md_rate_revenue for r in rows] == [Decimal("1400.000")]
    assert await _net(client_id, 11) == Decimal("14000.00")


async def test_order_that_starts_on_annex_day_or_ended_before_is_not_touched():
    client_id, _group_id, line_id, contract_id, admin = await _seed()
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        line.end_date = date(2026, 10, 31)
        line.status = ClientOrderStatus.completed
        later = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title="Zamówienie od listopada",
            status=ClientOrderStatus.active,
            start_date=ANNEX_DAY,
            end_date=date(2026, 12, 31),
            rate_unit=RateUnit.daily,
            rate_client=Decimal("1250"),
        )
        db.add(later)
        await db.commit()
    await _annex(contract_id, admin, "162.5")
    async with AsyncSessionLocal() as db:
        count = (
            await db.scalars(
                select(ClientOrderRevenueStep.id)
                .join(ClientOrder, ClientOrder.id == ClientOrderRevenueStep.order_id)
                .where(ClientOrder.contract_id == contract_id)
            )
        ).all()
    assert count == []


async def test_preview_lists_the_change_without_writing():
    _client_id, _group_id, line_id, contract_id, admin = await _seed()
    async with AsyncSessionLocal() as db:
        user = await db.merge(admin)
        impact = await preview_annex_client_rate_impact(
            contract_id,
            user,
            effective_date=date(2026, 11, 15),
            new_rate_client=Decimal("162.5"),
            db=db,
        )
        await db.rollback()
    (item,) = impact
    assert item.order_id == line_id
    assert item.order_number == "AN-2026-1"
    assert (item.old_md_rate, item.new_md_rate) == (
        Decimal("1200.000"),
        Decimal("1300.00"),
    )
    # Aneks od połowy miesiąca liczy się od rozliczenia za grudzień.
    assert item.first_month == date(2026, 12, 1)
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(ClientOrderRevenueStep).where(
                    ClientOrderRevenueStep.order_id == line_id
                )
            )
        ) is None
