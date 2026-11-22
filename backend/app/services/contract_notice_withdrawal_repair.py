"""Jednorazowe „Wycofaj wypowiedzenie” ze zgłoszenia Finansów 17.11.2026.

Konsultant wycofał wypowiedzenie zapisane aneksem „Wcześniejsze zakończenie”
(umowa B2B skrócona do 31.10.2026). Nocny proces zakończył kontrakt 01.11
i uciął przypisanie na zamówieniu, a „Cofnij zakończenie” blokowało się na
minionej dacie. Decyzja Artura z 17.11.2026: naprawić od razu, nie czekając
na przycisk — umowa wraca bezterminowa, zamówienie do daty z migawki.

Ta sama operacja co przycisk (``withdraw_notice``), przypięta do trójki
(kontrakt, kandydat, klient) — bez nazwisk w repo. Niezgodna trójka, brak
wypowiedzenia do wycofania albo blokada = pominięcie z kodem powodu. Paragon
pod kluczem ``REPAIR_MARKER``: liczniki i ID.
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
from app.services.contract_notice_withdrawal import (
    NoticeWithdrawalError,
    withdraw_notice,
)
from app.services.contract_termination_reversal import ReversalBlocked

logger = logging.getLogger(__name__)

REPAIR_MARKER = "notice_withdrawal_ticket_2026_11_17"
REPAIR_NOTE = "Wypowiedzenie wycofane — korekta ze zgłoszenia Finansów 17.11.2026."

# (kontrakt, kandydat, klient) — zgłoszenie 17.11.2026.
TARGETS: tuple[tuple[int, int, int], ...] = ((216, 33818, 11),)


async def _withdraw_one(
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
        outcome = await withdraw_notice(
            db, contract, end_date=None, actor_id=None, note=REPAIR_NOTE
        )
    except NoticeWithdrawalError as exc:
        result["skipped"] = exc.code
        return result
    except ReversalBlocked as exc:
        result["skipped"] = "blocked"
        result["blockers"] = [b.get("code") for b in exc.plan.blockers]
        return result
    reversal = outcome.get("reversal") or {}
    result.update(
        {
            "amendment_id": outcome["amendment_id"],
            "withdrawn_amendment_id": outcome["withdrawn_amendment_id"],
            "status": outcome["status"],
            "restored_order_ids": [o["order_id"] for o in reversal.get("orders", [])],
            "skipped_order_ids": [o["order_id"] for o in reversal.get("skipped", [])],
            "md_import_rows": len(reversal.get("md_imports", [])),
        }
    )
    return result


async def run_notice_withdrawal_repair(
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
    results = [await _withdraw_one(db, *row) for row in rows]
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(rows),
        "withdrawn": sum(1 for r in results if r["skipped"] is None),
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("notice withdrawal repair: %s/%s", summary["withdrawn"], len(rows))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    skipped = [
        f"{r['contract_id']}:{r['skipped']}"
        for r in summary["results"]
        if r["skipped"] is not None
    ]
    return f"withdrawn {summary['withdrawn']}/{summary['requested']}" + (
        f"; skipped {', '.join(skipped)}" if skipped else ""
    )
