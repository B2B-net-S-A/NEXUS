"""Legacy client-order Excel export: scope, order and financial columns."""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from openpyxl import load_workbook


async def _seed_order(label: str) -> tuple[int, int, int, str]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Anna",
            lastname=f"Eksportowa {suffix}",
            email=f"excel-{suffix}@example.com",
        )
        client = Client(name=f"{label} {suffix}")
        db.add_all([candidate, client])
        await db.commit()
        await db.refresh(candidate)
        await db.refresh(client)
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=date.today() - timedelta(days=30),
            rate_candidate=Decimal("123.456"),
            rate_client=Decimal("180.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"PO-{suffix}",
            status=ClientOrderStatus.active,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            rate_client=Decimal("185.750"),
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return (
            client.id,
            order.id,
            contract.id,
            f"{candidate.name} {candidate.lastname}",
        )


async def test_legacy_excel_export_has_visible_order_and_scoped_ids(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id, order_id, _, consultant = await _seed_order("Klient Eksport")
    other_client_id, other_order_id, _, _ = await _seed_order("Inny Klient")

    response = await app_client.post(
        f"/api/clients/{client_id}/orders/export",
        headers=app_auth_headers,
        json={"order_ids": [order_id]},
    )
    assert response.status_code == 200, response.text
    assert "Zamowienia_Klient_Eksport" in response.headers["content-disposition"]
    sheet = load_workbook(io.BytesIO(response.content)).active
    assert sheet.max_row == 2
    assert sheet["A2"].value == consultant
    assert sheet["C2"].value == 123.456
    assert sheet["D2"].value == 185.75
    assert sheet["E2"].value == "01.01.2026 – 31.12.2026"

    foreign = await app_client.post(
        f"/api/clients/{client_id}/orders/export",
        headers=app_auth_headers,
        json={"order_ids": [other_order_id]},
    )
    assert foreign.status_code == 404, foreign.text
    assert other_client_id != client_id
