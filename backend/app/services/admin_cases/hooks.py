"""Haki spraw administracja@ dla innych modułów (wpina je koordynator).

* ``open_case_for_new_contract`` — nowy kontrakt konsultanta zakłada sprawę
  „Wejście konsultanta: …” (obszar onboarding). W Compassie to samo robił
  import placementu, a sprawa miała konsultanta tylko jako pole tekstowe —
  tu jest spięta z kontraktem.
* ``open_case_for_offboarding`` — odejście pracownika (moduł cyklu życia)
  zakłada sprawę „Odejście: …” (obszar offboarding), jak w Compassie
  ``inbox_offboarding`` przy starcie offboardingu.

Oba są idempotentne po ``source_key`` (powtórne wywołanie oddaje tę samą
sprawę) i nie commitują — robi to wołający razem ze swoją zmianą. Przy
wyłączonym module „cases” nic nie zakładają i zwracają ``None``: do
przełączenia sprawy prowadzi Compass, a ciemna tablica zbierałaby duplikaty.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.admin_case import AdminCase
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.admin_cases.queries import CANDIDATE_FULL_NAME
from app.services.admin_cases.service import (
    AutomaticCase,
    module_enabled,
    open_automatic_case,
)


def contract_source_key(contract_id: int) -> str:
    return f"contract:{contract_id}:start"


def offboarding_source_key(user_id: int, lifecycle_case_id: Optional[int]) -> str:
    if lifecycle_case_id is not None:
        return f"lifecycle:{lifecycle_case_id}:offboarding"
    return f"lifecycle:user:{user_id}:offboarding"


async def open_case_for_new_contract(
    db: AsyncSession, contract: Contract
) -> Optional[AdminCase]:
    """Sprawa wejścia konsultanta; termin = dzień startu, gdy jest przed nami."""

    if not await module_enabled(db):
        return None

    candidate_name = None
    if contract.candidate_id is not None:
        candidate_name = await db.scalar(
            select(CANDIDATE_FULL_NAME).where(Candidate.id == contract.candidate_id)
        )
    client_name = await db.scalar(
        select(Client.name).where(Client.id == contract.client_id)
    )
    who = candidate_name or f"kontrakt #{contract.id}"
    title = f"Wejście konsultanta: {who}"
    if client_name:
        title = f"{title} · {client_name}"
    start = contract.start_date
    case, _created = await open_automatic_case(
        db,
        AutomaticCase(
            title=title,
            area="onboarding",
            priority="P2",
            source="contract",
            source_key=contract_source_key(contract.id),
            due_on=start if start is not None and start >= business_today() else None,
            description=(
                f"Start u klienta {start.strftime('%d.%m.%Y')}." if start else None
            ),
            contract_id=contract.id,
        ),
    )
    return case


async def open_case_for_offboarding(
    db: AsyncSession, user_id: int, lifecycle_case_id: Optional[int]
) -> Optional[AdminCase]:
    """Sprawa odejścia pracownika; termin = ostatni dzień pracy z kartoteki."""

    if not await module_enabled(db):
        return None

    name = await db.scalar(select(User.name).where(User.id == user_id))
    last_day = await db.scalar(
        select(EmployeeProfile.last_working_day).where(
            EmployeeProfile.user_id == user_id
        )
    )
    case, _created = await open_automatic_case(
        db,
        AutomaticCase(
            title=f"Odejście: {name or f'konto #{user_id}'}",
            area="offboarding",
            priority="P2",
            source="lifecycle",
            source_key=offboarding_source_key(user_id, lifecycle_case_id),
            due_on=(
                last_day
                if last_day is not None and last_day >= business_today()
                else None
            ),
            description=(
                f"Ostatni dzień pracy {last_day.strftime('%d.%m.%Y')}."
                if last_day
                else None
            ),
            subject_user_id=user_id,
            lifecycle_case_id=lifecycle_case_id,
        ),
    )
    return case
