"""Korekta dat rozpoczęcia umów (zgłoszenie 21.09.2026) + zapis, który nie wraca.

Korekta jest WYKONYWANA na bazie testowej — literówka wyszłaby dopiero na
produkcji, a entrypoint połknąłby ją. Osoby i klienci są zmyśleni, marker jest
własny (baza testowa jest współdzielona).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.data.contract_start_date_corrections import (
    CORRECTIONS,
    SKIPPED_WITHOUT_DATE,
)
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.services import contract_order_sync
from app.services.contract_start_date_repair import (
    REPAIR_MARKER,
    run_contract_start_date_repair,
    summarize_for_log,
)

WRONG = date(2026, 7, 1)
RIGHT = date(2023, 8, 1)


def test_sheet_data_is_ids_and_dates_only():
    from scripts.show_migration_receipts import is_receipt_key

    assert is_receipt_key(REPAIR_MARKER)
    ids = [row[0] for row in CORRECTIONS]
    assert len(ids) == len(set(ids)) == 287
    assert not set(ids) & set(SKIPPED_WITHOUT_DATE)
    for contract_id, candidate_id, client_id, current, correct in CORRECTIONS:
        assert all(isinstance(v, int) for v in (contract_id, candidate_id, client_id))
        assert current != correct
        date.fromisoformat(correct)


async def _seed(count: int) -> list[Contract]:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Korekta startu {suffix}")
        db.add(client)
        await db.flush()
        contracts = []
        for i in range(count):
            person = Candidate(
                name="Jan",
                lastname=f"Start{suffix}{i}",
                email=f"s{i}-{suffix}@example.test",
            )
            db.add(person)
            await db.flush()
            contract = Contract(
                candidate_id=person.id,
                client_id=client.id,
                contract_type=ContractType.b2b,
                status=ContractStatus.active,
                start_date=WRONG,
            )
            db.add(contract)
            contracts.append(contract)
        await db.commit()
        return contracts


async def _start(contract_id: int) -> date | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Contract.start_date).where(Contract.id == contract_id)
        )


@pytest.mark.asyncio
async def test_repair_applies_pinned_rows_and_skips_the_rest():
    ok, mismatch, edited, done = await _seed(4)
    async with AsyncSessionLocal() as db:
        edited_row = await db.get(Contract, edited.id)
        edited_row.start_date = date(2025, 1, 1)  # człowiek poprawił po migawce
        done_row = await db.get(Contract, done.id)
        done_row.start_date = RIGHT
        await db.commit()

    rows = (
        (ok.id, ok.candidate_id, ok.client_id, WRONG.isoformat(), RIGHT.isoformat()),
        (
            mismatch.id,
            mismatch.candidate_id + 999_999,
            mismatch.client_id,
            WRONG.isoformat(),
            RIGHT.isoformat(),
        ),
        (
            edited.id,
            edited.candidate_id,
            edited.client_id,
            WRONG.isoformat(),
            RIGHT.isoformat(),
        ),
        (
            done.id,
            done.candidate_id,
            done.client_id,
            WRONG.isoformat(),
            RIGHT.isoformat(),
        ),
    )
    marker = f"9999_test_start_date_{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_contract_start_date_repair(
                db, corrections=rows, marker=marker
            )
            await db.commit()
        assert summary["applied"] == 1
        assert summary["skipped"] == {
            "identity_mismatch": [mismatch.id],
            "edited_since_snapshot": [edited.id],
            "already_ok": [done.id],
        }
        assert "applied 1/4" in summarize_for_log(summary)
        assert await _start(ok.id) == RIGHT
        assert await _start(mismatch.id) == WRONG
        assert await _start(edited.id) == date(2025, 1, 1)

        async with AsyncSessionLocal() as db:
            activity = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == ok.id,
                    Activity.action == "start_date_corrected",
                )
            )
            assert activity.details["previous_start_date"] == WRONG.isoformat()
            again = await run_contract_start_date_repair(
                db, corrections=rows, marker=marker
            )
            assert again is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AppSetting).where(AppSetting.key == marker))
            await db.commit()


@pytest.mark.asyncio
async def test_failed_order_sync_does_not_roll_back_the_users_edit(monkeypatch):
    """Błąd synchronizacji nie może cofać daty wpisanej w formularzu.

    Sprawdzone 21.09.2026 przy diagnozie „zapisałam, a wróciło": `begin_nested`
    flushuje zmiany wołającego PRZED savepointem, więc rollback synchronizacji
    ich nie zabiera. Test pilnuje, żeby tak zostało.
    """
    (contract,) = await _seed(1)

    async def enabled(_db):
        return True

    async def boom(*_args, **_kwargs):
        raise RuntimeError("sync failed")

    monkeypatch.setattr(contract_order_sync, "sync_enabled", enabled)
    monkeypatch.setattr(contract_order_sync, "resync_contract", boom)

    async with AsyncSessionLocal() as db:
        row = await db.get(Contract, contract.id)
        row.start_date = RIGHT
        result = await contract_order_sync.resync_contract_safely(
            db, row, actor_id=None
        )
        assert result is None
        await db.commit()

    assert await _start(contract.id) == RIGHT


@pytest.mark.asyncio
async def test_patch_logs_previous_start_date_only_on_real_change(
    app_client, app_auth_headers
):
    """Formularz odsyła datę przy każdym zapisie — dziennik musi odróżnić zmianę."""
    (contract,) = await _seed(1)

    async def last_update() -> dict:
        async with AsyncSessionLocal() as db:
            activity = await db.scalar(
                select(Activity)
                .where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == contract.id,
                    Activity.action == "updated",
                )
                .order_by(Activity.id.desc())
                .limit(1)
            )
            return activity.details

    same = await app_client.patch(
        f"/api/contracts/{contract.id}",
        json={"start_date": WRONG.isoformat(), "project_name": "bez zmiany daty"},
        headers=app_auth_headers,
    )
    assert same.status_code == 200, same.text
    assert "previous_start_date" not in await last_update()

    changed = await app_client.patch(
        f"/api/contracts/{contract.id}",
        json={"start_date": RIGHT.isoformat()},
        headers=app_auth_headers,
    )
    assert changed.status_code == 200, changed.text
    details = await last_update()
    assert details["start_date"] == RIGHT.isoformat()
    assert details["previous_start_date"] == WRONG.isoformat()
    assert await _start(contract.id) == RIGHT
