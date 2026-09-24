"""Jednorazowe anulowanie zdublowanych zamówień jednoosobowych u CeZ.

Korekta jest WYKONYWANA na bazie testowej — literówka w SQL-u wyszłaby
dopiero na produkcji, a entrypoint połknąłby ją (``|| echo skipped``).
Scenariusz odtwarza układ zgłoszenia: żywy kontrakt z linią aktywnego
zamówienia grupowego MD i obok stare, samodzielne zamówienie na tym samym
kontrakcie. Osoby i numery są zmyślone, marker jest własny — baza testowa
jest współdzielona.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.critical_event import CriticalEvent
from app.services.cez_standalone_md_duplicate_repair import (
    DETAILS_KEY,
    REPAIR_MARKER,
    TICKET_DUPLICATES,
    StandaloneDuplicate,
    run_cez_standalone_md_duplicate_repair,
    summarize_for_log,
)


def test_ticket_pins_two_cez_contracts_and_public_receipt_carries_no_names():
    from scripts.show_migration_receipts import is_receipt_key

    assert {spec.contract_id for spec in TICKET_DUPLICATES} == {407, 408}
    assert {spec.client_id for spec in TICKET_DUPLICATES} == {115}
    assert is_receipt_key(REPAIR_MARKER)
    # Migawka niesie tytuły zamówień (z nazwiskami) — nie może trafić do
    # publicznego logu paragonów.
    assert not is_receipt_key(DETAILS_KEY)


async def _seed(
    *, with_group_line: bool = True, contract_status=ContractStatus.active
) -> dict:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"CeZ duplikat {suffix}")
        person = Candidate(
            name="Jan", lastname=f"Testowy{suffix}", email=f"cez-{suffix}@example.test"
        )
        db.add_all([client, person])
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=contract_status,
            start_date=business_today() - timedelta(days=60),
            rate_candidate=Decimal("75.000"),
        )
        db.add(contract)
        await db.flush()
        group_number = f"CeZ/{suffix}/2025"
        line_id = None
        if with_group_line:
            group = ClientOrderGroup(
                client_id=client.id,
                order_number=group_number,
                start_date=business_today() - timedelta(days=60),
                status=GROUP_STATUS_ACTIVE,
                order_type="md",
                md_budget_mode="per_person",
                is_md_budget_based=False,
            )
            db.add(group)
            await db.flush()
            line = ClientOrder(
                client_id=client.id,
                contract_id=contract.id,
                order_group_id=group.id,
                title=f"Zamówienie {group_number} — linia",
                order_type="md",
                status=ClientOrderStatus.active,
                start_date=business_today() - timedelta(days=60),
                md_rate_cost=Decimal("600.00"),
                md_rate_revenue=Decimal("800.00"),
                md_input_mode="md",
                md_input_value=Decimal("340"),
                md_total=Decimal("340"),
                md_remaining=Decimal("340"),
                rate_unit=RateUnit.daily,
                currency="PLN",
                rate_client_currency="PLN",
            )
            db.add(line)
            await db.flush()
            line_id = line.id
        standalone = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"Zamówienie {group_number} — stare",
            order_type="md",
            status=ClientOrderStatus.active,
            start_date=business_today() - timedelta(days=60),
            rate_client=Decimal("800.000"),
            rate_unit=RateUnit.daily,
            currency="PLN",
        )
        other_client_order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="Zamówienie historyczne",
            status=ClientOrderStatus.completed,
            start_date=business_today() - timedelta(days=200),
            end_date=business_today() - timedelta(days=61),
            rate_client=Decimal("700.000"),
        )
        db.add_all([standalone, other_client_order])
        await db.commit()
        return {
            "client_id": client.id,
            "contract_id": contract.id,
            "group_number": group_number,
            "line_id": line_id,
            "standalone_id": standalone.id,
            "completed_id": other_client_order.id,
        }


def _keys() -> tuple[str, str]:
    tag = uuid.uuid4().hex[:8]
    return f"9999_cez_standalone_md_duplicates_{tag}", f"repair_details_test_{tag}"


async def _drop(*keys: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSetting).where(AppSetting.key.in_(keys)))
        await db.commit()


def _spec(ids: dict, **over) -> StandaloneDuplicate:
    values = {
        "client_id": ids["client_id"],
        "contract_id": ids["contract_id"],
        "group_order_number": ids["group_number"],
        **over,
    }
    return StandaloneDuplicate(**values)


async def test_cancels_the_standalone_duplicate_and_keeps_the_group_line():
    ids = await _seed()
    marker, details_key = _keys()
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_cez_standalone_md_duplicate_repair(
                db, duplicates=(_spec(ids),), marker=marker, details_key=details_key
            )
            await db.commit()

        assert summary["orders_cancelled"] == 1
        assert summary["applied"][0]["cancelled_order_ids"] == [ids["standalone_id"]]
        assert summary["applied"][0]["group_line_ids"] == [ids["line_id"]]
        assert "Testowy" not in str(summary)

        async with AsyncSessionLocal() as db:
            standalone = await db.get(ClientOrder, ids["standalone_id"])
            line = await db.get(ClientOrder, ids["line_id"])
            completed = await db.get(ClientOrder, ids["completed_id"])
            contract = await db.get(Contract, ids["contract_id"])
            # Anulowane, nie skasowane — rekord zostaje w historii.
            assert standalone is not None
            assert standalone.status == ClientOrderStatus.cancelled
            assert line.status == ClientOrderStatus.active
            assert line.md_remaining == Decimal("340")
            assert completed.status == ClientOrderStatus.completed
            assert contract.status == ContractStatus.active

            activity = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "client",
                    Activity.entity_id == ids["client_id"],
                    Activity.action == "order_cancelled",
                )
            )
            assert activity is not None
            assert activity.details["order_id"] == ids["standalone_id"]
            event = await db.scalar(
                select(CriticalEvent).where(
                    CriticalEvent.entity_type == "order",
                    CriticalEvent.entity_id == ids["standalone_id"],
                )
            )
            assert event is not None
            assert event.event_type == "order.delete"
            assert event.reason_code == "duplicate_of_group_line"
            details = await db.get(AppSetting, details_key)
            assert details.value["cancelled_orders"][0]["status"] == "active"

        # Drugi start: marker już jest, nic się nie dzieje.
        async with AsyncSessionLocal() as db:
            again = await run_cez_standalone_md_duplicate_repair(
                db, duplicates=(_spec(ids),), marker=marker, details_key=details_key
            )
            await db.commit()
        assert again is None
        assert summarize_for_log(again) == "already done"
    finally:
        await _drop(marker, details_key)


async def test_without_a_live_group_line_the_only_order_is_left_alone():
    ids = await _seed(with_group_line=False)
    marker, details_key = _keys()
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_cez_standalone_md_duplicate_repair(
                db, duplicates=(_spec(ids),), marker=marker, details_key=details_key
            )
            await db.commit()
        assert summary["orders_cancelled"] == 0
        assert summary["skipped"] == [
            {"contract_id": ids["contract_id"], "reason": "no_live_group_line"}
        ]
        async with AsyncSessionLocal() as db:
            standalone = await db.get(ClientOrder, ids["standalone_id"])
            assert standalone.status == ClientOrderStatus.active
    finally:
        await _drop(marker, details_key)


async def test_mismatched_client_or_group_number_or_ended_contract_is_skipped():
    ids = await _seed()
    ended = await _seed(contract_status=ContractStatus.ended)
    marker, details_key = _keys()
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_cez_standalone_md_duplicate_repair(
                db,
                duplicates=(
                    _spec(ids, client_id=ids["client_id"] + 100000),
                    _spec(ids, group_order_number="CeZ/inny/2025"),
                    _spec(ended),
                ),
                marker=marker,
                details_key=details_key,
            )
            await db.commit()
        assert [item["reason"] for item in summary["skipped"]] == [
            "contract_client_mismatch",
            "no_live_group_line",
            "contract_not_live",
        ]
        assert "skipped" in summarize_for_log(summary)
        async with AsyncSessionLocal() as db:
            for key in (ids, ended):
                standalone = await db.get(ClientOrder, key["standalone_id"])
                assert standalone.status == ClientOrderStatus.active
    finally:
        await _drop(marker, details_key)


def test_entrypoint_runs_the_repair_and_logs_only_the_summary():
    source = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text(
        encoding="utf-8"
    )
    block = source.split("run_cez_standalone_md_duplicate_repair", 1)[1].split(
        "\nPY\n", 1
    )[0]
    assert "summarize_for_log(summary)" in block
    assert "await db.commit()" in block
    assert "await db.rollback()" in block
