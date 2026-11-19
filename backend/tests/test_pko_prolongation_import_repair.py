"""„Nieznany” zamiast „Nie” w prolongacie kontraktów PKO BP z importu z 26.06.2026.

Import z Excela zapisał uwagę „brak nowego zamówienia” jako prognozę
``prolongation_status = 'no'``, a zakładka Klient › Konsultanci pokazała ją
dwunastu obecnym konsultantom jak decyzję o nieprzedłużeniu. Naprawa zeruje
tylko wartości z importu. Prolongatę zapisaną po imporcie traktuje jako decyzję
człowieka i jej nie rusza.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.user import UserRole
from tests._jarvis_helpers import make_user

pytestmark = pytest.mark.asyncio


async def _seed_contract(prolongation: str = "no") -> dict[str, int]:
    """Kontrakt jak z importu: aktywny, stawki godzinowe, sam wpis ``created``."""
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import (
        Contract,
        ContractStatus,
        ContractType,
        ProlongationStatus,
        RateUnit,
    )

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Prolongata Import {unique}")
        candidate = Candidate(
            name="Prolongata",
            lastname=f"Osoba{unique}",
            email=f"prolongation-import-{unique}@example.com",
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=date(2026, 3, 2),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_client=Decimal("143.75"),
            rate_candidate=Decimal("120"),
            prolongation_status=ProlongationStatus(prolongation),
        )
        db.add(contract)
        await db.flush()
        db.add(
            Activity(
                entity_type="contract",
                entity_id=contract.id,
                action="created",
                user_id=None,
            )
        )
        await db.commit()
        return {
            "contract_id": contract.id,
            "candidate_id": candidate.id,
            "client_id": client.id,
        }


async def _contract(contract_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        return await db.get(Contract, contract_id)


async def test_targets_are_the_fourteen_import_contracts_of_pko_bp():
    from app.services.pko_prolongation_import_repair import PKO_BP_CLIENT_ID, TARGETS

    assert PKO_BP_CLIENT_ID == 26
    assert [t.contract_id for t in TARGETS] == [
        444,
        446,
        447,
        448,
        449,
        452,
        453,
        454,
        455,
        456,
        457,
        458,
        459,
        460,
    ]
    assert {t.client_id for t in TARGETS} == {PKO_BP_CLIENT_ID}
    assert len({t.candidate_id for t in TARGETS}) == len(TARGETS)


async def test_repair_resets_the_import_value_and_writes_history_once():
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.app_setting import AppSetting
    from app.models.contract import ProlongationStatus
    from app.services.pko_prolongation_import_repair import (
        REPAIR_MARKER,
        Target,
        run_pko_prolongation_import_repair,
        summarize_for_log,
    )

    seed = await _seed_contract()
    before = await _contract(seed["contract_id"])
    marker = f"test_pko_prolongation_{uuid.uuid4().hex[:8]}"
    targets = (Target(**seed),)
    async with AsyncSessionLocal() as db:
        summary = await run_pko_prolongation_import_repair(
            db, targets=targets, marker=marker
        )
        await db.commit()
    assert summary["reset"] == 1
    assert summarize_for_log(summary) == "reset 1/1"

    after = await _contract(seed["contract_id"])
    assert after.prolongation_status == ProlongationStatus.unknown
    assert after.status == before.status
    assert after.margin == before.margin == Decimal("23.75")
    async with AsyncSessionLocal() as db:
        history = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == seed["contract_id"],
                    Activity.action == "updated",
                )
            )
        ).all()
    assert [(a.user_id, a.details) for a in history] == [
        (None, {"prolongation_status": "unknown", "source": REPAIR_MARKER})
    ]

    async with AsyncSessionLocal() as db:
        assert (
            await run_pko_prolongation_import_repair(db, targets=targets, marker=marker)
            is None
        )
        await db.rollback()
        assert await db.get(AppSetting, marker) is not None


async def test_repair_keeps_values_someone_set_after_the_import():
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.contract import ProlongationStatus
    from app.services.pko_prolongation_import_repair import (
        Target,
        run_pko_prolongation_import_repair,
        summarize_for_log,
    )

    admin_id, _ = await make_user(UserRole.admin)
    confirmed_no = await _seed_contract("no")
    async with AsyncSessionLocal() as db:
        db.add(
            Activity(
                entity_type="contract",
                entity_id=confirmed_no["contract_id"],
                action="updated",
                user_id=admin_id,
                details={"prolongation_status": "no"},
            )
        )
        await db.commit()
    already_yes = await _seed_contract("yes")
    other = await _seed_contract("no")

    marker = f"test_pko_prolongation_{uuid.uuid4().hex[:8]}"
    targets = (
        Target(**confirmed_no),
        Target(**already_yes),
        Target(other["contract_id"], confirmed_no["candidate_id"], other["client_id"]),
        Target(0, other["candidate_id"], other["client_id"]),
    )
    async with AsyncSessionLocal() as db:
        summary = await run_pko_prolongation_import_repair(
            db, targets=targets, marker=marker
        )
        await db.commit()
    assert summary["reset"] == 0
    assert [r["skipped"] for r in summary["results"]] == [
        "set_after_import",
        "state_changed",
        "identity_mismatch",
        "contract_missing",
    ]
    assert summarize_for_log(summary).startswith("reset 0/4; skipped ")
    assert (await _contract(confirmed_no["contract_id"])).prolongation_status == (
        ProlongationStatus.no
    )
    assert (await _contract(already_yes["contract_id"])).prolongation_status == (
        ProlongationStatus.yes
    )
    assert (await _contract(other["contract_id"])).prolongation_status == (
        ProlongationStatus.no
    )
