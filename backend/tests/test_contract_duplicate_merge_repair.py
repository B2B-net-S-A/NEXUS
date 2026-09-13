"""Jednorazowe scalenie duplikatu kontraktu (``contract_duplicate_merge_repair``).

Korekta jest WYKONYWANA na bazie testowej — literówka w SQL-u wyszłaby
dopiero na produkcji, a entrypoint połknąłby ją (``|| echo skipped``).
Scenariusz odtwarza UKŁAD zgłoszenia: drugi rekord osoby o tym samym
nazwisku, kontrakt założony z maila zamówień ze szkicem zamówienia i krokiem
przychodu z tego zamówienia, kontrakt zachowany ze stawką kosztową. Osoby,
kwoty i numery są zmyślone (repo jest publiczne), a marker jest własny —
baza testowa jest współdzielona.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate
from app.models.contract_document import ContractDocument
from app.models.critical_event import CriticalEvent
from app.models.order_mail import OrderMailDocument
from app.services.contract_duplicate_merge_repair import (
    DETAILS_KEY,
    REPAIR_MARKER,
    TICKET_MERGES,
    DuplicateContractMerge,
    run_contract_duplicate_merge_repair,
    summarize_for_log,
)

TODAY = business_today()


def test_ticket_pins_exactly_one_same_client_pair_by_ids():
    from scripts.show_migration_receipts import is_receipt_key

    assert len(TICKET_MERGES) == 1
    spec = TICKET_MERGES[0]
    assert spec.keep_contract_id != spec.delete_contract_id
    assert spec.keep_candidate_id != spec.delete_candidate_id
    assert is_receipt_key(REPAIR_MARKER)
    # Migawka duplikatu nie może trafić do publicznego logu paragonów.
    assert not is_receipt_key(DETAILS_KEY)


async def _seed(
    *,
    duplicate_manual_cost_step: bool = False,
    keep_rate_client: str = "110.000",
) -> dict[str, int]:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Duplikat kontraktu {suffix}")
        keep_person = Candidate(
            name="(projekt dodatkowy) Jan",
            lastname=f"Testowy{suffix}",
            email=f"keep-{suffix}@example.test",
        )
        duplicate_person = Candidate(
            name="Jan", lastname=f"Testowy{suffix}", email=f"dup-{suffix}@example.test"
        )
        db.add_all([client, keep_person, duplicate_person])
        await db.flush()
        keep = Contract(
            candidate_id=keep_person.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=TODAY - timedelta(days=40),
            rate_candidate=Decimal("90.000"),
            rate_client=Decimal(keep_rate_client),
            margin=Decimal(keep_rate_client) - Decimal("90.000"),
        )
        duplicate = Contract(
            candidate_id=duplicate_person.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=TODAY - timedelta(days=8),
            client_order_start_date=TODAY - timedelta(days=8),
            client_order_end_date=TODAY + timedelta(days=60),
            rate_client=Decimal("110.000"),
            project_name=f"Projekt {suffix}",
        )
        db.add_all([keep, duplicate])
        await db.flush()
        old_order = ClientOrder(
            client_id=client.id,
            contract_id=keep.id,
            title=f"Umowa {suffix}",
            status=ClientOrderStatus.completed,
            start_date=TODAY - timedelta(days=40),
            end_date=TODAY - timedelta(days=9),
            rate_client=Decimal("110.000"),
        )
        mail_order = ClientOrder(
            client_id=client.id,
            contract_id=duplicate.id,
            title=f"Zlecenie {suffix}",
            status=ClientOrderStatus.draft,
            start_date=TODAY - timedelta(days=8),
            end_date=TODAY + timedelta(days=80),
            rate_client=Decimal("110.000"),
            notes="Zamówienie z maila",
        )
        db.add_all([old_order, mail_order])
        await db.flush()
        db.add_all(
            [
                ContractClientRate(
                    contract_id=duplicate.id,
                    rate=Decimal("110.000"),
                    effective_from=TODAY - timedelta(days=8),
                    source_order_id=mail_order.id,
                    note="Z zamówienia klienta",
                ),
                ContractDocument(
                    contract_id=duplicate.id,
                    filename="zlecenie.pdf",
                    file_path=f"contracts/{suffix}/zlecenie.pdf",
                ),
                OrderMailDocument(
                    internet_message_id=f"<{uuid.uuid4()}@merge.test>",
                    client_id=client.id,
                    outcome="auto_applied",
                    gate_verdict="auto",
                    applied_order_id=mail_order.id,
                ),
                Activity(
                    entity_type="contract",
                    entity_id=duplicate.id,
                    action="auto_drafted_from_order_mail",
                    details={"document_id": 1},
                ),
            ]
        )
        if duplicate_manual_cost_step:
            db.add(
                ContractCandidateRate(
                    contract_id=duplicate.id,
                    rate=Decimal("70.000"),
                    effective_from=TODAY - timedelta(days=8),
                )
            )
        await db.commit()
        return {
            "client_id": client.id,
            "keep_id": keep.id,
            "keep_candidate_id": keep_person.id,
            "duplicate_id": duplicate.id,
            "duplicate_candidate_id": duplicate_person.id,
            "mail_order_id": mail_order.id,
            "old_order_id": old_order.id,
        }


def _spec(ids: dict[str, int], **over: int) -> DuplicateContractMerge:
    values = {
        "keep_contract_id": ids["keep_id"],
        "keep_candidate_id": ids["keep_candidate_id"],
        "delete_contract_id": ids["duplicate_id"],
        "delete_candidate_id": ids["duplicate_candidate_id"],
        "client_id": ids["client_id"],
        **over,
    }
    return DuplicateContractMerge(**values)


def _keys() -> tuple[str, str]:
    tag = uuid.uuid4().hex[:8]
    return f"9999_contract_duplicate_merge_{tag}", f"repair_details_test_{tag}"


async def _drop(*keys: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSetting).where(AppSetting.key.in_(keys)))
        await db.commit()


async def test_repair_merges_the_duplicate_into_the_kept_contract():
    ids = await _seed()
    marker, details_key = _keys()
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_contract_duplicate_merge_repair(
                db, merges=(_spec(ids),), marker=marker, details_key=details_key
            )
            await db.commit()
        assert summary is not None
        assert summary["merges_applied"] == 1, summary
        assert summarize_for_log(summary) == "merged 1/1"

        async with AsyncSessionLocal() as db:
            again = await run_contract_duplicate_merge_repair(
                db, merges=(_spec(ids),), marker=marker, details_key=details_key
            )
        assert again is None, "drugi start nie może niczego powtórzyć"

        async with AsyncSessionLocal() as db:
            # Duplikat usunięty trwale — wiersza nie ma.
            assert await db.get(Contract, ids["duplicate_id"]) is None
            keep = await db.get(Contract, ids["keep_id"])
            await db.refresh(keep)
            # Pola już uzupełnione zostają bez zmian.
            assert keep.rate_candidate == Decimal("90.000")
            assert keep.start_date == TODAY - timedelta(days=40)
            assert keep.status == ContractStatus.active
            assert keep.end_date is None
            # Puste pola uzupełnione danymi duplikatu.
            assert keep.project_name.startswith("Projekt ")
            assert keep.client_order_start_date == TODAY - timedelta(days=8)
            # Okres zamówienia liczy synchronizacja z najnowszego zamówienia
            # (duplikat niósł nieaktualny koniec) — dowód, że resync zaszedł.
            assert keep.client_order_end_date == TODAY + timedelta(days=80)

            orders = (
                await db.scalars(
                    select(ClientOrder).where(ClientOrder.contract_id == ids["keep_id"])
                )
            ).all()
            assert {order.id for order in orders} == {
                ids["old_order_id"],
                ids["mail_order_id"],
            }
            mail_order = await db.get(ClientOrder, ids["mail_order_id"])
            # Szkic wisiał na złym kontrakcie; na kontrakcie zachowanym przechodzi
            # bramkę zamówień z maila i dostaje koszt z kontraktu.
            assert mail_order.status == ClientOrderStatus.active
            assert mail_order.rate_candidate == Decimal("90.000")

            steps = (
                await db.execute(
                    text(
                        "SELECT contract_id, source_order_id FROM contract_client_rates "
                        "WHERE source_order_id = :o"
                    ),
                    {"o": ids["mail_order_id"]},
                )
            ).all()
            assert [tuple(row) for row in steps] == [
                (ids["keep_id"], ids["mail_order_id"])
            ]
            documents = (
                await db.scalars(
                    select(ContractDocument.contract_id).where(
                        ContractDocument.file_path.like("contracts/%/zlecenie.pdf"),
                        ContractDocument.contract_id.in_(
                            [ids["keep_id"], ids["duplicate_id"]]
                        ),
                    )
                )
            ).all()
            assert documents == [ids["keep_id"]]

            history = (
                await db.scalars(
                    select(Activity).where(
                        Activity.entity_type == "contract",
                        Activity.entity_id == ids["keep_id"],
                    )
                )
            ).all()
            actions = {row.action for row in history}
            assert "auto_drafted_from_order_mail" in actions
            merged = next(row for row in history if row.action == "contracts_merged")
            assert merged.details["deleted_contract_ids"] == [ids["duplicate_id"]]
            assert merged.details["reparented"]["client_orders"] == 1
            assert merged.details["reparented"]["contract_documents"] == 1
            assert merged.created_at is not None

            event = await db.scalar(
                select(CriticalEvent).where(
                    CriticalEvent.event_type == "contract.delete",
                    CriticalEvent.entity_id == ids["duplicate_id"],
                )
            )
            assert event is not None
            assert event.outcome == "executed"
            assert event.client_id == ids["client_id"]
            assert event.details["merged_into_contract_id"] == ids["keep_id"]

            # Drugi rekord osoby zostaje — zgłoszenie dotyczy kontraktów.
            assert await db.get(Candidate, ids["duplicate_candidate_id"]) is not None

            receipt = (await db.get(AppSetting, marker)).value
            details = (await db.get(AppSetting, details_key)).value
        assert "Testowy" not in str(receipt)
        assert "Projekt" not in str(receipt)
        assert details["merged"][0]["delete_snapshot"]["id"] == ids["duplicate_id"]
    finally:
        await _drop(marker, details_key)


@pytest.mark.parametrize(
    ("seed_kwargs", "spec_over", "reason"),
    [
        ({}, {"delete_candidate_id": 1}, "identity_mismatch"),
        (
            {"duplicate_manual_cost_step": True},
            {},
            "rate_schedule_conflict_candidate",
        ),
        ({"keep_rate_client": "120.000"}, {}, "client_rate_baseline_conflict"),
    ],
)
async def test_repair_leaves_both_contracts_untouched_when_not_safe(
    seed_kwargs, spec_over, reason
):
    ids = await _seed(**seed_kwargs)
    marker, details_key = _keys()
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_contract_duplicate_merge_repair(
                db,
                merges=(_spec(ids, **spec_over),),
                marker=marker,
                details_key=details_key,
            )
            await db.commit()
        assert summary["merges_applied"] == 0
        assert summary["merges_skipped"] == [
            {"delete_contract_id": ids["duplicate_id"], "reason": reason}
        ]
        async with AsyncSessionLocal() as db:
            assert await db.get(Contract, ids["duplicate_id"]) is not None
            mail_order = await db.get(ClientOrder, ids["mail_order_id"])
            assert mail_order.contract_id == ids["duplicate_id"]
            assert mail_order.status == ClientOrderStatus.draft
    finally:
        await _drop(marker, details_key)


async def test_failure_mid_merge_rolls_everything_back(monkeypatch):
    from app.services import contract_duplicate_merge_repair as repair

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("forced")

    monkeypatch.setattr(repair, "_assert_no_fk_rows", _boom)
    ids = await _seed()
    marker, details_key = _keys()
    try:
        async with AsyncSessionLocal() as db:
            with pytest.raises(RuntimeError):
                await run_contract_duplicate_merge_repair(
                    db, merges=(_spec(ids),), marker=marker, details_key=details_key
                )
            await db.rollback()
        async with AsyncSessionLocal() as db:
            assert await db.get(AppSetting, marker) is None
            assert await db.get(Contract, ids["duplicate_id"]) is not None
            mail_order = await db.get(ClientOrder, ids["mail_order_id"])
            assert mail_order.contract_id == ids["duplicate_id"]
    finally:
        await _drop(marker, details_key)


def test_entrypoint_runs_the_merge_and_logs_only_the_summary():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text(
        encoding="utf-8"
    )
    block = source.split("run_contract_duplicate_merge_repair", 1)[1].split(
        "\nPY\n", 1
    )[0]
    assert "summarize_for_log(summary)" in block
    assert "await db.commit()" in block
    assert "await db.rollback()" in block
