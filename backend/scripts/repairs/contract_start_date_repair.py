"""Jednorazowa korekta dat rozpoczęcia umów (zgłoszenie 21.09.2026).

Dział przysłał arkusz z poprawnymi datami rozpoczęcia umów. Diagnoza
(21.09.2026, produkcja tylko do odczytu):

- 291 z 475 kontraktów miało inną datę niż arkusz, najczęściej datę startu
  ZAMÓWIENIA zamiast umowy (Nordea masowo 2026-07-01, BNP 2026-01-02).
- W 30 dziennych zrzutach bazy (23.08–21.09) ``start_date`` zmieniło się
  w 11 kontraktach i każda zmiana szła W STRONĘ arkusza — żaden automat nie
  nadpisywał tej daty. Błędne wartości pochodzą z masowego importu rejestrów
  kontraktów 23–26.06.2026.

Korekta jest przypięta do stanu z 21.09: kontrakt zmienia się tylko wtedy,
gdy kandydat, klient i BIEŻĄCA data zgadzają się z migawką. Świeższa zmiana
człowieka wygrywa (kod ``edited_since_snapshot``). Kontrakt, który ma już
poprawną datę, liczy się jako ``already_ok``.

Profil klienta („Start date") czyta ``contracts.start_date`` wprost, więc
poprawia się razem z kontraktem.

Paragon pod kluczem ``REPAIR_MARKER`` niesie wyłącznie liczniki, ID i daty.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.contract_start_date_corrections import (
    CORRECTIONS,
    SKIPPED_WITHOUT_DATE,
    CorrectionRow,
)
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.contract import Contract

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0334_contract_start_date_correction"
SOURCE = REPAIR_MARKER


def _parse(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


async def _apply_one(db: AsyncSession, row: CorrectionRow) -> dict[str, Any]:
    contract_id, candidate_id, client_id, snapshot, correct = row
    expected = _parse(snapshot)
    target = date.fromisoformat(correct)
    result: dict[str, Any] = {"contract_id": contract_id, "skipped": None}

    contract = await db.scalar(
        select(Contract).where(Contract.id == contract_id).with_for_update()
    )
    if contract is None:
        result["skipped"] = "contract_missing"
    elif contract.candidate_id != candidate_id or contract.client_id != client_id:
        result["skipped"] = "identity_mismatch"
    elif contract.start_date == target:
        result["skipped"] = "already_ok"
    elif contract.start_date != expected:
        result["skipped"] = "edited_since_snapshot"
    if result["skipped"] is not None:
        return result

    contract.start_date = target
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="start_date_corrected",
            user_id=None,
            details={
                "source": SOURCE,
                "previous_start_date": expected.isoformat() if expected else None,
                "start_date": target.isoformat(),
            },
        )
    )
    result.update(
        {
            "before": expected.isoformat() if expected else None,
            "after": target.isoformat(),
        }
    )
    return result


async def run_contract_start_date_repair(
    db: AsyncSession,
    *,
    corrections: Iterable[CorrectionRow] = CORRECTIONS,
    marker: str = REPAIR_MARKER,
) -> Optional[dict[str, Any]]:
    """Zastosuj korekty; ``None`` = już wykonane. Wołający commituje."""
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None

    rows = list(corrections)
    results = [await _apply_one(db, row) for row in rows]
    await db.flush()

    applied = [r for r in results if r["skipped"] is None]
    skipped: dict[str, list[int]] = {}
    for r in results:
        if r["skipped"] is not None:
            skipped.setdefault(r["skipped"], []).append(r["contract_id"])
    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(rows),
        "applied": len(applied),
        "skipped": skipped,
        "skipped_without_date": list(SKIPPED_WITHOUT_DATE),
        "changes": [
            {
                "contract_id": r["contract_id"],
                "before": r["before"],
                "after": r["after"],
            }
            for r in applied
        ],
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("contract start-date repair: applied %s/%s", len(applied), len(rows))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    skipped = ", ".join(f"{k}={len(v)}" for k, v in summary["skipped"].items())
    return f"applied {summary['applied']}/{summary['requested']}" + (
        f" (skipped: {skipped})" if skipped else ""
    )
