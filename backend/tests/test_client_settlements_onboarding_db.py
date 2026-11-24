"""MD wdrożeniowe w miesiącu po starcie (próba rozliczeń IX–X 2026, BNP).

Finanse dają 2 MD za 0 zł na fakturze za miesiąc startu (pozycja ``_onbording``),
a od kolejnego miesiąca fakturują pełne MD. NEXUS dawał je drugi raz w miesiącu
po starcie i liczył kwotę do faktury o 2 MD za niską (6 przypadków BNP):

* miesiąc startu był rozliczony bez reguły, bo reguły klienta działają od
  późniejszego miesiąca (na produkcji BNP ma regułę od 2026-11), więc pulę
  wykorzystały Finanse poza NEXUS-em;
* miesiąc startu był policzony, ale jeszcze nie przyjęty, a pula liczyła tylko
  przyjęte rozliczenia.

Kwoty i osoby fikcyjne."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client_settlement import ClientSettlement, ClientSettlementRuleSet
from app.models.contract import Contract
from app.services.client_settlements import service
from tests.test_client_settlements_service_db import (
    ACTOR,
    _cleanup,
    _previous_month,
    _world,
)

pytestmark = pytest.mark.asyncio

RULES = {
    "order.no_md_holds_invoice": {"level": "block", "params": {}},
    "order.onboarding_md": {"level": "warn", "params": {"md": "2"}},
}


def _month_before(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


async def _setup(rules_from: str, start: date) -> tuple[int, int]:
    """Klient z regułą MD wdrożeniowych od ``rules_from``, kontrakt od ``start``."""

    client_id, contract_id, _line = await _world()
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id, effective_from=rules_from, rules=RULES
            )
        )
        contract = await db.get(Contract, contract_id)
        contract.start_date = start
        await db.commit()
    return client_id, contract_id


async def _set(contract_id: int, month: str, md: str) -> ClientSettlement:
    async with AsyncSessionLocal() as db:
        s = await service.set_md(
            db, contract_id, month, md_regular=Decimal(md), md_extra=None, actor=ACTOR
        )
        await db.commit()
        return s


async def test_miesiac_startu_bez_reguly_nie_przenosi_puli() -> None:
    month = _previous_month()
    start_month = _month_before(month)
    year, mon = (int(x) for x in start_month.split("-"))
    client_id, contract_id = await _setup(month, date(year, mon, 17))
    try:
        s = await _set(contract_id, month, "20")
        assert s.md_onboarding == Decimal("0")
        assert s.md_charged == Decimal("20.000")
        assert s.amount_revenue == Decimal("22000.00")

        # Miesiąc startu policzony w NEXUS-ie bez reguły też niczego nie przenosi.
        before = await _set(contract_id, start_month, "9")
        assert before.md_onboarding == Decimal("0")
        s = await _set(contract_id, month, "20")
        assert s.md_onboarding == Decimal("0")
        assert s.amount_revenue == Decimal("22000.00")
    finally:
        await _cleanup(client_id)


async def test_nieprzyjety_miesiac_startu_zuzywa_pule() -> None:
    month = _previous_month()
    start_month = _month_before(month)
    year, mon = (int(x) for x in start_month.split("-"))
    client_id, contract_id = await _setup(start_month, date(year, mon, 1))
    try:
        first = await _set(contract_id, start_month, "22")
        assert first.status != "accepted"
        assert first.md_onboarding == Decimal("2")
        assert first.amount_revenue == Decimal("22000.00")  # 20 MD × 1100 zł

        s = await _set(contract_id, month, "22")
        assert s.md_onboarding == Decimal("0")
        assert s.md_charged == Decimal("22.000")
        assert s.amount_revenue == Decimal("24200.00")
    finally:
        await _cleanup(client_id)


async def test_reszta_puli_przechodzi_z_miesiaca_startu_z_regula() -> None:
    month = _previous_month()
    start_month = _month_before(month)
    year, mon = (int(x) for x in start_month.split("-"))
    client_id, contract_id = await _setup(start_month, date(year, mon, 28))
    try:
        first = await _set(contract_id, start_month, "1")
        assert first.md_onboarding == Decimal("1")
        s = await _set(contract_id, month, "20")
        assert s.md_onboarding == Decimal("1")
        assert s.md_charged == Decimal("19.000")
        assert s.amount_revenue == Decimal("20900.00")
    finally:
        await _cleanup(client_id)
