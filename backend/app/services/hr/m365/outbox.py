"""Kolejka operacji Microsoft Graph (``hr_m365_operations``) — tylko zapis.

``enqueue`` dokłada operację raz: ``dedupe_key`` nazywa jedną operację
logiczną (np. „ustaw autoodpowiedź dla urlopu X”), więc ponowione żądanie,
podwójne kliknięcie albo restart w trakcie zapisu nie tworzą drugiego wiersza.
Operację wykonuje (albo symuluje) pętla z kolejnego etapu.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import HrM365Operation
from app.services.hr_leave_schema import M365_OPERATION_KINDS


class UnknownOperationError(ValueError):
    pass


async def enqueue(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    dedupe_key: str,
    payload: Optional[dict[str, Any]] = None,
    leave_request_id: Optional[uuid.UUID] = None,
) -> bool:
    """Zapisuje operację w kolejce; ``False`` = taka operacja już tam była."""

    if kind not in M365_OPERATION_KINDS:
        raise UnknownOperationError(kind)
    statement = (
        insert(HrM365Operation)
        .values(
            user_id=user_id,
            leave_request_id=leave_request_id,
            kind=kind,
            dedupe_key=dedupe_key[:200],
            payload=payload or {},
        )
        .on_conflict_do_nothing(index_elements=[HrM365Operation.dedupe_key])
        .returning(HrM365Operation.id)
    )
    created = await db.scalar(statement)
    return created is not None
