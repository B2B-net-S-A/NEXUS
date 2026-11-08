"""Nocny raport rozjazdów stawek kontrakt ↔ linia zamówienia MD (A5). Dane fikcyjne."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.api import finance as finance_api
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client_order import ClientOrder
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services import rate_divergence_report as report
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio

NOVEMBER = date(2026, 11, 20)


@pytest_asyncio.fixture
async def http():
    target = FastAPI()
    target.include_router(finance_api.router, prefix="/api/finance")
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as client:
        yield client


async def _set_contract(line_id: int, **values: object) -> None:
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, line_id)
        await db.execute(
            update(Contract).where(Contract.id == order.contract_id).values(**values)
        )
        await db.commit()


async def _group(number: str, people: list[tuple[str, str, str, str | None]]):
    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Bank Rozjazdów", None)
        _group_id, lines = await fx.md_group(db, client_id, number, people=people)
        await db.commit()
    # Pomocnik zakłada kontrakt bez jednostki; stawki 150/100 to zł za godzinę.
    for line in lines:
        await _set_contract(line, rate_unit=RateUnit.hourly)
    return client_id, lines


async def _rows(number: str, today: date = NOVEMBER) -> list[dict]:
    async with AsyncSessionLocal() as db:
        built = await report.build_report(db, today=today)
    return [row for row in built["rows"] if row["order_number"] == number]


def _number() -> str:
    return f"ZAM/{uuid.uuid4().hex[:8]}"


async def test_revenue_divergence_lists_person_client_amount_and_month() -> None:
    number = _number()
    _client, (line,) = await _group(number, [("Maria", "Rozjazdowa", "750", "20")])
    await _set_contract(
        line,
        rate_unit=RateUnit.daily,
        rate_client=Decimal("800"),
        rate_candidate=Decimal("800"),
    )

    rows = await _rows(number)

    assert len(rows) == 1
    row = rows[0]
    assert row["person"] == "Maria Rozjazdowa"
    assert row["client_name"].startswith("Bank Rozjazdów")
    assert row["leg"] == "revenue"
    assert row["month"] == "2026-10"
    assert (row["contract_rate"], row["order_rate"]) == ("800.00", "750.00")
    assert row["difference"] == "-50.00"
    assert (row["md"], row["effect"]) == ("20.00", "-1000.00")
    assert row["rounding"] is False


async def test_matching_rates_are_not_a_divergence() -> None:
    number = _number()
    await _group(number, [("Ola", "Zgodna", "1200", "10")])
    assert await _rows(number) == []


async def test_cost_leg_is_reported_separately() -> None:
    number = _number()
    _client, (line,) = await _group(number, [("Piotr", "Kosztowy", "1200", None)])
    await _set_contract(line, rate_candidate=Decimal("110"))

    rows = await _rows(number)

    assert [row["leg"] for row in rows] == ["cost"]
    assert rows[0]["difference"] == "-80.00"
    assert rows[0]["md"] is None and rows[0]["effect"] is None


async def test_hourly_rounding_is_marked_and_goes_last() -> None:
    number = _number()
    _client, (line,) = await _group(number, [("Ela", "Zaokrąglona", "1203", "10")])

    rows = await _rows(number)

    assert rows[0]["difference"] == "3.00"
    assert rows[0]["rounding"] is True


async def test_contract_without_rate_is_counted_not_reported() -> None:
    number = _number()
    _client, (line,) = await _group(number, [("Iga", "Pusta", "750", "5")])
    await _set_contract(line, rate_client=None, rate_candidate=None)

    assert await _rows(number) == []


async def test_draft_contract_is_out_of_scope() -> None:
    number = _number()
    _client, (line,) = await _group(number, [("Kai", "Szkic", "750", "5")])
    await _set_contract(line, status=ContractStatus.draft)

    assert await _rows(number) == []


async def test_line_outside_the_closed_month_is_out_of_scope() -> None:
    number = _number()
    _client, (line,) = await _group(number, [("Ida", "Przyszla", "750", None)])
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientOrder)
            .where(ClientOrder.id == line)
            .values(start_date=date(2026, 11, 2))
        )
        await db.commit()

    assert await _rows(number) == []


async def test_january_reports_december_of_previous_year() -> None:
    assert report.report_month(date(2027, 1, 5)) == (2026, 12)


async def test_rows_carry_no_database_ids_in_text() -> None:
    number = _number()
    client_id, (line,) = await _group(number, [("Ula", "Bezid", "750", "4")])
    await _set_contract(line, rate_unit=RateUnit.daily, rate_client=Decimal("800"))

    rows = await _rows(number)

    visible = {key: value for key, value in rows[0].items() if key != "link"}
    assert not re.search(rf"\b({client_id}|{line})\b", json.dumps(visible))


async def test_refresh_saves_the_nightly_snapshot() -> None:
    number = _number()
    _client, (line,) = await _group(number, [("Ewa", "Snapshot", "750", "4")])
    await _set_contract(line, rate_unit=RateUnit.daily, rate_client=Decimal("800"))
    try:
        async with AsyncSessionLocal() as db:
            await report.refresh(db, today=NOVEMBER)
            await db.commit()
        async with AsyncSessionLocal() as db:
            saved = await report.latest(db)
        assert saved["month"] == "2026-10"
        assert any(row["order_number"] == number for row in saved["rows"])
    finally:
        async with AsyncSessionLocal() as db:
            row = await db.get(AppSetting, report.SETTING_KEY)
            if row is not None:
                await db.delete(row)
            await db.commit()


@pytest.mark.parametrize(
    "role, expected",
    [("finance", 200), ("recruiter", 403), ("delivery_lead", 403)],
)
async def test_route_is_finance_only(http, role, expected) -> None:
    async with AsyncSessionLocal() as db:
        user = await fx.make_user(db, role)
        await db.commit()
    response = await http.get("/api/finance/rate-divergences", headers=fx.headers(user))
    assert response.status_code == expected, response.text


async def test_route_says_when_report_has_not_run(http) -> None:
    async with AsyncSessionLocal() as db:
        await db.delete(
            await db.scalar(
                select(AppSetting).where(AppSetting.key == report.SETTING_KEY)
            )
        ) if await db.get(AppSetting, report.SETTING_KEY) else None
        user = await fx.make_user(db, "finance")
        await db.commit()
    response = await http.get("/api/finance/rate-divergences", headers=fx.headers(user))
    assert response.json()["generated_at"] is None
    assert response.json()["rows"] == []
