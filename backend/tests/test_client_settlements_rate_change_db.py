"""Zmiana stawki kontraktora w trakcie miesiąca (próba IX–X 2026).

Kontrakt miał w harmonogramie zmianę stawki 17.09 (100 → 105 zł/h). NEXUS liczył
koszt jedną stawką z linii zamówienia i dawał „ok”, a zapłacono po dwóch stawkach.
Teraz rozliczenie ma uwagę z datą i stawkami. Kwoty i osoby fikcyjne."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.models.contract_candidate_rate import ContractCandidateRate
from app.services.client_settlements import service
from tests.test_client_settlements_service_db import (
    ACTOR,
    _cleanup,
    _previous_month,
    _world,
)

pytestmark = pytest.mark.asyncio


async def _rate(contract_id: int, day: date, rate: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ContractCandidateRate(
                contract_id=contract_id, effective_from=day, rate=Decimal(rate)
            )
        )
        await db.commit()


def _titles(s) -> list[str]:
    return [
        c["title"]
        for g in s.checks
        if isinstance(g, dict) and g.get("title") == "Stawka kontraktora"
        for c in g["checks"]
    ]


async def _set(contract_id: int, month: str):
    async with AsyncSessionLocal() as db:
        s = await service.set_md(
            db, contract_id, month, md_regular=Decimal("21"), md_extra=None, actor=ACTOR
        )
        await db.commit()
        return s


async def test_zmiana_stawki_w_trakcie_miesiaca_daje_uwage() -> None:
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    try:
        await _rate(contract_id, date(year - 1, 1, 1), "100")
        await _rate(contract_id, date(year, mon, 17), "105")
        s = await _set(contract_id, month)
        assert _titles(s) == [f"Zmiana stawki 17.{mon:02d}: 100 → 105"]
        assert s.status == "warnings"
    finally:
        await _cleanup(client_id)


async def test_zmiana_od_pierwszego_dnia_nie_daje_uwagi() -> None:
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    try:
        await _rate(contract_id, date(year - 1, 1, 1), "100")
        await _rate(contract_id, date(year, mon, 1), "105")
        s = await _set(contract_id, month)
        assert _titles(s) == []
    finally:
        await _cleanup(client_id)
