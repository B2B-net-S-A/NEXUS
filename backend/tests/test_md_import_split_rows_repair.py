"""Korekta ticketu 1.1: dwa wiersze jednej osoby zsumowane na jednym zamówieniu.

Odtwarza stan z produkcji z 24.09.2026 na zmyślonych danych: 23 MD za lipiec
i 21 MD za sierpień (2 + 19) na zamówieniu A, saldo −19, zamówienie A
zakończone automatycznie „dziś”, zamówienie B (wystawione po sierpniu) puste.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from tests.test_md_import_order_number_assignment import (
    _consumptions,
    _events,
    _finance_headers,
    _import,
    _period,
    _prev_period,
    _sheet,
    _two_orders_one_issued_after_the_month,
)

pytestmark = pytest.mark.asyncio


async def _seed_wrong_state(app_client: AsyncClient, headers: dict, monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup
    from app.models.md_consumption import (
        CONSUMPTION_SOURCE_IMPORT,
        IMPORT_ROW_APPLIED,
        ClientOrderMdConsumption,
        MdConsumptionImport,
        MdConsumptionImportRow,
    )
    from app.services.client_order_lines import recompute_remaining
    from app.services.order_md_exhaustion import MD_EXHAUSTED_CLOSURE_REASON

    case = await _two_orders_one_issued_after_the_month(
        app_client, headers, bik=True, monkeypatch=monkeypatch
    )
    finance = await _finance_headers(app_client)
    await _import(
        app_client,
        finance,
        _sheet([(case["name"], 23, case["a_number"], 0)]),
        period=_prev_period(),
    )
    wrong_closure = business_today()
    async with AsyncSessionLocal() as db:
        batch = MdConsumptionImport(period_month=_period(), filename="stary.xlsx")
        db.add(batch)
        await db.flush()
        for number, md, hint in (
            (35, "2", case["a_number"]),
            (36, "19", case["b_number"]),
        ):
            db.add(
                MdConsumptionImportRow(
                    import_id=batch.id,
                    row_number=number,
                    consultant_name=case["name"],
                    md_reported=Decimal(md),
                    status=IMPORT_ROW_APPLIED,
                    matched_order_id=case["a_line"],
                    notes_raw=hint,
                    order_number_hint=hint,
                )
            )
        db.add(
            ClientOrderMdConsumption(
                order_id=case["a_line"],
                period_month=_period(),
                md_reported=Decimal("21"),
                source=CONSUMPTION_SOURCE_IMPORT,
                import_id=batch.id,
            )
        )
        await db.flush()
        line = await db.get(ClientOrder, case["a_line"])
        line.status = ClientOrderStatus.completed
        await recompute_remaining(db, line, rebalance=False)
        group = await db.get(ClientOrderGroup, line.order_group_id)
        group.status = "completed"
        group.closure_reason = MD_EXHAUSTED_CLOSURE_REASON
        group.closure_date = wrong_closure
        group.closed_by_user_id = None
        right = await db.get(ClientOrder, case["b_line"])
        case.update(
            a_group=line.order_group_id,
            b_group=right.order_group_id,
            contract_id=line.contract_id,
            client_id=line.client_id,
            import_id=batch.id,
            wrong_closure=wrong_closure,
        )
        await db.commit()
    return case


def _spec(case):
    from app.services.md_import_split_rows_repair import SplitRowsCase

    return SplitRowsCase(
        client_id=case["client_id"],
        contract_id=case["contract_id"],
        wrong_order_id=case["a_line"],
        wrong_group_id=case["a_group"],
        wrong_number=case["a_number"],
        right_order_id=case["b_line"],
        right_group_id=case["b_group"],
        right_number=case["b_number"],
        report_month=_period(),
        import_id=case["import_id"],
        moved_row_number=36,
        expected_before={
            (case["a_line"], _prev_period()): Decimal("23"),
            (case["a_line"], _period()): Decimal("21"),
        },
        target={
            (case["a_line"], _period()): Decimal("2"),
            (case["b_line"], _period()): Decimal("19"),
        },
        wrong_closure_date=case["wrong_closure"],
    )


def _month_end(period: str) -> date:
    import calendar

    year, month = (int(p) for p in period.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


async def test_repair_books_each_row_on_its_order_and_redates_the_closure(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import ClientOrderGroup
    from app.models.md_consumption import MdConsumptionImportRow
    from app.services import md_import_split_rows_repair as repair

    case = await _seed_wrong_state(app_client, app_auth_headers, monkeypatch)
    marker = f"test_split_repair_{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        summary = await repair.run_md_import_split_rows_repair(
            db, case=_spec(case), marker=marker, details_key=f"{marker}_details"
        )
        await db.commit()
    assert summary["applied"] is True, summary

    assert await _consumptions(case["a_line"]) == {
        _prev_period(): Decimal("23"),
        _period(): Decimal("2"),
    }
    assert await _consumptions(case["b_line"]) == {_period(): Decimal("19")}
    async with AsyncSessionLocal() as db:
        a = await db.get(ClientOrder, case["a_line"])
        b = await db.get(ClientOrder, case["b_line"])
        assert Decimal(str(a.md_remaining)) == Decimal("0")
        assert Decimal(str(b.md_remaining)) == Decimal("23")
        group = await db.get(ClientOrderGroup, case["a_group"])
        assert group.status == "completed"
        assert group.closure_date == _month_end(_period())
        moved = (
            await db.execute(
                MdConsumptionImportRow.__table__.select().where(
                    MdConsumptionImportRow.import_id == case["import_id"],
                    MdConsumptionImportRow.row_number == 36,
                )
            )
        ).first()
        assert moved.matched_order_id == case["b_line"]
    assert any("Korekta importu MD" in d for _, d in await _events(case["a_group"]))
    assert any("Korekta importu MD" in d for _, d in await _events(case["b_group"]))

    async with AsyncSessionLocal() as db:
        again = await repair.run_md_import_split_rows_repair(
            db, case=_spec(case), marker=marker, details_key=f"{marker}_details"
        )
    assert again is None


async def test_repair_leaves_a_hand_corrected_state_alone(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import ClientOrderMdConsumption
    from app.services import md_import_split_rows_repair as repair
    from sqlalchemy import update

    case = await _seed_wrong_state(app_client, app_auth_headers, monkeypatch)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientOrderMdConsumption)
            .where(
                ClientOrderMdConsumption.order_id == case["a_line"],
                ClientOrderMdConsumption.period_month == _period(),
            )
            .values(md_reported=Decimal("2"))
        )
        await db.commit()

    marker = f"test_split_repair_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        summary = await repair.run_md_import_split_rows_repair(
            db, case=_spec(case), marker=marker, details_key=f"{marker}_details"
        )
        await db.commit()
    assert summary["applied"] is False
    assert summary["skipped"] == "edited_since_snapshot"
    assert await _consumptions(case["b_line"]) == {}


def test_entrypoint_runs_the_repair_once():
    source = open("entrypoint.sh", encoding="utf-8").read()
    assert 'startup_phase "repair-md-import-split-rows"' in source
    assert "run_md_import_split_rows_repair" in source


def test_overflow_status_is_mirrored_in_entrypoint_and_migration():
    """0375: status ``overflow`` i kolumna ``overflow_md`` w migracji i lustrze."""
    source = open("entrypoint.sh", encoding="utf-8").read()
    migration = open(
        "alembic/versions/0375_md_import_row_overflow.py", encoding="utf-8"
    ).read()
    assert "ADD COLUMN IF NOT EXISTS overflow_md NUMERIC(16, 6) NULL" in source
    assert "'overflow'" in migration
    block = source[source.index("0375: 'overflow'") :]
    block = block[: block.index("END $$")]
    assert "'overflow'" in block
