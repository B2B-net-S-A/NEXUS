"""Sprzedaż → Leady: dwa równoległe „Utwórz szansę” dają jedną szansę (audyt 24.11.2026).

``convert_lead`` czytał lead bez blokady, więc dwa kliknięcia naraz (dwie
karty, podwójne kliknięcie) przechodziły obie przez sprawdzenie
``status == "converted"`` i zakładały dwie szanse — a gdy firmy jeszcze nie
było, także dwie karty firmy (``normalized_name`` nie jest unikalne).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesCompany, SalesOpportunity
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/leads"


@pytest.mark.asyncio
async def test_parallel_conversions_create_one_opportunity_and_one_company(
    app_client, monkeypatch
) -> None:
    from app.api import sales_leads

    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    company_name = f"Kormoran Serwis {tag}"
    created = await app_client.post(
        URL,
        json={"title": "Szukają 3 analityków", "company_name": company_name},
        headers=_headers(rep),
    )
    assert created.status_code == 201, created.text
    lead_id = created.json()["id"]

    # Obie konwersje mają się spotkać w środku: pierwsza czeka (najwyżej 1 s),
    # aż druga też dojdzie do zakładania szansy. Z blokadą leada druga stoi na
    # niej, więc pierwsza kończy po czasie i druga widzi już „converted”.
    real_convert = sales_leads.service.convert
    entered: list[int] = []
    both_inside = asyncio.Event()

    async def _meeting_convert(db, lead, **kwargs):
        entered.append(lead.id)
        if len(entered) >= 2:
            both_inside.set()
        try:
            await asyncio.wait_for(both_inside.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
        return await real_convert(db, lead, **kwargs)

    monkeypatch.setattr(sales_leads.service, "convert", _meeting_convert)

    first, second = await asyncio.gather(
        app_client.post(f"{URL}/{lead_id}/convert", json={}, headers=_headers(rep)),
        app_client.post(f"{URL}/{lead_id}/convert", json={}, headers=_headers(rep)),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    async with AsyncSessionLocal() as db:
        companies = await db.scalar(
            select(func.count(SalesCompany.id)).where(SalesCompany.name == company_name)
        )
        opportunities = await db.scalar(
            select(func.count(SalesOpportunity.id)).where(
                SalesOpportunity.company_id == first.json()["company_id"]
            )
        )
    assert (companies, opportunities) == (1, 1)
