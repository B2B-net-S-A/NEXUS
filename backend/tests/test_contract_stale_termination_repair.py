"""Jednorazowe czyszczenie cofniętych zakończeń (decyzja Artura 02.11.2026).

Każdy test seeduje WŁASNE wiersze i podaje własne trójki oraz własny marker,
bo baza jest wspólna, a prawdziwe ID z ``TARGETS`` nie istnieją w testach.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    ContractType,
)
from app.services.contract_stale_termination_repair import (
    REPAIR_MARKER,
    TARGETS,
    Target,
    run_stale_termination_repair,
    summarize_for_log,
)

ENTRYPOINT = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()
TERMINATED = date(2026, 8, 31)


async def _seed(
    *,
    status: ContractStatus = ContractStatus.active,
    end_date: date | None = None,
    terminated_at: date = TERMINATED,
) -> Target:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Powrot",
            lastname=f"Wsp-{uuid.uuid4().hex[:6]}",
            email=f"powrot-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"KlientPowrot-{uuid.uuid4().hex[:6]}")
        db.add_all([candidate, client])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=status,
            contract_type=ContractType.b2b,
            start_date=business_today() - timedelta(days=200),
            end_date=end_date,
            terminated_at=terminated_at,
            termination_reason=ContractTerminationReason.project_ended,
            termination_lessons="Klient — koniec projektu",
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(contract)
        await db.commit()
        return Target(contract.id, candidate.id, client.id, terminated_at, end_date)


async def _run(*targets: Target, marker: str | None = None) -> dict | None:
    async with AsyncSessionLocal() as db:
        summary = await run_stale_termination_repair(
            db,
            targets=targets,
            marker=marker or f"test_stale_termination_{uuid.uuid4().hex[:8]}",
        )
        await db.commit()
        return summary


async def _contract(contract_id: int) -> Contract:
    async with AsyncSessionLocal() as db:
        return await db.get(Contract, contract_id)


def test_targets_are_the_seven_contracts_from_the_decision():
    assert [t.contract_id for t in TARGETS] == [408, 498, 523, 527, 535, 552, 557]
    assert [t.contract_id for t in TARGETS if t.end_date is not None] == [523, 535]
    assert 'startup_phase "repair-stale-termination"' in ENTRYPOINT
    assert "run_stale_termination_repair" in ENTRYPOINT


async def test_clears_termination_and_end_date_and_keeps_values_in_history():
    indefinite = await _seed()
    dated = await _seed(end_date=date(2026, 12, 31))

    summary = await _run(indefinite, dated)

    assert summary["cleared"] == 2
    assert summary["results"][0]["end_date_cleared"] is False
    assert summary["results"][1]["end_date_cleared"] is True
    for target in (indefinite, dated):
        contract = await _contract(target.contract_id)
        assert contract.status == ContractStatus.active
        assert contract.end_date is None
        assert contract.terminated_at is None
        assert contract.termination_reason is None
        assert contract.termination_lessons is None
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(Activity.details).where(
                Activity.entity_type == "contract",
                Activity.entity_id == dated.contract_id,
                Activity.action == "termination_data_cleared",
            )
        )
    assert details == {
        "source": REPAIR_MARKER,
        "terminated_at": TERMINATED.isoformat(),
        "termination_reason": "project_ended",
        "termination_lessons": "Klient — koniec projektu",
        "end_date": "2026-12-31",
    }


async def test_other_state_than_in_the_decision_is_skipped_untouched():
    wrong_person = await _seed()
    ended = await _seed(status=ContractStatus.ended, end_date=TERMINATED)
    other_date = await _seed(terminated_at=date(2026, 9, 15))
    other_end = await _seed(end_date=date(2027, 3, 31))

    summary = await _run(
        wrong_person._replace(candidate_id=wrong_person.candidate_id + 1),
        Target(
            ended.contract_id, ended.candidate_id, ended.client_id, TERMINATED, None
        ),
        other_date._replace(terminated_at=TERMINATED),
        other_end._replace(end_date=date(2026, 12, 31)),
        Target(2_000_000_000, 1, 1, TERMINATED, None),
    )

    assert summary["cleared"] == 0
    assert [r["skipped"] for r in summary["results"]] == [
        "identity_mismatch",
        "not_active",
        "state_changed",
        "state_changed",
        "contract_missing",
    ]
    for target, expected in (
        (wrong_person, TERMINATED),
        (ended, TERMINATED),
        (other_date, date(2026, 9, 15)),
        (other_end, TERMINATED),
    ):
        contract = await _contract(target.contract_id)
        assert contract.terminated_at == expected
        assert contract.termination_reason == ContractTerminationReason.project_ended
    assert (await _contract(other_end.contract_id)).end_date == date(2027, 3, 31)
    assert "skipped" in summarize_for_log(summary)


async def test_runs_once_and_receipt_has_no_lessons():
    target = await _seed()
    marker = f"test_stale_termination_{uuid.uuid4().hex[:8]}"

    first = await _run(target, marker=marker)
    second = await _run(target, marker=marker)

    assert first["cleared"] == 1
    assert second is None
    assert summarize_for_log(second) == "already applied"
    async with AsyncSessionLocal() as db:
        receipt = (await db.get(AppSetting, marker)).value
        cleared_entries = await db.scalars(
            select(Activity.id).where(
                Activity.entity_type == "contract",
                Activity.entity_id == target.contract_id,
                Activity.action == "termination_data_cleared",
            )
        )
        assert len(list(cleared_entries)) == 1
    assert "Klient" not in str(receipt)
