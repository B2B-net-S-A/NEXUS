"""Jednorazowe usunięcie zamówienia z odwróconym okresem (Alior, 28.09.2026).

Korekta jest WYKONYWANA na bazie testowej — literówka wyszłaby dopiero na
produkcji, a entrypoint połknąłby ją (``|| echo skipped``). Scenariusz
odtwarza zgłoszenie: dwa zamówienia tej samej osoby o jednym numerze —
poprawne (X-10-01 – X-12-31) i drugie (X+1-01-01 → X-12-31) z krokiem stawki
klienta od X+1-01-01. Osoby i numery zmyślone, marker własny.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.contract_client_rate import ContractClientRate
from app.models.critical_event import CriticalEvent
from app.services.alior_reversed_order_repair import (
    REPAIR_MARKER,
    TICKET_TARGETS,
    ReversedOrderTarget,
    run_alior_reversed_order_repair,
    summarize_for_log,
)

KEEP_START = date(2033, 10, 1)
KEEP_END = date(2033, 12, 31)
BAD_START = date(2034, 1, 1)


def test_ticket_pins_the_alior_order_and_receipt_is_public_safe():
    from scripts.show_migration_receipts import is_receipt_key

    (target,) = TICKET_TARGETS
    assert (target.order_id, target.contract_id, target.client_id) == (653, 646, 39)
    assert target.start_date > target.end_date
    assert target.keep_order_id == 630
    assert is_receipt_key(REPAIR_MARKER)


async def _seed() -> tuple[ReversedOrderTarget, dict]:
    suffix = uuid.uuid4().hex[:8]
    title = f"OIT/{suffix}/2033/ITVM"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Alior odwrócony {suffix}")
        person = Candidate(
            name="Ola", lastname=f"Testowa{suffix}", email=f"al-{suffix}@example.test"
        )
        db.add_all([client, person])
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=date(2033, 9, 1),
            rate_candidate=Decimal("880.000"),
            rate_client=Decimal("1176.500"),
            rate_unit=RateUnit.daily,
        )
        db.add(contract)
        await db.flush()
        keep = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=title,
            status=ClientOrderStatus.active,
            start_date=KEEP_START,
            end_date=KEEP_END,
            rate_client=Decimal("1176.500"),
            rate_unit=RateUnit.daily,
        )
        bad = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=title,
            status=ClientOrderStatus.active,
            start_date=BAD_START,
            end_date=KEEP_END,
            rate_client=Decimal("1176.500"),
            rate_unit=RateUnit.daily,
        )
        db.add_all([keep, bad])
        await db.flush()
        db.add_all(
            [
                ContractClientRate(
                    contract_id=contract.id,
                    rate=Decimal("1176.5"),
                    effective_from=KEEP_START,
                    source_order_id=keep.id,
                ),
                ContractClientRate(
                    contract_id=contract.id,
                    rate=Decimal("1176.5"),
                    effective_from=BAD_START,
                    source_order_id=bad.id,
                ),
            ]
        )
        await db.commit()
        target = ReversedOrderTarget(
            order_id=bad.id,
            contract_id=contract.id,
            candidate_id=person.id,
            client_id=client.id,
            title=title,
            start_date=BAD_START,
            end_date=KEEP_END,
            keep_order_id=keep.id,
            keep_start_date=KEEP_START,
            keep_end_date=KEEP_END,
        )
        return target, {"client_id": client.id, "candidate_id": person.id}


async def _cleanup(ids: dict, *markers: str) -> None:
    # Jak w teście korekty CeZ: dane testowe mają unikalne nazwy, sprzątamy
    # wyłącznie własne markery.
    del ids
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSetting).where(AppSetting.key.in_(markers)))
        await db.commit()


def _marker() -> str:
    return f"9999_alior_reversed_{uuid.uuid4().hex[:8]}"


async def test_deletes_reversed_duplicate_and_keeps_the_correct_order():
    target, ids = await _seed()
    marker = _marker()
    try:
        async with AsyncSessionLocal() as db:
            summary, po_paths = await run_alior_reversed_order_repair(
                db, targets=(target,), marker=marker
            )
            await db.commit()
        assert summary["deleted_order_ids"] == [target.order_id]
        assert summary["skipped"] == []
        assert po_paths == []
        assert "Testowa" not in str(summary)
        assert "deleted orders" in summarize_for_log(summary)

        async with AsyncSessionLocal() as db:
            assert await db.get(ClientOrder, target.order_id) is None
            kept = await db.get(ClientOrder, target.keep_order_id)
            assert kept.status == ClientOrderStatus.active
            steps = (
                await db.scalars(
                    select(ContractClientRate.effective_from).where(
                        ContractClientRate.contract_id == target.contract_id
                    )
                )
            ).all()
            assert BAD_START not in steps
            assert KEEP_START in steps
            event = await db.scalar(
                select(CriticalEvent).where(
                    CriticalEvent.entity_type == "order",
                    CriticalEvent.entity_id == target.order_id,
                )
            )
            assert event is not None
            assert event.event_type == "order.delete"

        async with AsyncSessionLocal() as db:
            again, paths = await run_alior_reversed_order_repair(
                db, targets=(target,), marker=marker
            )
        assert again is None and paths == []
    finally:
        await _cleanup(ids, marker)


async def test_edited_or_changed_order_is_left_untouched():
    target, ids = await _seed()
    markers = [_marker(), _marker()]
    try:
        # Zmienione daty w celu = stan produkcji inny niż w zgłoszeniu.
        async with AsyncSessionLocal() as db:
            summary, _ = await run_alior_reversed_order_repair(
                db,
                targets=(replace(target, start_date=date(2034, 2, 1)),),
                marker=markers[0],
            )
            await db.commit()
        assert summary["skipped"] == [
            {"order_id": target.order_id, "reason": "order_changed"}
        ]

        # Ktoś edytował zamówienie po założeniu — decyzja należy do człowieka.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ClientOrder)
                .where(ClientOrder.id == target.order_id)
                .values(notes="poprawione ręcznie")
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            summary, _ = await run_alior_reversed_order_repair(
                db, targets=(target,), marker=markers[1]
            )
            await db.commit()
        assert summary["skipped"] == [
            {"order_id": target.order_id, "reason": "edited_after_creation"}
        ]
        async with AsyncSessionLocal() as db:
            assert await db.get(ClientOrder, target.order_id) is not None
    finally:
        await _cleanup(ids, *markers)


async def test_without_the_correct_order_nothing_is_deleted():
    target, ids = await _seed()
    marker = _marker()
    try:
        async with AsyncSessionLocal() as db:
            summary, _ = await run_alior_reversed_order_repair(
                db,
                targets=(replace(target, keep_end_date=date(2033, 11, 30)),),
                marker=marker,
            )
            await db.commit()
        assert summary["skipped"] == [
            {"order_id": target.order_id, "reason": "correct_order_missing"}
        ]
        async with AsyncSessionLocal() as db:
            assert await db.get(ClientOrder, target.order_id) is not None
    finally:
        await _cleanup(ids, marker)
