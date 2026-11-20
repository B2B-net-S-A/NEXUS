"""Jednorazowe sprzątanie zdublowanych i mylnych aneksów kontraktów (19.11.2026).

Trzy kontrakty miały po 2–3 identyczne aneksy z wprowadzania wstecz 29.06–10.07,
a w jednym pomyłkę wpisu poprawiano kolejnymi aneksami. Naprawa usuwa wyłącznie
cele przypięte do stanu z 19.11.2026 i tylko wtedy, gdy kwoty się nie zmieniają.

Kwoty w testach są umowne.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.services.contract_amendment_history_repair import (
    AMENDMENTS,
    STEPS,
    AmendmentTarget,
    StepTarget,
    same_rates_without,
)


@dataclass
class _Step:
    id: int
    rate: Decimal
    effective_from: date


# ── Bez bazy ────────────────────────────────────────────────────────────────


def test_targets_are_pinned_to_the_19_11_state():
    assert [(t.amendment_id, t.contract_id) for t in AMENDMENTS] == [
        (3, 155),
        (29, 155),
        (31, 116),
        (20, 444),
        (47, 398),
        (48, 398),
    ]
    assert [(t.schedule, t.step_id, t.contract_id) for t in STEPS] == [
        ("candidate", 6, 155),
        ("candidate", 17, 155),
        ("candidate", 31, 116),
        ("candidate", 197, 263),
        ("client", 22, 398),
    ]
    duplicates = [t for t in AMENDMENTS if t.duplicate_of is not None]
    assert {t.duplicate_of for t in duplicates} == {1, 7, 19}
    assert all(t.step_id != t.same_as for t in STEPS)


def test_identical_step_on_the_same_day_can_go():
    steps = [
        _Step(1, Decimal("100"), date(2026, 4, 1)),
        _Step(2, Decimal("110"), date(2026, 7, 1)),
        _Step(3, Decimal("110"), date(2026, 7, 1)),
    ]

    assert same_rates_without(steps, 3)
    assert same_rates_without(steps, 2)


def test_later_step_with_the_same_rate_can_go():
    steps = [
        _Step(1, Decimal("150"), date(2025, 8, 4)),
        _Step(2, Decimal("130"), date(2026, 7, 1)),
        _Step(3, Decimal("130"), date(2026, 7, 10)),
    ]

    assert same_rates_without(steps, 3)


def test_step_that_changes_the_rate_stays():
    steps = [
        _Step(1, Decimal("150"), date(2025, 8, 4)),
        _Step(2, Decimal("130"), date(2026, 7, 1)),
    ]

    assert not same_rates_without(steps, 2)
    # Pierwszy krok rządzi też dniami przed nim; bez niego wygrałby krok drugi.
    assert not same_rates_without(steps, 1)


def test_same_day_tie_with_another_rate_stays():
    # Remis tego samego dnia wygrywa krok dopisany później.
    steps = [
        _Step(1, Decimal("120"), date(2026, 7, 1)),
        _Step(2, Decimal("130"), date(2026, 7, 1)),
    ]

    assert not same_rates_without(steps, 2)


def test_only_step_or_unknown_step_stays():
    steps = [_Step(1, Decimal("100"), date(2026, 1, 1))]

    assert not same_rates_without(steps, 1)
    assert not same_rates_without(steps, 99)


# ── Baza (sprawdza CI) ───────────────────────────────────────────────────────


async def _seed() -> dict[str, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
    from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
    from app.models.contract_candidate_rate import ContractCandidateRate

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Historia aneksów {suffix}")
        candidate = Candidate(
            name="Historia",
            lastname=f"Osoba{suffix}",
            email=f"amendment-history-{suffix}@example.test",
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=date(2026, 4, 1),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_candidate=Decimal("110"),
            rate_client=Decimal("200"),
        )
        db.add(contract)
        await db.flush()
        values = {"rate_candidate": 110}
        old = {"rate_candidate": 100, "end_date": None}
        keeper = ContractAmendment(
            contract_id=contract.id,
            amendment_type=ContractAmendmentType.rate_change,
            effective_date=date(2026, 7, 1),
            old_values=old,
            new_values=values,
        )
        duplicate = ContractAmendment(
            contract_id=contract.id,
            amendment_type=ContractAmendmentType.rate_change,
            effective_date=date(2026, 7, 1),
            old_values=old,
            new_values=dict(values),
        )
        other = ContractAmendment(
            contract_id=contract.id,
            amendment_type=ContractAmendmentType.rate_change,
            effective_date=date(2026, 7, 1),
            old_values=old,
            new_values={"rate_candidate": 115},
        )
        shortening = ContractAmendment(
            contract_id=contract.id,
            amendment_type=ContractAmendmentType.extension,
            effective_date=date(2026, 7, 1),
            old_values={"end_date": "2026-08-31"},
            new_values={"end_date": "2026-07-31", "status": "active"},
        )
        baseline = ContractCandidateRate(
            contract_id=contract.id,
            rate=Decimal("100"),
            effective_from=date(2026, 4, 1),
        )
        step = ContractCandidateRate(
            contract_id=contract.id,
            rate=Decimal("110"),
            effective_from=date(2026, 7, 1),
        )
        twin = ContractCandidateRate(
            contract_id=contract.id,
            rate=Decimal("110"),
            effective_from=date(2026, 7, 1),
        )
        db.add_all([keeper, duplicate, other, shortening, baseline, step, twin])
        await db.commit()
        return {
            "contract_id": contract.id,
            "keeper": keeper.id,
            "duplicate": duplicate.id,
            "other": other.id,
            "shortening": shortening.id,
            "baseline": baseline.id,
            "step": step.id,
            "twin": twin.id,
        }


async def _ids(model, contract_id: int) -> set[int]:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return set(
            (
                await db.scalars(
                    select(model.id).where(model.contract_id == contract_id)
                )
            ).all()
        )


async def test_repair_removes_only_proven_duplicates_and_writes_history_once():
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.app_setting import AppSetting
    from app.models.contract_amendment import ContractAmendment
    from app.models.contract_candidate_rate import ContractCandidateRate
    from app.services.contract_amendment_history_repair import (
        ACTIVITY_ACTION,
        run_contract_amendment_history_repair,
        summarize_for_log,
    )

    seed = await _seed()
    cid = seed["contract_id"]
    marker = f"test_amendment_history_{uuid.uuid4().hex[:8]}"
    details_key = f"test_amendment_history_details_{uuid.uuid4().hex[:8]}"
    amendments = (
        AmendmentTarget(
            seed["duplicate"], cid, "rate_change", date(2026, 7, 1), seed["keeper"]
        ),
        AmendmentTarget(
            seed["other"], cid, "rate_change", date(2026, 7, 1), seed["keeper"]
        ),
        AmendmentTarget(
            seed["shortening"],
            cid,
            "extension",
            date(2026, 7, 1),
            old_end=date(2026, 8, 31),
            new_end=date(2026, 7, 31),
        ),
    )
    steps = (
        StepTarget("candidate", seed["twin"], cid, date(2026, 7, 1), seed["step"]),
        StepTarget("candidate", seed["baseline"], cid, date(2026, 4, 1), seed["step"]),
    )

    async with AsyncSessionLocal() as db:
        summary = await run_contract_amendment_history_repair(
            db,
            amendments=amendments,
            steps=steps,
            marker=marker,
            details_key=details_key,
        )
        await db.commit()

    assert summary["amendments_removed"] == 2
    assert summary["steps_removed"] == 1
    assert summarize_for_log(summary) == (
        f"amendments 2/3, steps 1/2; skipped amendment {seed['other']}:values_differ, "
        f"step candidate/{seed['baseline']}:rate_differs"
    )
    assert await _ids(ContractAmendment, cid) == {seed["keeper"], seed["other"]}
    assert await _ids(ContractCandidateRate, cid) == {seed["baseline"], seed["step"]}

    async with AsyncSessionLocal() as db:
        history = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == cid,
                    Activity.action == ACTIVITY_ACTION,
                )
            )
        ).all()
        details = await db.get(AppSetting, details_key)
    assert [(a.user_id, a.details) for a in history] == [
        (
            None,
            {
                "source": marker,
                "removed_amendment_ids": [seed["duplicate"], seed["shortening"]],
                "removed_candidate_rate_step_ids": [seed["twin"]],
            },
        )
    ]
    assert [row["amendment_id"] for row in details.value["amendments"]] == [
        seed["duplicate"],
        seed["shortening"],
    ]
    assert [row["step_id"] for row in details.value["steps"]] == [seed["twin"]]

    async with AsyncSessionLocal() as db:
        again = await run_contract_amendment_history_repair(
            db,
            amendments=amendments,
            steps=steps,
            marker=marker,
            details_key=details_key,
        )
    assert again is None
    assert summarize_for_log(again) == "already applied"


async def test_repair_skips_a_target_that_no_longer_matches():
    from app.core.database import AsyncSessionLocal
    from app.models.contract_amendment import ContractAmendment
    from app.services.contract_amendment_history_repair import (
        run_contract_amendment_history_repair,
    )

    seed = await _seed()
    cid = seed["contract_id"]
    amendments = (
        # Inny dzień niż w stanie z 19.11 → nie ten aneks.
        AmendmentTarget(
            seed["duplicate"], cid, "rate_change", date(2026, 8, 1), seed["keeper"]
        ),
        # Inna data końca niż w przypiętej poprawce.
        AmendmentTarget(
            seed["shortening"],
            cid,
            "extension",
            date(2026, 7, 1),
            old_end=date(2026, 9, 30),
            new_end=date(2026, 7, 31),
        ),
    )

    async with AsyncSessionLocal() as db:
        summary = await run_contract_amendment_history_repair(
            db,
            amendments=amendments,
            steps=(),
            marker=f"test_amendment_history_{uuid.uuid4().hex[:8]}",
            details_key=f"test_amendment_history_details_{uuid.uuid4().hex[:8]}",
        )
        await db.commit()

    assert [r["skipped"] for r in summary["amendment_results"]] == [
        "identity_mismatch",
        "values_differ",
    ]
    assert await _ids(ContractAmendment, cid) == {
        seed["keeper"],
        seed["duplicate"],
        seed["other"],
        seed["shortening"],
    }
