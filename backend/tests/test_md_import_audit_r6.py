"""Runda 6 audytu (26.09.2026) — wiązanie numeru zamówienia w imporcie MD.

MD-3: numer zamówienia KOSZTOWEGO osoby (np. SAP Polkomtela) wiąże wiersz tak
samo jak numer jej zamówienia MD — wiersz rozliczający fakturę u Polkomtela nie
może odjąć MD po samym nazwisku u innego klienta.

MD-4: osoba z linią wspólnej puli i linią MD per osoba u innego klienta —
wiersz bez numeru puli nie zostaje `unmatched` bez kandydatów (ręczne
przypisanie dawało 409).

MD-5: przeliczenie wierszy po cofnięciu zakończenia
(``reapply_rows_for_restored_line``) zapisuje wiersz z numerem jako wskazany
numerem (``explicit_order``), bez przekierowania na poprzednika.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.test_md_import_shared_budget import (
    _client_and_contract_for_existing_candidate,
    _create_shared_md_group,
    _enable_cyfrowy_polsat,
    _group_from_list,
)
from tests.test_order_lifecycle_and_cost import (
    _cost_line,
    _create_group,
    _enable_cost,
    _enable_multi,
    _finance_headers,
    _import_sheet,
    _md_line,
    _period,
    _seed_client_with_contracts,
    _sheet,
)
from tests.test_polkomtel_finance_order_matching import _set_polkomtel

pytestmark = pytest.mark.asyncio


async def test_cost_order_number_blocks_md_name_match_at_another_client(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    other_id, other_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, polkomtel_id, other_id)
    _enable_cost(monkeypatch, polkomtel_id)
    _set_polkomtel(monkeypatch, polkomtel_id)

    cost = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_cost_line(contracts[0])],
        order_number="SAP 3456789",
        is_cost_based=True,
        budget_amount=10000,
    )
    md = await _create_group(
        app_client,
        app_auth_headers,
        other_id,
        [_md_line(other_contract)],
        order_number="ZAM/445/A",
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 7, "3456789", 2500)]),
    )

    row = detail["rows"][0]
    assert row["status"] != "applied"
    assert row["matched_order_id"] is None
    assert row["cost_status"] == "applied"
    md_body = await _group_from_list(app_client, app_auth_headers, other_id, md["id"])
    assert md_body["lines"][0]["md_remaining"] == pytest.approx(50)
    cost_body = await _group_from_list(
        app_client, app_auth_headers, polkomtel_id, cost["id"]
    )
    assert cost_body["budget_remaining"] == pytest.approx(7500)


async def test_row_of_shared_pool_person_without_pool_number_waits_for_assignment(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    shared_client, contracts, names = await _seed_client_with_contracts(1)
    legacy_client, legacy_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_cyfrowy_polsat(monkeypatch, shared_client)
    _enable_multi(monkeypatch, legacy_client)
    await _create_shared_md_group(
        app_client,
        app_auth_headers,
        shared_client,
        contracts[0],
        order_number="4500820001",
    )
    legacy = await _create_group(
        app_client,
        app_auth_headers,
        legacy_client,
        [_md_line(legacy_contract, input_value=50)],
        order_number="ZAM/820/B",
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client, finance, _sheet([(names[0], 5, "delegacja", 0)])
    )

    row = detail["rows"][0]
    assert row["status"] == "needs_assignment"
    assert [opt["order_id"] for opt in row["options"]] == [legacy["lines"][0]["id"]]

    assigned = await app_client.post(
        f"/api/md-consumption/imports/{detail['id']}/rows/{row['id']}/assign",
        json={"order_id": legacy["lines"][0]["id"]},
        headers=finance,
    )
    assert assigned.status_code == 200, assigned.text
    body = await _group_from_list(
        app_client, app_auth_headers, legacy_client, legacy["id"]
    )
    assert body["lines"][0]["md_remaining"] == pytest.approx(45)


async def test_reapply_after_restore_books_a_numbered_row_as_explicit(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.api import md_consumption as module
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract
    from app.models.md_consumption import (
        IMPORT_ROW_UNMATCHED,
        MdConsumptionImport,
        MdConsumptionImportRow,
    )

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0])],
        order_number="4500830001",
    )
    line_id = group["lines"][0]["id"]

    captured: list[dict] = []
    real_apply = module._apply_to_line

    async def _spy(db, **kwargs):
        captured.append(kwargs)
        return await real_apply(db, **kwargs)

    monkeypatch.setattr(module, "_apply_to_line", _spy)

    async with AsyncSessionLocal() as db:
        batch = MdConsumptionImport(period_month=_period(), filename="r6.xlsx")
        db.add(batch)
        await db.flush()
        db.add(
            MdConsumptionImportRow(
                import_id=batch.id,
                row_number=2,
                consultant_name=names[0],
                md_reported=Decimal("3"),
                status=IMPORT_ROW_UNMATCHED,
                notes_raw="4500830001",
            )
        )
        await db.commit()

        line = await db.scalar(
            select(ClientOrder)
            .options(
                selectinload(ClientOrder.order_group),
                selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            )
            .where(ClientOrder.id == line_id)
        )
        rows = await module.reapply_rows_for_restored_line(
            db,
            line=line,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            ended_on=None,
            target_end_date=None,
            user_id=None,
            dry_run=False,
        )
        await db.rollback()

    assert [r.skipped for r in rows] == [None]
    assert captured and captured[0].get("explicit_order") is True
