"""Krok przychodu po korekcie 0306 (``pfron_revenue_resync``) na prawdziwej bazie.

Surowy SQL korekty nie wyzwala synchronizacji kontrakt ↔ zamówienia, więc
przywrócony okres nie ma kroku przychodu i czerwiec–sierpień czytałby stawkę
nowego okresu (przegląd adwersarialny, przypadek H). Scenariusz jak w
``test_pfron_renewal_split_repair_0306`` — własne id i markery, zmyślone dane.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.services.pfron_renewal_split_repair import (
    NEW_PERIOD_START,
    REVENUE_RESYNC_NOT_APPLICABLE,
    REVENUE_RESYNC_PENDING,
)
from app.services.pfron_revenue_resync import (
    STATUS_DONE,
    STATUS_SKIPPED,
    STATUS_SKIPPED_SYNC_DISABLED,
    run_pfron_revenue_resync,
    summarize_for_log,
)
from tests.test_pfron_renewal_split_repair_0306 import (
    AFTER,
    _cleanup,
    _order_row,
    _receipt,
    _seed_target,
    _setup,
    _spec,
    _sql,
)

JULY = date(2026, 7, 15)
SEPTEMBER = date(2026, 9, 15)


def test_only_split_orders_with_a_restorable_revenue_period_are_resynced():
    from app.services.pfron_revenue_resync import _pending_contract_ids

    def split(contract_id, resync):
        return {
            "status": "split",
            "contract_id": contract_id,
            "contract_revenue_resync": resync,
        }

    receipt = {
        "orders": [
            split(3, REVENUE_RESYNC_PENDING),
            split(1, REVENUE_RESYNC_PENDING),
            split(5, REVENUE_RESYNC_NOT_APPLICABLE),
            {"status": "skipped", "contract_id": 7, "reason": "state_changed"},
            # Paragon pierwszej wersji bloku (sprzed utwardzenia).
            split(9, "pending_next_order_write"),
        ]
    }
    assert _pending_contract_ids(receipt) == [1, 3, 9]
    assert _pending_contract_ids({}) == []


async def _seed_and_split(tag: str, split_marker: str, **spec_over):
    """Nadpisane zamówienie z krokiem przychodu, jaki zostawiła synchronizacja
    0304 po T0 (nowa stawka od 01.09), rozdzielone korektą 0306."""
    from app.models.contract_client_rate import ContractClientRate

    async with AsyncSessionLocal() as db:
        client, dl = await _setup(db, tag)
        seeded = await _seed_target(
            db, tag=tag, client=client, dl_user=dl, spec=_spec("r", **spec_over)
        )
        db.add(
            ContractClientRate(
                contract_id=seeded["contract_id"],
                rate=Decimal("81.370"),
                effective_from=NEW_PERIOD_START,
                source_order_id=seeded["order_id"],
                note="Z zamówienia klienta",
                created_at=AFTER,
            )
        )
        await db.commit()
        client_id, dl_id = client.id, dl.id
    async with AsyncSessionLocal() as db:
        await db.execute(text(_sql(split_marker, client_id, [seeded])))
        await db.commit()
    async with AsyncSessionLocal() as db:
        entry = (await _receipt(db, split_marker))["orders"][0]
    assert entry["status"] == "split"
    return client_id, dl_id, seeded, entry


async def _revenue_on(contract_id: int, day: date) -> Decimal:
    from app.models.contract import Contract
    from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields

    async with AsyncSessionLocal() as db:
        contract = await db.scalar(
            select(Contract)
            .where(Contract.id == contract_id)
            .options(*RATE_SCHEDULE_LOADS)
        )
        return effective_rate_fields(contract, day)["rate_client"]


async def _schedule(contract_id: int):
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text(
                    "SELECT effective_from, rate, source_order_id "
                    "FROM contract_client_rates WHERE contract_id = :c "
                    "ORDER BY effective_from, id"
                ),
                {"c": contract_id},
            )
        ).all()


async def _sync_audits(contract_id: int):
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text(
                    "SELECT user_id, details FROM activities "
                    "WHERE entity_type = 'contract' AND entity_id = :c "
                    "AND action = 'synced_with_orders' ORDER BY id"
                ),
                {"c": contract_id},
            )
        ).all()


async def _marker(key: str):
    async with AsyncSessionLocal() as db:
        return await _receipt(db, key)


async def _drop_marker(key: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM app_settings WHERE key = :k"), {"k": key})
        await db.commit()


@pytest.mark.asyncio
async def test_resync_closes_the_revenue_gap_left_by_the_split_and_runs_once():
    tag = uuid.uuid4().hex[:8]
    split_marker, resync_marker = f"t0306s_{tag}", f"t0306v_{tag}"
    client_id, dl_id, seeded, entry = await _seed_and_split(tag, split_marker)
    contract_id, new_id = seeded["contract_id"], entry["new_order_id"]
    try:
        assert entry["contract_revenue_resync"] == REVENUE_RESYNC_PENDING
        # Luka: krok z nadpisanego zamówienia przeszedł z wierszem na nowe
        # zamówienie, więc lipiec czyta stawkę nowego okresu.
        assert await _revenue_on(contract_id, JULY) == Decimal("81.370")
        async with AsyncSessionLocal() as db:
            original_cost = (await _order_row(db, seeded["order_id"]))["rate_candidate"]
        assert original_cost == Decimal("55.000")

        async with AsyncSessionLocal() as db:
            summary = await run_pfron_revenue_resync(
                db, split_marker=split_marker, marker=resync_marker
            )
            await db.commit()

        assert summary["status"] == STATUS_DONE
        assert summary["contract_ids"] == [contract_id]
        [result] = summary["contracts"]
        assert (result["contract_id"], result["result"]) == (contract_id, "changed")
        assert result["details"]["source_order_id"] == new_id
        assert result["details"]["revenue_steps_changed"] == 1
        assert summarize_for_log(summary) == (
            "status=done contracts=1 changed=1 missing=0"
        )
        assert (await _marker(resync_marker))["status"] == STATUS_DONE

        # Lipiec czyta przywróconą stawkę, wrzesień — nową.
        assert await _revenue_on(contract_id, JULY) == Decimal("85.000")
        assert await _revenue_on(contract_id, SEPTEMBER) == Decimal("81.370")
        schedule = await _schedule(contract_id)
        assert [(row[0], row[1], row[2]) for row in schedule] == [
            (date(2026, 6, 1), Decimal("85.000"), seeded["order_id"]),
            (NEW_PERIOD_START, Decimal("81.370"), new_id),
        ]
        # Koszt zakończonego oryginału nie jest przepisywany.
        async with AsyncSessionLocal() as db:
            assert (await _order_row(db, seeded["order_id"]))[
                "rate_candidate"
            ] == original_cost
        # Ten sam audyt co zwykły zapis zamówienia, bez autora.
        audits = await _sync_audits(contract_id)
        assert [row[0] for row in audits] == [None]

        # Drugi bieg: marker → nic.
        async with AsyncSessionLocal() as db:
            assert (
                await run_pfron_revenue_resync(
                    db, split_marker=split_marker, marker=resync_marker
                )
                is None
            )
            await db.commit()
        assert await _schedule(contract_id) == schedule
        assert len(await _sync_audits(contract_id)) == 1
    finally:
        await _drop_marker(resync_marker)
        await _cleanup(client_id, dl_id, split_marker)


@pytest.mark.asyncio
async def test_resync_with_contract_order_sync_disabled_writes_only_the_marker(
    monkeypatch,
):
    async def _disabled(_db) -> bool:
        return False

    monkeypatch.setattr("app.services.contract_order_sync.sync_enabled", _disabled)
    tag = uuid.uuid4().hex[:8]
    split_marker, resync_marker = f"t0306s_{tag}", f"t0306v_{tag}"
    client_id, dl_id, seeded, _entry = await _seed_and_split(tag, split_marker)
    contract_id = seeded["contract_id"]
    try:
        schedule = await _schedule(contract_id)
        async with AsyncSessionLocal() as db:
            summary = await run_pfron_revenue_resync(
                db, split_marker=split_marker, marker=resync_marker
            )
            await db.commit()
        assert summary["status"] == STATUS_SKIPPED_SYNC_DISABLED
        assert summary["contract_ids"] == [contract_id]
        assert (await _marker(resync_marker))["status"] == (
            STATUS_SKIPPED_SYNC_DISABLED
        )
        assert await _schedule(contract_id) == schedule
        assert await _sync_audits(contract_id) == []
        async with AsyncSessionLocal() as db:
            assert (
                await run_pfron_revenue_resync(
                    db, split_marker=split_marker, marker=resync_marker
                )
                is None
            )
            await db.commit()
    finally:
        await _drop_marker(resync_marker)
        await _cleanup(client_id, dl_id, split_marker)


@pytest.mark.asyncio
async def test_resync_without_a_restorable_revenue_period_is_skipped():
    """Przywrócony okres bez daty startu nie tworzy kroku — nie ma czego domykać."""
    tag = uuid.uuid4().hex[:8]
    split_marker, resync_marker = f"t0306s_{tag}", f"t0306v_{tag}"
    client_id, dl_id, seeded, entry = await _seed_and_split(
        tag, split_marker, before_start="None"
    )
    contract_id = seeded["contract_id"]
    try:
        assert entry["contract_revenue_resync"] == REVENUE_RESYNC_NOT_APPLICABLE
        schedule = await _schedule(contract_id)
        async with AsyncSessionLocal() as db:
            summary = await run_pfron_revenue_resync(
                db, split_marker=split_marker, marker=resync_marker
            )
            await db.commit()
        assert (summary["status"], summary["contract_ids"]) == (STATUS_SKIPPED, [])
        assert summarize_for_log(summary) == "status=skipped contracts=0"
        assert await _schedule(contract_id) == schedule
        assert await _sync_audits(contract_id) == []
    finally:
        await _drop_marker(resync_marker)
        await _cleanup(client_id, dl_id, split_marker)


@pytest.mark.asyncio
async def test_resync_waits_for_the_split_receipt_and_skips_a_split_free_one():
    tag = uuid.uuid4().hex[:8]
    split_marker, resync_marker = f"t0306s_{tag}", f"t0306v_{tag}"
    try:
        # Korekta jeszcze nie przeszła (np. timeout blokady): bez markera,
        # następny start spróbuje ponownie.
        async with AsyncSessionLocal() as db:
            assert (
                await run_pfron_revenue_resync(
                    db, split_marker=split_marker, marker=resync_marker
                )
                is None
            )
            await db.commit()
        assert await _marker(resync_marker) is None
        assert summarize_for_log(None) == (
            "nothing to do (already done or 0306 receipt missing)"
        )

        # Paragon bez żadnego podziału.
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "INSERT INTO app_settings (key, value) VALUES (:k, CAST(:v AS jsonb))"
                ),
                {
                    "k": split_marker,
                    "v": '{"client_id": 0, "split": 0, "skipped": 1, "orders": '
                    '[{"status": "skipped", "reason": "order_missing", '
                    '"contract_id": 0}]}',
                },
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            summary = await run_pfron_revenue_resync(
                db, split_marker=split_marker, marker=resync_marker
            )
            await db.commit()
        assert (summary["status"], summary["contract_ids"]) == (STATUS_SKIPPED, [])
        assert (await _marker(resync_marker))["status"] == STATUS_SKIPPED
    finally:
        await _drop_marker(resync_marker)
        await _drop_marker(split_marker)
