"""Zmiana stawki kontraktora w trakcie miesiąca (próba IX–X 2026).

Kontrakt miał w harmonogramie zmianę stawki 17.09 (100 → 105 zł/h). NEXUS liczył
koszt jedną stawką z linii zamówienia i dawał „ok”, a zapłacono po dwóch stawkach.
Z godzinami z RCP dzień po dniu koszt dzieli się na dni przed i po zmianie; bez
nich rozliczenie ma uwagę z datą i stawkami. Kwoty i osoby fikcyjne."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.client_settlement import ClientSettlement
from app.models.contract import Contract, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.services.client_settlements import rcp_checks, rules_catalog, service
from app.services.client_settlements.engine import OrderState
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


# ── podział kosztu według godzin z RCP ──────────────────────────────────────


async def _hourly(contract_id: int, start: date) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == contract_id)
            .values(rate_unit=RateUnit.hourly, start_date=start, rate_candidate=125)
        )
        await db.commit()


def _hours(month: str) -> tuple[Decimal, ...]:
    """8 h w każdy dzień roboczy (pon–pt) miesiąca, 31 kolumn jak w RCP BNP."""

    year, mon = (int(x) for x in month.split("-"))
    days = calendar.monthrange(year, mon)[1]
    return tuple(
        Decimal("8")
        if day <= days and date(year, mon, day).weekday() < 5
        else Decimal("0")
        for day in range(1, 32)
    )


async def _checks(contract_id: int, client_id: int, month: str, line_rate: str):
    """``_rate_change_checks`` z RCP z godzinami dzień po dniu i linią zamówienia."""

    hours = _hours(month)
    md = sum(hours, Decimal("0")) / 8
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        s = ClientSettlement(
            contract_id=contract_id,
            client_id=client_id,
            period_month=month,
            md_regular=md,
            md_extra=None,
        )
        proof = rcp_checks.ProofResult(md_regular=md, md_extra=None, day_hours=hours)
        order = OrderState(
            order_id=1,
            number=None,
            md_total=None,
            md_available=None,
            rate_cost=Decimal(line_rate),
            rate_revenue=Decimal("1200"),
        )
        rules = rules_catalog.effective({})
        proof, parts = await service._rate_change_checks(
            db, s, proof, rules, contract, order, split=False
        )
    checks = [
        c
        for g in proof.groups
        if g["title"] == "Stawka kontraktora"
        for c in g["checks"]
    ]
    return checks, parts, hours, md


async def test_zmiana_w_srodku_miesiaca_z_godzinami_z_rcp_dzieli_koszt() -> None:
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    try:
        await _hourly(contract_id, date(year - 1, 1, 1))
        await _rate(contract_id, date(year - 1, 1, 1), "125")
        await _rate(contract_id, date(year, mon, 17), "130")
        checks, parts, hours, md = await _checks(contract_id, client_id, month, "1000")
        before = sum(hours[:16], Decimal("0")) / 8
        assert [(p.md, p.rate) for p in parts] == [
            (before, Decimal("1000.00")),
            (md - before, Decimal("1040.00")),
        ]
        assert [c["state"] for c in checks] == ["ok"]
        assert checks[0]["title"].startswith("Koszt po stawkach z harmonogramu")
    finally:
        await _cleanup(client_id)


async def test_linia_ze_stawka_spoza_harmonogramu_zostawia_uwage() -> None:
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    try:
        await _hourly(contract_id, date(year - 1, 1, 1))
        await _rate(contract_id, date(year - 1, 1, 1), "125")
        await _rate(contract_id, date(year, mon, 17), "130")
        checks, parts, _hours_, _md = await _checks(
            contract_id, client_id, month, "950"
        )
        assert parts == ()
        assert [c["state"] for c in checks] == ["warn"]
        assert "Linia zamówienia ma 950 zł/MD" in checks[0]["detail"]
    finally:
        await _cleanup(client_id)


async def test_krok_z_ta_sama_stawka_nie_daje_uwagi() -> None:
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    try:
        await _rate(contract_id, date(year - 1, 1, 1), "100")
        await _rate(contract_id, date(year, mon, 29), "100")
        s = await _set(contract_id, month)
        assert _titles(s) == []
    finally:
        await _cleanup(client_id)


async def test_pierwszy_krok_w_dniu_startu_kontraktu_nie_daje_uwagi() -> None:
    """Kontrakt zaczęty w środku miesiąca ma jedyny krok z dnia startu: to nie
    zmiana stawki (dawniej „Zmiana stawki 29.10: ? → 50”)."""

    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    try:
        await _hourly(contract_id, date(year, mon, 20))
        # 125 zł/h = 1000 zł/MD, jak linia z ``_world``.
        await _rate(contract_id, date(year, mon, 20), "125")
        s = await _set(contract_id, month)
        assert _titles(s) == []
    finally:
        await _cleanup(client_id)


# ── linia zamówienia zbiorczego a stawka kontraktu na cały miesiąc ──────────


async def test_linia_zbiorcza_po_aneksie_liczy_koszt_z_kontraktu() -> None:
    """Aneks od 1. dnia miesiąca: linia zbiorcza została przy 1000 zł/MD,
    kontrakt płaci 130 zł/h = 1040 zł/MD. Przychód z linii bez zmian."""

    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    try:
        await _hourly(contract_id, date(year - 1, 1, 1))
        await _rate(contract_id, date(year - 1, 1, 1), "125")
        await _rate(contract_id, date(year, mon, 1), "130")
        s = await _set(contract_id, month)
        assert _titles(s) == ["Koszt ze stawki kontraktu: 1040 zł/MD"]
        assert s.amount_cost == Decimal("21840.00")
        assert s.amount_revenue == Decimal("23100.00")
    finally:
        await _cleanup(client_id)


async def test_linia_zbiorcza_zgodna_z_kontraktem_bez_wpisu() -> None:
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, _mon = (int(x) for x in month.split("-"))
    try:
        await _hourly(contract_id, date(year - 1, 1, 1))
        await _rate(contract_id, date(year - 1, 1, 1), "125")
        s = await _set(contract_id, month)
        assert _titles(s) == []
        assert s.amount_cost == Decimal("21000.00")
    finally:
        await _cleanup(client_id)
