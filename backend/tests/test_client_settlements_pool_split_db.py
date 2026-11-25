"""Dni zwykłe na kolejnych zamówieniach kontraktu, gdy pula się kończy, z bazą.

Próba VI–X 2026: osoba ma w miesiącu dwie linie zamówień (stara pula na
wyczerpaniu, nowe zamówienie od połowy miesiąca), rozliczenie brało jedną i stało
na „Ponad zamówienie”, a Finanse dzieliły fakturę: starsza linia do końca puli,
reszta na kolejną. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.dl_alert import ALERT_SETTLEMENT_OVER_ORDER, DlAlert
from app.services.client_settlements import service
from app.tasks.dl_alerts_scanner import rule_settlement_over_order
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_order_issues_db import (
    _alerts,
    _scan,
    _set_md,
    _world,
)
from tests.test_client_settlements_service_db import _cleanup

pytestmark = pytest.mark.asyncio
MANUAL = "MD wpisane bez pliku RCP"  # ``set_md`` w teście: uwaga wpisu ręcznego


@pytest.fixture
async def clients():
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


async def _second_line(w, *, md_total: str, start: date) -> int:
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=w.client_id,
            order_number=f"ZAM-NOWE-{w.client_id}",
            start_date=start,
            status="active",
            order_type="md",
            is_cost_based=False,
            is_md_budget_based=False,
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=w.client_id,
            contract_id=w.contract_id,
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
        await db.commit()
        return line.id


def _mid_month(month: str) -> date:
    year, mon = (int(x) for x in month.split("-"))
    return date(year, mon, 15)


async def _settlement(w):
    async with AsyncSessionLocal() as db:
        return await service._settlement(db, w.contract_id, w.month)


def _warns(s) -> list[str]:
    return [
        c["title"]
        for g in s.checks
        if "checks" in g
        for c in g["checks"]
        if c.get("state") in ("warn", "fail")
    ]


def _titles(s) -> list[str]:
    return [c["title"] for g in s.checks if "checks" in g for c in g["checks"]]


async def test_pula_starej_linii_potem_nowa_linia_bez_uwagi_i_bez_karty(
    clients,
) -> None:
    # Rozliczenie bierze najnowszą linię (pula 3 MD), która nie mieści 12 MD.
    w = await _world(md_total="10")
    clients.append(w.client_id)
    new = await _second_line(w, md_total="3", start=_mid_month(w.month))
    await _set_md(w, "12")

    s = await _settlement(w)
    parts = {o["order_id"]: o["md"] for o in service.split_orders(s)}
    assert parts == {w.line_id: "10.000", new: "2.000"}
    assert _warns(s) == [MANUAL]
    assert "Podział na kolejne zamówienia kontraktu" in _titles(s)
    assert not any(t.startswith("Ponad") for t in _titles(s))
    assert s.amount_revenue == Decimal("13200.00")  # 12 × 1100 na dwóch liniach
    assert await _scan(rule_settlement_over_order) == 0
    assert await _alerts(w, ALERT_SETTLEMENT_OVER_ORDER) == []


async def test_pule_obu_linii_za_male_zostaje_jedno_zamowienie_ponad_pule(
    clients,
) -> None:
    w = await _world(md_total="10")
    clients.append(w.client_id)
    await _second_line(w, md_total="2", start=_mid_month(w.month))
    await _set_md(w, "15")

    s = await _settlement(w)
    assert service.split_orders(s) == []
    assert any(t.startswith("Ponad") for t in _warns(s))
    assert "Podział na kolejne zamówienia kontraktu" not in _titles(s)


async def test_linia_od_nastepnego_miesiaca_nie_dzieli(clients) -> None:
    w = await _world(md_total="10")
    clients.append(w.client_id)
    year, mon = (int(x) for x in w.month.split("-"))
    after = date(year + (mon == 12), mon % 12 + 1, 1)
    await _second_line(w, md_total="40", start=after)
    await _set_md(w, "15")

    s = await _settlement(w)
    assert service.split_orders(s) == []
    assert any(t.startswith("Ponad") for t in _warns(s))


async def test_pula_wystarcza_zostaje_jedno_zamowienie(clients) -> None:
    w = await _world(md_total="30")
    clients.append(w.client_id)
    await _second_line(w, md_total="40", start=_mid_month(w.month))
    await _set_md(w, "15")

    s = await _settlement(w)
    assert service.split_orders(s) == []
    assert _warns(s) == [MANUAL]


def test_zakonczone_po_miesiacu_nie_jest_zakonczone_dla_miesiaca() -> None:
    first = date(2026, 9, 1)
    later = ClientOrder(status=ClientOrderStatus.completed, end_date=date(2026, 10, 30))
    before = ClientOrder(status=ClientOrderStatus.completed, end_date=date(2026, 8, 31))
    open_ended = ClientOrder(status=ClientOrderStatus.completed, end_date=None)
    active = ClientOrder(status=ClientOrderStatus.active, end_date=None)
    assert service._closed_for(later, first) is False
    assert service._closed_for(before, first) is True
    assert service._closed_for(open_ended, first) is True
    assert service._closed_for(active, first) is False
