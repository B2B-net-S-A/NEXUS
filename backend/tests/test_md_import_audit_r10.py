"""Runda 10 audytu (N5): import zużycia MD i zamówienia kosztowe.

* R10-N5-1 — preferencja linii aktywnej tylko dla tej samej osoby u tego
  samego klienta (MD za pracę u klienta A schodziły z zamówienia klienta B).
* R10-N5-2 — przywrócona linia nie przejmuje wiersza z numerem innego klienta.
* R10-N5-3 — wiersz z numerem NASTĘPCY cofa wcześniejszą część miesiąca
  zaksięgowaną na poprzedniku (lustro ``_revert_earlier_transfer``).
* R10-N5-4 — zatwierdzenie przekroczenia wspólnej puli sprawdza grupę i okres.
* R10-N5-5 — nieczytelna kwota w „Fakturze” nie wyrzuca wiersza z poprawnym MD.
* R10-N5-6 — faktura na wyczerpane zamówienie kosztowe: „zamówienie
  wyczerpane — faktura nierozliczona”, nie „brak zamówienia”.
* R10-N5-7 — ``order_number_hint`` przycinany do 64 znaków (≥ 65 cyfr = 500).

Nazwiska, numery i liczby są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from app.models.client_order import ClientOrderStatus
from app.services.client_order_lines import LineMatch, prefer_active_line

BACKEND = Path(__file__).resolve().parents[1]


# ── Testy bez bazy ──────────────────────────────────────────────────────────


def _line(
    order_id: int,
    *,
    client_id: int,
    candidate_id: int | None,
    status=ClientOrderStatus.active,
    number: str = "ZAM/1",
    name: str = "Jan Kowalski",
) -> LineMatch:
    return LineMatch(
        order=SimpleNamespace(
            id=order_id,
            status=status,
            client_id=client_id,
            contract=SimpleNamespace(candidate_id=candidate_id),
        ),
        group=SimpleNamespace(
            id=order_id * 10, client_id=client_id, order_number=number
        ),
        consultant_name=name,
    )


def test_active_line_wins_only_for_the_same_person_at_the_same_client():
    ended = _line(1, client_id=7, candidate_id=70, status=ClientOrderStatus.completed)
    joined = _line(2, client_id=7, candidate_id=70)
    assert prefer_active_line([ended, joined]) == [joined]


def test_active_line_of_another_client_does_not_win():
    """R10-N5-1: linia zakończona u BNP i aktywna u BIK — to nie remis do
    rozstrzygnięcia preferencją, tylko wiersz do przypisania przez człowieka."""
    ended_bnp = _line(
        1, client_id=7, candidate_id=70, status=ClientOrderStatus.completed
    )
    active_bik = _line(2, client_id=8, candidate_id=70)
    assert prefer_active_line([ended_bnp, active_bik]) == [ended_bnp, active_bik]


def test_active_line_of_a_namesake_does_not_win():
    ended = _line(1, client_id=7, candidate_id=70, status=ClientOrderStatus.completed)
    namesake = _line(2, client_id=7, candidate_id=71)
    assert prefer_active_line([ended, namesake]) == [ended, namesake]


def test_unknown_candidate_does_not_win():
    ended = _line(1, client_id=7, candidate_id=None, status=ClientOrderStatus.completed)
    active = _line(2, client_id=7, candidate_id=None)
    assert prefer_active_line([ended, active]) == [ended, active]


def test_row_without_number_waits_for_assignment_across_clients():
    from app.api.md_consumption import _match_per_consultant_md_row

    ended_bnp = _line(
        1, client_id=7, candidate_id=70, status=ClientOrderStatus.completed
    )
    active_bik = _line(2, client_id=8, candidate_id=70, number="4500000002")
    picked = _match_per_consultant_md_row(
        parsed_row=SimpleNamespace(consultant_name="Jan Kowalski", notes_raw=None),
        candidates=[ended_bnp, active_bik],
    )
    assert picked == [ended_bnp, active_bik]


def test_cost_row_with_the_number_of_an_exhausted_order_is_not_missing():
    """R10-N5-6: numer wyczerpanego zamówienia kosztowego tej osoby."""
    from app.api.md_consumption import _match_cost_row
    from app.models.md_consumption import COST_ROW_ORDER_EXHAUSTED

    exhausted = _line(5, client_id=15, candidate_id=90, number="4500777001")
    row = SimpleNamespace(cost_status=None, order_number_hint=None)
    matched = _match_cost_row(
        row,
        parsed_row=SimpleNamespace(
            consultant_name="Jan Kowalski",
            notes_raw="zlecenie 4500777001",
            invoice_amount=Decimal("5000"),
        ),
        cost_candidates=[],
        pending_invoices={},
        invoice_orders={},
        touched_groups={},
        exhausted_cost_candidates=[exhausted],
    )
    assert matched is None
    assert row.cost_status == COST_ROW_ORDER_EXHAUSTED
    assert row.order_number_hint == "4500777001"


def test_cost_row_with_an_unknown_number_stays_unmatched():
    from app.api.md_consumption import _match_cost_row
    from app.models.md_consumption import COST_ROW_UNMATCHED_NUMBER

    exhausted = _line(5, client_id=15, candidate_id=90, number="4500777001")
    row = SimpleNamespace(cost_status=None, order_number_hint=None)
    _match_cost_row(
        row,
        parsed_row=SimpleNamespace(
            consultant_name="Jan Kowalski",
            notes_raw="zlecenie 4500777999",
            invoice_amount=Decimal("5000"),
        ),
        cost_candidates=[],
        pending_invoices={},
        invoice_orders={},
        touched_groups={},
        exhausted_cost_candidates=[exhausted],
    )
    assert row.cost_status == COST_ROW_UNMATCHED_NUMBER


def test_exhausted_cost_row_reason_names_the_exhausted_order():
    from app.api.md_consumption import _unmatched_reason
    from app.models.md_consumption import (
        COST_ROW_ORDER_EXHAUSTED,
        IMPORT_ROW_UNMATCHED,
    )

    row = SimpleNamespace(
        status=IMPORT_ROW_UNMATCHED,
        cost_status=COST_ROW_ORDER_EXHAUSTED,
        order_number_hint="4500777001",
        notes_raw="4500777001",
        consultant_name="Jan Kowalski",
    )
    kind, text = _unmatched_reason(row, "2026-09", SimpleNamespace())
    assert kind == "to_verify"
    assert "wyczerpane" in text
    assert "4500777001" in text


def _book(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.parametrize("invoice", ["brak", "20 900,00 zł netto", "NaN"])
def test_unreadable_invoice_keeps_the_md_of_the_row(invoice):
    """R10-N5-5: MD zostają, faktura dostaje znacznik do ręcznego rozliczenia."""
    from app.services.md_import_parser import parse_md_sheet

    parsed = parse_md_sheet(
        _book(
            [
                ["Konsultant", "MD", "Uwagi", "Faktura"],
                ["Jan Kowalski", 15, None, invoice],
            ]
        )
    )
    assert parsed.skipped_rows == []
    [row] = parsed.rows
    assert row.md_reported == Decimal("15")
    assert row.invoice_amount is None
    assert row.invoice_problem is not None


def test_new_cost_statuses_are_mirrored_in_entrypoint_and_migration():
    entrypoint = re.sub(r"\s+", " ", (BACKEND / "entrypoint.sh").read_text())
    migration = (
        BACKEND / "alembic" / "versions" / "0393_md_import_cost_statuses.py"
    ).read_text()
    for value in ("'invoice_unreadable'", "'order_exhausted'"):
        assert value in entrypoint, value
        assert value in migration, value
    assert 'down_revision = "0392_fin_order_gap_episodes"' in migration


# ── Testy z bazą ────────────────────────────────────────────────────────────

from tests.test_md_import_shared_budget import (  # noqa: E402
    _client_and_contract_for_existing_candidate,
    _create_shared_md_group,
    _enable_cyfrowy_polsat,
    _group_from_list,
)
from tests.test_order_lifecycle_and_cost import (  # noqa: E402
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


async def _end_line(line_id: int, on: date) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        line.status = ClientOrderStatus.completed
        line.end_date = on
        await db.commit()


@pytest.mark.asyncio
async def test_ended_line_at_one_client_and_active_at_another_wait_for_assignment(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """R10-N5-1: MD bez numeru nie schodzą z zamówienia drugiego klienta."""
    first_id, contracts, names = await _seed_client_with_contracts(1)
    second_id, second_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, first_id, second_id)
    ended = await _create_group(
        app_client, app_auth_headers, first_id, [_md_line(contracts[0])]
    )
    active = await _create_group(
        app_client, app_auth_headers, second_id, [_md_line(second_contract)]
    )
    await _end_line(ended["lines"][0]["id"], business_today())
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(app_client, finance, _sheet([(names[0], 10, "", 0)]))

    [row] = detail["rows"]
    assert row["status"] == "needs_assignment", detail
    assert {opt["order_id"] for opt in row["options"]} == {
        ended["lines"][0]["id"],
        active["lines"][0]["id"],
    }
    body = await _group_from_list(app_client, app_auth_headers, second_id, active["id"])
    assert body["lines"][0]["md_remaining"] == pytest.approx(50)


@pytest.mark.asyncio
async def test_restored_line_skips_a_row_bound_to_another_clients_number(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """R10-N5-2: numer w kształcie BIK (nieznany) nie trafia na linię BNP."""
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

    bnp_id, contracts, names = await _seed_client_with_contracts(1)
    bik_id, bik_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, bnp_id, bik_id)
    bnp = await _create_group(
        app_client,
        app_auth_headers,
        bnp_id,
        [_md_line(contracts[0])],
        order_number="ZAM/910/A",
    )
    await _create_group(
        app_client,
        app_auth_headers,
        bik_id,
        [_md_line(bik_contract)],
        order_number="4500910001",
    )
    line_id = bnp["lines"][0]["id"]

    calls: list[dict] = []

    async def _spy(db, **kwargs):
        calls.append(kwargs)
        raise AssertionError("wiersz nie może trafić na linię BNP")

    monkeypatch.setattr(module, "_apply_to_line", _spy)

    async with AsyncSessionLocal() as db:
        batch = MdConsumptionImport(period_month=_period(), filename="r10.xlsx")
        db.add(batch)
        await db.flush()
        db.add(
            MdConsumptionImportRow(
                import_id=batch.id,
                row_number=2,
                consultant_name=names[0],
                md_reported=Decimal("10"),
                status=IMPORT_ROW_UNMATCHED,
                notes_raw="4500919999",
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

    assert rows == []
    assert calls == []


@pytest.mark.asyncio
async def test_reimport_with_the_successors_number_reverts_the_predecessors_part(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """R10-N5-3: paczka 1 podzieliła 20 MD (8 na poprzedniku, 12 na
    następcy); paczka 2 wskazuje NASTĘPCĘ numerem i niesie całe 20 MD —
    wpis poprzednika za ten miesiąc znika (bez tego 28 MD zamiast 20)."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import ClientOrderGroupEvent
    from app.models.md_consumption import (
        ClientOrderMdConsumption,
        MdConsumptionImport,
    )
    from app.services.client_order_lines import recompute_remaining
    from tests.test_md_import_order_number_assignment import (
        _consumptions,
        _events,
        _import,
        _period as _report_period,
        _sheet as _numbered_sheet,
        _ticket_setup,
    )

    case = await _ticket_setup(app_client, app_auth_headers, monkeypatch, old_md=8)
    finance = await _finance_headers(app_client)
    period = _report_period()

    async with AsyncSessionLocal() as db:
        batch = MdConsumptionImport(period_month=period, filename="p1.xlsx")
        db.add(batch)
        await db.flush()
        for order_id, md in ((case["old_line"], "8"), (case["new_line"], "12")):
            db.add(
                ClientOrderMdConsumption(
                    order_id=order_id,
                    period_month=period,
                    md_reported=Decimal(md),
                    source="import",
                    import_id=batch.id,
                )
            )
        db.add(
            ClientOrderGroupEvent(
                group_id=case["new"]["id"],
                order_id=case["new_line"],
                event_type="transfer_md",
                description="przejęcie zużycia (12 MD)",
                payload={
                    "md_transferred": "12.000000",
                    "period_month": period,
                    "predecessor_group_id": case["old"]["id"],
                    "successor_group_id": case["new"]["id"],
                },
            )
        )
        await db.flush()
        for line_id in (case["old_line"], case["new_line"]):
            await recompute_remaining(db, await db.get(ClientOrder, line_id))
        await db.commit()

    detail = await _import(
        app_client,
        finance,
        _numbered_sheet([(case["name"], 20, case["new_number"], 27200)]),
    )
    [row] = detail["rows"]
    assert row["status"] == "applied", detail
    assert row["matched_order_id"] == case["new_line"]
    assert await _consumptions(case["new_line"]) == {period: Decimal("20")}
    assert await _consumptions(case["old_line"]) == {}
    assert any(
        "wcześniejszego podziału" in d for _, d in await _events(case["old"]["id"])
    )


