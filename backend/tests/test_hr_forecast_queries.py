"""Prognoza premii „w drodze”: tyle samo zapytań dla 1 i 10 kontraktów (17.10.2026).

Stawka klienta w EUR wymaga kursu NBP. Do poprawki kurs czytano osobno dla
każdego kontraktu (``placement_bonuses.contract_margin`` →
``fx_service.get_rate_to_pln``), więc ``GET /api/hr/payroll/me`` rósł z liczbą
kontraktów osoby. Teraz kursy na dni startu idą jednym zapytaniem na paczkę
(``fx_service.rates_to_pln_by_date``), jak rekrutacje i nazwy w
``placement_bonuses.load_context``. Kwota dalej liczy się z kursu.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, select

from app.core.database import AsyncSessionLocal, engine
from app.core.scheduling import business_today
from app.models.fx_rate import FxRate
from app.services.hr.my_settlement import bonus_forecast
from tests.test_hr_me_payroll import (  # noqa: F401 — fikstury
    _client,
    _contract,
    _job,
    _person,
    payroll_on,
)


async def _forecast(contracts: int, currency: str) -> tuple[list[dict], int]:
    today = business_today()
    async with AsyncSessionLocal() as db:
        if not await db.scalar(
            select(FxRate.id).where(
                FxRate.currency == "EUR", FxRate.effective_date <= today
            )
        ):
            db.add(
                FxRate(
                    effective_date=today - timedelta(days=7),
                    currency="EUR",
                    rate_to_pln=Decimal("4.25"),
                    source="NBP",
                )
            )
        me = await _person(db, "recruiter")
        for offset in range(contracts):
            client = await _client(db)
            job = await _job(db, client, recruiter=me, dl=None)
            contract = await _contract(
                db, client, start=today + timedelta(days=3 + offset), job=job
            )
            if currency != "PLN":
                # 35 EUR/h × 4,25 − 104 zł/h = dodatnia marża (kwoty zmyślone).
                contract.rate_client = Decimal("35")
                contract.rate_client_currency = currency
            await db.flush()
        await db.commit()

    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args, **_kwargs) -> None:  # noqa: ANN001
        statements.append(statement)

    async with AsyncSessionLocal() as db:
        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            items = await bonus_forecast(db, user_id=me.id, today=today)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)
    return items, len(statements)


@pytest.mark.asyncio
async def test_forecast_reads_fx_once_per_batch(payroll_on) -> None:  # noqa: F811
    one_items, one = await _forecast(1, "EUR")
    ten_items, ten = await _forecast(10, "EUR")
    assert (len(one_items), len(ten_items)) == (1, 10)
    assert ten == one, (one, ten)
    # Kurs jest — kwota liczy się (szacunek), bez powodu braku.
    for item in one_items + ten_items:
        assert item["amount"] is not None, item
        assert item["amount_missing_reason"] is None


@pytest.mark.asyncio
async def test_forecast_in_pln_needs_no_fx_and_same_query_count(
    payroll_on,  # noqa: F811
) -> None:
    _, eur = await _forecast(3, "EUR")
    pln_items, pln = await _forecast(3, "PLN")
    assert len(pln_items) == 3
    assert all(item["amount"] is not None for item in pln_items)
    # Paczka w złotych nie czyta kursów wcale.
    assert pln <= eur
