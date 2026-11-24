"""Rozliczenie ponad zamówienie i stawka linii, z bazą. Dane fikcyjne.

Alert do Delivery Leada klienta z linkiem do zamówienia, gdy rozliczenie
przekracza pulę; brak alertu, gdy pula wystarcza albo rozliczenie jest przyjęte;
przeliczenie po zmianie zamówienia zamyka kartę. Stawka linii inna niż kontrakt:
uwaga na karcie rozliczenia (Finanse, z kwotą) i karta DL bez kwot.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.contract import RateUnit
from app.models.dl_alert import (
    ALERT_SETTLEMENT_OVER_ORDER,
    ALERT_SETTLEMENT_RATE_MISMATCH,
    DL_ALERT_PRIORITY_HIGH,
    DL_ALERT_STATUS_NEW,
    DL_ALERT_STATUS_RESOLVED,
    DlAlert,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.services.client_settlements import line_rate, order_issues, service
from app.tasks.dl_alerts_scanner import (
    rule_settlement_over_order,
    rule_settlement_rate_mismatch,
)
from tests.client_invoicing import helpers as fx
from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_service_db import _cleanup, _previous_month

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)


async def _world(
    *, md_total: str, contract_rate: dict | None = None
) -> SimpleNamespace:
    client_id = await _client()
    contract_id = await _contract(
        client_id, await _candidate(), **(contract_rate or {})
    )
    start = business_today() - timedelta(days=90)
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=f"ZAM-{client_id}",
            start_date=start,
            status="active",
            order_type="md",
            is_cost_based=False,
            is_md_budget_based=False,
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            order_group_id=group.id,
            title="linia MD",
            status=ClientOrderStatus.active,
            start_date=start,
            md_total=Decimal(md_total),
            md_remaining=Decimal(md_total),
            md_input_mode="md",
            md_input_value=Decimal(md_total),
            md_rate_cost=Decimal("1000"),
            md_rate_revenue=Decimal("1100"),
        )
        db.add(line)
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id,
                effective_from="2020-01",
                rules={"order.no_md_holds_invoice": {"level": "warn", "params": {}}},
            )
        )
        dl = await fx.make_user(db, "delivery_lead")
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl.id, client_id=client_id, is_head=True
            )
        )
        await db.commit()
        return SimpleNamespace(
            client_id=client_id,
            contract_id=contract_id,
            line_id=line.id,
            dl_id=dl.id,
            month=_previous_month(),
        )


@pytest.fixture
async def module():
    previous = await _module(True)
    created: list[int] = []
    try:
        yield created
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                DlAlert.__table__.delete().where(DlAlert.client_id.in_(created or [0]))
            )
            await db.commit()
        for client_id in created:
            await _cleanup(client_id)
        await _restore(previous)


async def _set_md(w: SimpleNamespace, md: str) -> None:
    async with AsyncSessionLocal() as db:
        await service.set_md(
            db,
            w.contract_id,
            w.month,
            md_regular=Decimal(md),
            md_extra=None,
            actor=ACTOR,
        )
        await db.commit()


async def _alerts(w: SimpleNamespace, alert_type: str) -> list[DlAlert]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(DlAlert).where(
                    DlAlert.client_id == w.client_id, DlAlert.alert_type == alert_type
                )
            )
        )


async def _scan(rule) -> int:
    async with AsyncSessionLocal() as db:
        created = await rule(db)
        await db.commit()
        return created


async def test_ponad_pule_alert_do_dl_z_linkiem_do_zamowienia(module) -> None:
    w = await _world(md_total="10")
    module.append(w.client_id)
    await _set_md(w, "15")

    assert await _scan(rule_settlement_over_order) == 1
    [alert] = await _alerts(w, ALERT_SETTLEMENT_OVER_ORDER)
    assert alert.user_id == w.dl_id
    assert alert.order_id == w.line_id
    assert alert.link == f"/clients/{w.client_id}?tab=zamowienia&order={w.line_id}"
    assert alert.priority == DL_ALERT_PRIORITY_HIGH
    assert "5 MD ponad pulę zamówienia" in alert.message
    assert alert.payload["email"] is True
    # Drugi bieg nie dokłada karty.
    assert await _scan(rule_settlement_over_order) == 0


async def test_pula_wystarcza_brak_alertu(module) -> None:
    w = await _world(md_total="30")
    module.append(w.client_id)
    await _set_md(w, "15")

    assert await _scan(rule_settlement_over_order) == 0
    assert await _alerts(w, ALERT_SETTLEMENT_OVER_ORDER) == []


async def test_przyjete_rozliczenie_bez_alertu(module) -> None:
    w = await _world(md_total="10")
    module.append(w.client_id)
    await _set_md(w, "15")
    async with AsyncSessionLocal() as db:
        await service.accept(db, w.contract_id, w.month, actor=ACTOR, now=local_now())
        await db.commit()

    assert await _scan(rule_settlement_over_order) == 0


async def test_uzupelnione_zamowienie_przelicza_rozliczenie_i_zamyka_karte(
    module,
) -> None:
    w = await _world(md_total="10")
    module.append(w.client_id)
    await _set_md(w, "15")
    await _scan(rule_settlement_over_order)

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, w.line_id)
        line.md_total = Decimal("40")
        line.md_remaining = Decimal("40")
        assert await order_issues.refresh_client(db, client_id=w.client_id) == 1
        await db.commit()
    async with AsyncSessionLocal() as db:
        s = await service._settlement(db, w.contract_id, w.month)
        assert service.md_over(s) is None
        assert s.md_charged == Decimal("15.000")

    await _scan(rule_settlement_over_order)
    [alert] = await _alerts(w, ALERT_SETTLEMENT_OVER_ORDER)
    assert alert.status == DL_ALERT_STATUS_RESOLVED


async def test_zapas_skanera_przelicza_po_zmianie_zamowienia_bez_haka(module) -> None:
    w = await _world(md_total="10")
    module.append(w.client_id)
    await _set_md(w, "15")
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, w.line_id)
        line.md_total = Decimal("40")
        line.md_remaining = Decimal("40")
        await db.commit()

    # Ścieżka bez haka: skaner widzi zmianę linii po przeliczeniu.
    assert await _scan(rule_settlement_over_order) == 0
    async with AsyncSessionLocal() as db:
        s = await service._settlement(db, w.contract_id, w.month)
        assert service.md_over(s) is None


async def test_modul_wylaczony_nic_nie_przelicza(module) -> None:
    w = await _world(md_total="10")
    module.append(w.client_id)
    await _set_md(w, "15")
    await _module(False)
    async with AsyncSessionLocal() as db:
        assert await order_issues.refresh_client(db, client_id=w.client_id) == 0


async def test_stawka_linii_inna_niz_kontrakt_uwaga_i_karta_bez_kwot(module) -> None:
    w = await _world(
        md_total="30",
        contract_rate={"rate_client": 1200, "rate_unit": RateUnit.daily},
    )
    module.append(w.client_id)
    await _set_md(w, "15")
    async with AsyncSessionLocal() as db:
        s = await service._settlement(db, w.contract_id, w.month)
        [item] = line_rate.mismatches_of(service.meta_of(s))
        assert item["line"] == "1100.00" and item["contract"] == "1200.00"
        group = next(g for g in s.checks if g.get("title") == line_rate.GROUP_TITLE)
        assert "kontrakt 1 200 zł/MD" in group["checks"][0]["detail"]
        assert s.status == "warnings"

    assert await _scan(rule_settlement_rate_mismatch) == 1
    [alert] = await _alerts(w, ALERT_SETTLEMENT_RATE_MISMATCH)
    assert alert.status == DL_ALERT_STATUS_NEW
    assert alert.order_id == w.line_id
    assert "kontraktu" in alert.message
    assert "1100" not in alert.message and "1 200" not in alert.message
    assert alert.payload["email"] is True


async def test_stawka_linii_jak_kontrakt_bez_uwagi(module) -> None:
    w = await _world(
        md_total="30",
        contract_rate={"rate_client": 1100, "rate_unit": RateUnit.daily},
    )
    module.append(w.client_id)
    await _set_md(w, "15")
    async with AsyncSessionLocal() as db:
        s = await service._settlement(db, w.contract_id, w.month)
        assert line_rate.mismatches_of(service.meta_of(s)) == []
    assert await _scan(rule_settlement_rate_mismatch) == 0
