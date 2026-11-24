"""Import MD — błędy z drugiej rundy audytu 24.11.2026.

1. Ręczne przypisanie wiersza (``assign_row``) i przeliczenie importów po
   cofnięciu zakończenia (``reapply_rows_for_restored_line``) sprawdzały
   „nowsza paczka albo wpis ręczny” PRZED blokadą kontraktu i linii. Gdy
   wpisu za miesiąc jeszcze nie było, nie było czego zablokować, więc
   równoległy import nowszej paczki zapisywał MD, a starsza paczka po
   zwolnieniu blokady je nadpisywała.
2. Przeliczenie po cofnięciu zakończenia księgowało po samym nazwisku wiersz
   osoby, która w tym miesiącu ma linię wspólnej puli. Zwykły import daje
   takiemu wierszowi „Wymaga przypisania”, bo mógł dotyczyć puli.
3. ``name_tokens`` dzieliło nazwisko tylko po spacji: „Nowak-Kowalska” nie
   było tą samą osobą co „Nowak Kowalska”.

Osoby i kwoty są fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.services.client_order_lines import name_tokens


def test_hyphenated_surname_gives_the_same_tokens_as_spaced_one():
    expected = frozenset({"anna", "nowak", "kowalska"})
    assert name_tokens("Anna Nowak-Kowalska") == expected
    assert name_tokens("Anna Nowak Kowalska") == expected
    assert name_tokens("NOWAK-KOWALSKA Anna") == expected


def test_punctuation_around_tokens_does_not_create_empty_tokens():
    assert name_tokens(" Jan  –  Kowalski ") == frozenset({"jan", "kowalski"})
    assert name_tokens("Łukasz Żółć-Gęś") == frozenset({"lukasz", "zolc", "ges"})
    assert name_tokens("-") == frozenset()
    # Placeholder jako osobne słowo nadal nie jest tokenem nazwiska.
    assert name_tokens("Jan Kowalski n/a") == frozenset({"jan", "kowalski"})


# ── Testy z bazą ────────────────────────────────────────────────────────────

from tests.test_md_import_shared_budget import (  # noqa: E402
    _client_and_contract_for_existing_candidate,
    _create_shared_md_group,
    _enable_cyfrowy_polsat,
)
from tests.test_order_lifecycle_and_cost import (  # noqa: E402
    _create_group,
    _enable_multi,
    _finance_headers,
    _md_line,
    _period,
    _seed_client_with_contracts,
)


async def _wait_until_someone_waits_for_a_lock(timeout: float = 15.0) -> None:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    deadline = asyncio.get_running_loop().time() + timeout
    async with AsyncSessionLocal() as probe:
        while asyncio.get_running_loop().time() < deadline:
            waiting = await probe.scalar(
                text("SELECT count(*) FROM pg_locks WHERE NOT granted")
            )
            await probe.rollback()
            if waiting:
                return
            await asyncio.sleep(0.05)
    raise AssertionError("druga transakcja nie czekała na blokadę linii")


async def _batches_with_row(
    *, consultant_name: str, status: str, candidate_order_ids=None
) -> tuple[int, int, int]:
    """Starsza paczka z jednym wierszem i nowsza paczka za ten sam miesiąc."""
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import MdConsumptionImport, MdConsumptionImportRow

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        older = MdConsumptionImport(
            period_month=_period(),
            filename="starsza.xlsx",
            created_at=now - timedelta(hours=1),
        )
        newer = MdConsumptionImport(
            period_month=_period(), filename="nowsza.xlsx", created_at=now
        )
        db.add_all([older, newer])
        await db.flush()
        row = MdConsumptionImportRow(
            import_id=older.id,
            row_number=2,
            consultant_name=consultant_name,
            md_reported=Decimal("10"),
            status=status,
            candidate_order_ids=candidate_order_ids,
        )
        db.add(row)
        await db.commit()
        return older.id, row.id, newer.id


async def _hold_line_and_book_newer(line_id: int, newer_id: int):
    """Import nowszej paczki: blokada kontraktu i linii, zapis MD, bez commitu."""
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import (
        CONSUMPTION_SOURCE_IMPORT,
        ClientOrderMdConsumption,
    )
    from app.services.contract_lifecycle import lock_contract_then_orders

    session = AsyncSessionLocal()
    await lock_contract_then_orders(session, order_ids=[line_id])
    session.add(
        ClientOrderMdConsumption(
            order_id=line_id,
            period_month=_period(),
            md_reported=Decimal("7"),
            import_id=newer_id,
            source=CONSUMPTION_SOURCE_IMPORT,
        )
    )
    await session.flush()
    return session


async def _booked_md(line_id: int) -> Decimal | None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import ClientOrderMdConsumption

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(ClientOrderMdConsumption.md_reported).where(
                ClientOrderMdConsumption.order_id == line_id,
                ClientOrderMdConsumption.period_month == _period(),
            )
        )


async def _load_line(db, line_id: int):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.client_order import ClientOrder
    from app.models.contract import Contract

    return await db.scalar(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.order_group),
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
        )
        .where(ClientOrder.id == line_id)
    )


@pytest.mark.asyncio
async def test_assign_row_of_older_batch_does_not_overwrite_concurrent_newer_import(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.models.md_consumption import IMPORT_ROW_NEEDS_ASSIGNMENT

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    line_id = group["lines"][0]["id"]
    finance = await _finance_headers(app_client)
    older_id, row_id, newer_id = await _batches_with_row(
        consultant_name=names[0],
        status=IMPORT_ROW_NEEDS_ASSIGNMENT,
        candidate_order_ids=[line_id],
    )

    newer_import = await _hold_line_and_book_newer(line_id, newer_id)
    try:
        assign = asyncio.create_task(
            app_client.post(
                f"/api/md-consumption/imports/{older_id}/rows/{row_id}/assign",
                json={"order_id": line_id},
                headers=finance,
            )
        )
        await _wait_until_someone_waits_for_a_lock()
        await newer_import.commit()
    finally:
        await newer_import.close()
    resp = await asyncio.wait_for(assign, timeout=30)

    assert resp.status_code == 409, resp.text
    assert "nowszego importu" in resp.json()["detail"]
    assert await _booked_md(line_id) == Decimal("7")


@pytest.mark.asyncio
async def test_restored_line_does_not_overwrite_concurrent_newer_import(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.api import md_consumption as module
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import IMPORT_ROW_UNMATCHED

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    line_id = group["lines"][0]["id"]
    _older_id, _row_id, newer_id = await _batches_with_row(
        consultant_name=names[0], status=IMPORT_ROW_UNMATCHED
    )

    async def _reapply():
        async with AsyncSessionLocal() as db:
            rows = await module.reapply_rows_for_restored_line(
                db,
                line=await _load_line(db, line_id),
                since=datetime.now(timezone.utc) - timedelta(hours=2),
                ended_on=None,
                target_end_date=None,
                user_id=None,
                dry_run=False,
            )
            await db.commit()
            return rows

    newer_import = await _hold_line_and_book_newer(line_id, newer_id)
    try:
        reapply = asyncio.create_task(_reapply())
        await _wait_until_someone_waits_for_a_lock()
        await newer_import.commit()
    finally:
        await newer_import.close()
    [result] = await asyncio.wait_for(reapply, timeout=30)

    assert result.skipped and "nowszego importu" in result.skipped
    assert await _booked_md(line_id) == Decimal("7")


@pytest.mark.asyncio
async def test_restored_line_leaves_row_of_a_shared_pool_person_for_assignment(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.api import md_consumption as module
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import (
        IMPORT_ROW_NEEDS_ASSIGNMENT,
        IMPORT_ROW_UNMATCHED,
        MdConsumptionImportRow,
    )

    own_id, contracts, names = await _seed_client_with_contracts(1)
    pool_client_id, pool_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, own_id, pool_client_id)
    _enable_cyfrowy_polsat(monkeypatch, pool_client_id)
    group = await _create_group(
        app_client, app_auth_headers, own_id, [_md_line(contracts[0])]
    )
    await _create_shared_md_group(
        app_client,
        app_auth_headers,
        pool_client_id,
        pool_contract,
        order_number="POOL/24/11",
    )
    line_id = group["lines"][0]["id"]
    _older_id, row_id, _newer_id = await _batches_with_row(
        consultant_name=names[0], status=IMPORT_ROW_UNMATCHED
    )

    async def _reapply(dry_run: bool):
        async with AsyncSessionLocal() as db:
            rows = await module.reapply_rows_for_restored_line(
                db,
                line=await _load_line(db, line_id),
                since=datetime.now(timezone.utc) - timedelta(hours=2),
                ended_on=None,
                target_end_date=None,
                user_id=None,
                dry_run=dry_run,
            )
            await db.commit()
            return rows

    [preview] = await _reapply(dry_run=True)
    assert preview.skipped and "Wymaga przypisania" in preview.skipped

    [result] = await _reapply(dry_run=False)
    assert result.skipped and "Wymaga przypisania" in result.skipped
    assert await _booked_md(line_id) is None
    async with AsyncSessionLocal() as db:
        row = await db.get(MdConsumptionImportRow, row_id)
        assert row.status == IMPORT_ROW_NEEDS_ASSIGNMENT
        assert row.candidate_order_ids == [line_id]
