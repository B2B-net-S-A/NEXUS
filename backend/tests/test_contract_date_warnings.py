"""Ostrzeżenia dat kontraktu: „start przed podpisem” i „próg stawki przed startem”.

Przegląd skrzynki działu umów z 23.11.2026: umowa podpisana po starcie pracy
i próg stawki z datą sprzed startu (literówka w roku). Reguła:
``services/contract_date_warnings.py``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.contract_candidate_rate import ContractCandidateRate
from app.schemas.contract import ContractDateWarningRead
from app.services.contract_date_warnings import (
    RATE_STEP_BEFORE_START,
    START_BEFORE_SIGNATURE,
    contract_date_warnings,
    dead_steps_before_start,
)

START = date(2026, 11, 16)


# ── Reguła progu (bez bazy) ──────────────────────────────────────────────────


def test_typo_in_year_gives_a_dead_step_before_start():
    """Próg „od 01.06.2026” przy starcie 16.11.2026 nigdy nie obowiązuje."""
    steps = [(date(2026, 6, 1), 2), (START, 1)]
    assert dead_steps_before_start(START, steps) == [date(2026, 6, 1)]


def test_single_initial_step_before_start_is_fine():
    """Stawka początkowa od 1. dnia miesiąca obowiązuje od startu — bez uwagi."""
    steps = [(date(2026, 11, 1), 1), (date(2027, 6, 1), 2)]
    assert dead_steps_before_start(START, steps) == []


def test_progression_after_start_is_fine():
    steps = [(START, 1), (date(2027, 6, 1), 2), (date(2027, 12, 1), 3)]
    assert dead_steps_before_start(START, steps) == []


def test_two_steps_on_the_start_day_are_not_a_date_problem():
    """Remis w dniu startu (aneks na start) rozstrzyga kolejność dopisania."""
    assert dead_steps_before_start(START, [(START, 1), (START, 2)]) == []


def test_without_start_date_there_is_nothing_to_compare():
    assert dead_steps_before_start(None, [(date(2026, 1, 1), 1), (START, 2)]) == []


def test_warning_schema_carries_dates_only():
    read = ContractDateWarningRead(
        code="start_before_signature", start_date=START, day=date(2026, 11, 18)
    )
    assert set(read.model_dump()) == {"code", "start_date", "day"}


# ── Odczyt z bazy ────────────────────────────────────────────────────────────


async def _seed(*, signed_on: date | None, steps: list[date]) -> int:
    suffix = uuid.uuid4().hex[:8]
    seq = 100000 + (uuid.uuid4().int % 800000)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Date warnings client {suffix}")
        person = Candidate(name="Ewa", lastname=f"Daty{suffix}")
        db.add_all([client, person])
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            start_date=START,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()
        for index, day in enumerate(steps):
            db.add(
                ContractCandidateRate(
                    contract_id=contract.id,
                    rate=Decimal("100") + index,
                    effective_from=day,
                )
            )
        if signed_on is not None:
            db.add(
                B2BGeneratedContract(
                    year=2026,
                    seq=seq,
                    contract_number=f"{seq}/2026",
                    partner_name=f"Ewa Daty{suffix}",
                    client_name=client.name,
                    language="pl",
                    candidate_id=person.id,
                    client_id=client.id,
                    contract_id=contract.id,
                    signature_status="signed_both",
                    contract_status="active",
                    render_payload={"language": "pl"},
                    signed_on=signed_on,
                    signed_on_source="pdf",
                )
            )
        await db.commit()
        return contract.id


async def _warnings(contract_id: int) -> list[tuple[str, date]]:
    async with AsyncSessionLocal() as db:
        contract = await db.scalar(
            select(Contract)
            .where(Contract.id == contract_id)
            .options(selectinload(Contract.candidate_rate_schedule))
        )
        return [(w.code, w.day) for w in await contract_date_warnings(db, contract)]


@pytest.mark.asyncio
async def test_agreement_signed_after_start_is_flagged():
    contract_id = await _seed(signed_on=date(2026, 11, 18), steps=[START])
    assert await _warnings(contract_id) == [
        (START_BEFORE_SIGNATURE, date(2026, 11, 18))
    ]


@pytest.mark.asyncio
async def test_agreement_signed_before_start_is_not_flagged():
    contract_id = await _seed(signed_on=date(2026, 11, 10), steps=[START])
    assert await _warnings(contract_id) == []


@pytest.mark.asyncio
async def test_rate_step_typo_is_flagged_without_agreement_row():
    contract_id = await _seed(signed_on=None, steps=[START, date(2026, 6, 1)])
    assert await _warnings(contract_id) == [(RATE_STEP_BEFORE_START, date(2026, 6, 1))]