@pytest.mark.asyncio
async def test_shared_pool_overflow_cannot_be_approved_after_the_order_closed(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """R10-N5-4: zamówienie zakończone przed miesiącem wstrzymanej paczki."""
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import (
        ClientOrderGroup,
        ClientOrderGroupMdConsumption,
    )

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_cyfrowy_polsat(monkeypatch, client_id)
    group = await _create_shared_md_group(
        app_client,
        app_auth_headers,
        client_id,
        contracts[0],
        order_number="4500910003",
        budget=10,
    )
    finance = await _finance_headers(app_client)
    detail = await _import_sheet(
        app_client, finance, _sheet([(names[0], 15, "SAP 4500910003", 0)])
    )
    [held] = [r for r in detail["rows"] if r["status"] == "overflow"]

    first = business_today().replace(day=1)
    async with AsyncSessionLocal() as db:
        row = await db.get(ClientOrderGroup, group["id"])
        row.status = "completed"
        row.closure_date = first - timedelta(days=1)
        await db.commit()

    approved = await app_client.post(
        f"/api/md-consumption/imports/{detail['id']}/rows/{held['id']}/assign",
        json={"order_id": held["matched_order_id"], "confirm_overflow": True},
        headers=finance,
    )
    assert approved.status_code == 409, approved.text
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count(ClientOrderGroupMdConsumption.id)).where(
                ClientOrderGroupMdConsumption.group_id == group["id"]
            )
        )
    assert count == 0


