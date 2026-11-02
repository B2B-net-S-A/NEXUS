"""Jednorazowe czyszczenie cofniętych zakończeń (decyzja Artura 02.11.2026).

Siedem aktywnych kontraktów niosło datę i powód zakończenia, które już nie
obowiązuje: współpraca trwa (aktywne zamówienia, zużycie MD za wrzesień,
podpisane cofnięcie wypowiedzenia). Poczta zamówień, zamiary kończących się
zamówień i karta kontraktu czytały te pola jak trwające wypowiedzenie. Dwa
z nich mają też datę końca 31.12.2026 z dawnego wskrzeszenia zamówieniem, więc
nocna zmiana statusu zakończyłaby je 01.01.2027.

Przypięta do trójki (kontrakt, kandydat, klient) i starych wartości, bez nazwisk
w repo. Inny stan niż z decyzji = pominięcie z kodem powodu. Poprzednie wartości
idą do historii kontraktu (``termination_data_cleared``), paragon pod kluczem
``REPAIR_MARKER`` niesie wyłącznie liczby i ID.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable, NamedTuple, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.contract import Contract, ContractStatus

logger = logging.getLogger(__name__)

REPAIR_MARKER = "stale_termination_cleanup_2026_11_02"


class Target(NamedTuple):
    contract_id: int
    candidate_id: int
    client_id: int
    terminated_at: date
    end_date: Optional[date]


END_OF_AUGUST = date(2026, 8, 31)
END_OF_YEAR = date(2026, 12, 31)

TARGETS: tuple[Target, ...] = (
    Target(408, 65586, 115, END_OF_AUGUST, None),
    Target(498, 19471, 11, date(2026, 6, 30), None),
    Target(523, 69651, 12, END_OF_AUGUST, END_OF_YEAR),
    Target(527, 182149, 12, END_OF_AUGUST, None),
    Target(535, 6574, 12, END_OF_AUGUST, END_OF_YEAR),
    Target(552, 78418, 12, END_OF_AUGUST, None),
    Target(557, 18021, 12, END_OF_AUGUST, None),
)


async def _clear_one(db: AsyncSession, target: Target) -> dict[str, Any]:
    result: dict[str, Any] = {"contract_id": target.contract_id, "skipped": None}
    contract = await db.scalar(
        select(Contract).where(Contract.id == target.contract_id).with_for_update()
    )
    if contract is None:
        result["skipped"] = "contract_missing"
    elif (
        contract.candidate_id != target.candidate_id
        or contract.client_id != target.client_id
    ):
        result["skipped"] = "identity_mismatch"
    elif contract.status != ContractStatus.active:
        result["skipped"] = "not_active"
    elif (
        contract.terminated_at != target.terminated_at
        or contract.end_date != target.end_date
    ):
        result["skipped"] = "state_changed"
    if result["skipped"] is not None:
        return result

    reason = contract.termination_reason
    details: dict[str, Any] = {
        "source": REPAIR_MARKER,
        "terminated_at": target.terminated_at.isoformat(),
        "termination_reason": getattr(reason, "value", reason),
        "termination_lessons": contract.termination_lessons,
    }
    if target.end_date is not None:
        details["end_date"] = target.end_date.isoformat()
    contract.terminated_at = None
    contract.termination_reason = None
    contract.termination_lessons = None
    contract.end_date = None
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="termination_data_cleared",
            user_id=None,
            details=details,
        )
    )
    result["end_date_cleared"] = target.end_date is not None
    return result


async def run_stale_termination_repair(
    db: AsyncSession,
    *,
    targets: Iterable[Target] = TARGETS,
    marker: str = REPAIR_MARKER,
) -> Optional[dict[str, Any]]:
    """Wykonaj korektę; ``None`` = już wykonana. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    rows = list(targets)
    results = [await _clear_one(db, row) for row in rows]
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(rows),
        "cleared": sum(1 for r in results if r["skipped"] is None),
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("stale termination repair: %s/%s", summary["cleared"], len(rows))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    skipped = [
        f"{r['contract_id']}:{r['skipped']}"
        for r in summary["results"]
        if r["skipped"] is not None
    ]
    return f"cleared {summary['cleared']}/{summary['requested']}" + (
        f"; skipped {', '.join(skipped)}" if skipped else ""
    )
