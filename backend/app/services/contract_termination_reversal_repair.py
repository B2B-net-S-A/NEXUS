"""Jednorazowe „Cofnij zakończenie" ze zgłoszenia 23.09.2026.

Kontrakt zakończono przez pomyłkę z datą 31.08.2026 i po kilkudziesięciu
sekundach przywrócono zmianą statusu — która nie przenosi się na zamówienia.
Linia zamówienia MD została w „Zakończonych" ze sprawą „Wymagana decyzja
o pozostałej puli MD". Korekta wykonuje dokładnie tę samą operację co przycisk
„Cofnij zakończenie" (``execute_reversal``); datę końca przypisania bierze
z historii zmian przypisania (``order_change_events``), a gdy jej brak —
z daty końca zamówienia.

Przypięta do trójki (kontrakt, kandydat, klient) — bez nazwisk w repo.
Niezgodna trójka, brak zakończenia do cofnięcia albo blokada (np. ktoś podjął
już decyzję o puli MD) = pominięcie z kodem powodu. Paragon pod kluczem
``REPAIR_MARKER``: liczniki i ID.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.app_setting import AppSetting
from app.models.contract import Contract
from app.services.contract_termination_reversal import (
    ReversalBlocked,
    ReversalUnavailable,
    execute_reversal,
)

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0355_termination_reversal_ticket_2026_09_23"

# (kontrakt, kandydat, klient) — zgłoszenie 23.09.2026.
TARGETS: tuple[tuple[int, int, int], ...] = ((408, 65586, 115),)


async def _reverse_one(
    db: AsyncSession, contract_id: int, candidate_id: int, client_id: int
) -> dict[str, Any]:
    result: dict[str, Any] = {"contract_id": contract_id, "skipped": None}
    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
        .with_for_update()
    )
    if contract is None:
        result["skipped"] = "contract_missing"
        return result
    if contract.candidate_id != candidate_id or contract.client_id != client_id:
        result["skipped"] = "identity_mismatch"
        return result
    try:
        plan = await execute_reversal(db, contract, actor_id=None)
    except ReversalUnavailable:
        result["skipped"] = "nothing_to_reverse"
        return result
    except ReversalBlocked as exc:
        result["skipped"] = "blocked"
        result["blockers"] = [b.get("code") for b in exc.plan.blockers]
        return result
    result.update(
        {
            "restored_order_ids": [item.order_id for item in plan.orders],
            "skipped_order_ids": [item["order_id"] for item in plan.skipped],
            "decision_cases_removed": list(plan.pending_case_ids),
            "md_import_rows": len(plan.md_imports),
        }
    )
    return result


async def run_termination_reversal_repair(
    db: AsyncSession,
    *,
    targets: Iterable[tuple[int, int, int]] = TARGETS,
    marker: str = REPAIR_MARKER,
) -> Optional[dict[str, Any]]:
    """Wykonaj korektę; ``None`` = już wykonana. Wołający commituje
    (``commit_order_write`` — synchronizacja kontrakt ↔ zamówienia)."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    rows = list(targets)
    results = [await _reverse_one(db, *row) for row in rows]
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(rows),
        "reversed": sum(1 for r in results if r["skipped"] is None),
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("termination reversal repair: %s/%s", summary["reversed"], len(rows))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    skipped = [
        f"{r['contract_id']}:{r['skipped']}"
        for r in summary["results"]
        if r["skipped"] is not None
    ]
    return f"reversed {summary['reversed']}/{summary['requested']}" + (
        f"; skipped {', '.join(skipped)}" if skipped else ""
    )