@pytest.mark.asyncio
async def test_unreadable_invoice_row_still_books_md(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """R10-N5-5: „brak” w „Fakturze” — 5 MD schodzi, faktura ze znacznikiem."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client, finance, _sheet([(names[0], 5, "", "brak")])
    )

    [row] = detail["rows"]
    assert row["status"] == "applied", detail
    assert row["cost_status"] == "invoice_unreadable"
    assert row["invoice_amount"] is None
    body = await _group_from_list(app_client, app_auth_headers, client_id, group["id"])
    assert body["lines"][0]["md_remaining"] == pytest.approx(45)


@pytest.mark.asyncio
async def test_invoice_for_an_exhausted_cost_order_is_reported_as_unsettled(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """R10-N5-6: numer istnieje, budżet się skończył — faktura nierozliczona."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500910006",
        is_cost_based=True,
        budget_amount=10000,
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(ClientOrderGroup, group["id"])
        row.status = "exhausted"
        await db.commit()
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client, finance, _sheet([(names[0], 0, "4500910006", 2500)])
    )

    [row] = detail["rows"]
    assert row["cost_status"] == "order_exhausted", detail
    assert row["order_number_hint"] == "4500910006"
    assert "wyczerpane" in (row["status_reason"] or "")


@pytest.mark.asyncio
async def test_seventy_digit_note_does_not_break_the_import(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """R10-N5-7: ≥ 65 cyfr w „Uwagach” dawało 500 i przepadał cały import."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client, finance, _sheet([(names[0], 5, "1" * 70, 0)])
    )

    [row] = detail["rows"]
    assert row["order_number_hint"] is None or len(row["order_number_hint"]) <= 64
