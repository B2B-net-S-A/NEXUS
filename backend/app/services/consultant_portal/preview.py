"""Podgląd panelu oczami konsultanta dla Finansów (tryb „Tylko zespół”, 16.11.2026).

Finanse testują na produkcji, co zobaczy konsultant, zanim ktokolwiek dostanie dostęp.
Te same funkcje ekranów co panel (``panel``, ``content``, ``documents``), więc lista
dozwolonych pól jest ta sama: bez stawki klienta, marży i mnożnika. Podgląd tylko czyta:
nie zakłada sesji ani aktywacji i nie wysyła maili, a wyłącznik panelu nie gra roli.

Zadania „Do zrobienia” liczą się od poprzedniego miesiąca, jakby panel był aktywny od
jego początku: inaczej podgląd w listopadzie nie pokazałby zadań za październik.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.consultant_panel import CpActivation
from app.models.contract import Contract
from app.services.consultant_portal import content, documents, identity, panel
from app.services.consultant_portal.auth import PortalContext, PortalError

NOT_FOUND = "Nie ma takiego kontraktu."


def _previous_month(today: date) -> tuple[int, int]:
    return (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)


async def _consultant(
    db: AsyncSession, contract: Contract, today: date
) -> identity.Consultant:
    siblings = (
        (
            await db.scalars(
                select(Contract).where(Contract.candidate_id == contract.candidate_id)
            )
        ).all()
        if contract.candidate_id is not None
        else []
    )
    candidate = (
        await db.get(Candidate, contract.candidate_id)
        if contract.candidate_id
        else None
    )
    return identity.Consultant(
        contract_id=contract.id,
        email=identity.normalize_email(contract.candidate_email),
        contract_ids=tuple(
            sorted(
                {contract.id}
                | {row.id for row in siblings if identity.eligible(row, today)}
            )
        ),
        candidate_id=contract.candidate_id,
        first_name=(candidate.name.strip() or None)
        if candidate and candidate.name
        else None,
        phone=(contract.candidate_phone or "").strip() or None,
    )


async def build(
    db: AsyncSession, contract_id: int, *, today: date, now: datetime
) -> dict[str, Any]:
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise PortalError(NOT_FOUND, status=404, code="contract_not_found")
    context = PortalContext(
        session=None, consultant=await _consultant(db, contract, today)
    )
    activation = await db.scalar(
        select(CpActivation).where(
            CpActivation.contract_id == contract_id,
            CpActivation.deactivated_at.is_(None),
        )
    )
    return {
        "activated": activation is not None,
        "me": {
            **await content.overview(db, context),
            **await panel.overview_extra(db, context, today=today),
        },
        "todo": {
            "items": await panel.todo(
                db, context, today=today, now=now, since=_previous_month(today)
            )
        },
        "settlement": await panel.settlement_screen(db, context),
        "finance": {"months": await documents.overview(db, context, today=today)},
    }
