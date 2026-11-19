"""Jednorazowe „Nieznany” w prolongacie kontraktów PKO BP z importu z 26.06.2026.

Zakładka Klient › Konsultanci (#3584) pokazała u PKO BP dwunastu obecnych
konsultantów z „Prolongata: Nie”. Tej prognozy nikt nie wybrał. 26.06.2026
skrypt importu z Excela „Zamówienia_PKO BP” założył kontrakty przez
``POST /api/contracts`` (17 w nieco ponad sekundę) i uwagę „brak nowego
zamówienia” z arkusza zapisał jako ``prolongation_status = 'no'``. Uwaga
znaczyła tylko, że następne zamówienie jeszcze nie przyszło. Każdy z dwunastu
ma potem zamówienie na III kwartał i kolejne na IV kwartał (01.10–31.12).
Historia tych kontraktów nie ma żadnego wpisu zmieniającego prolongatę. Ręczne
wybory u innych klientów (PFRON 10.07, Alior 15.07) taki wpis mają.

Kontrakty przypięte do trójki (kontrakt, kandydat, klient), bez nazwisk w repo,
stan produkcji z 19.11.2026: 12 obecnych i 2 zakończone z tego samego importu.
Pominięcie z kodem powodu, gdy prolongata ma już inną wartość niż „Nie” albo
gdy ktoś zapisał ją po imporcie (wpis z kluczem ``prolongation_status``
w historii kontraktu). Wtedy to decyzja człowieka i zostaje. Zmiana idzie do
historii kontraktu, paragon pod kluczem ``REPAIR_MARKER`` niesie wyłącznie
liczby i ID.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, NamedTuple, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.contract import Contract, ProlongationStatus

logger = logging.getLogger(__name__)

REPAIR_MARKER = "pko_prolongation_import_reset_2026_11_19"

PKO_BP_CLIENT_ID = 26


class Target(NamedTuple):
    contract_id: int
    candidate_id: int
    client_id: int


TARGETS: tuple[Target, ...] = (
    Target(444, 30839, PKO_BP_CLIENT_ID),
    Target(446, 20092, PKO_BP_CLIENT_ID),
    Target(447, 12699, PKO_BP_CLIENT_ID),
    Target(448, 18074, PKO_BP_CLIENT_ID),
    Target(449, 25552, PKO_BP_CLIENT_ID),
    Target(452, 65741, PKO_BP_CLIENT_ID),
    Target(453, 5450, PKO_BP_CLIENT_ID),
    Target(454, 25721, PKO_BP_CLIENT_ID),
    Target(455, 5368, PKO_BP_CLIENT_ID),
    Target(456, 25609, PKO_BP_CLIENT_ID),
    Target(457, 19610, PKO_BP_CLIENT_ID),
    Target(458, 6522, PKO_BP_CLIENT_ID),
    Target(459, 12539, PKO_BP_CLIENT_ID),
    Target(460, 66256, PKO_BP_CLIENT_ID),
)


async def _prolongation_written_after_import(
    db: AsyncSession, contract_id: int
) -> bool:
    """Czy ktoś zapisał prolongatę po założeniu (wybór w wierszu, okno rejestru)."""

    return (
        await db.scalar(
            select(Activity.id)
            .where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract_id,
                Activity.details.has_key("prolongation_status"),
            )
            .limit(1)
        )
    ) is not None


async def _reset_one(db: AsyncSession, target: Target) -> dict[str, Any]:
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
    elif contract.prolongation_status != ProlongationStatus.no:
        result["skipped"] = "state_changed"
    elif await _prolongation_written_after_import(db, contract.id):
        result["skipped"] = "set_after_import"
    if result["skipped"] is not None:
        return result

    contract.prolongation_status = ProlongationStatus.unknown
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="updated",
            user_id=None,
            details={
                "prolongation_status": ProlongationStatus.unknown.value,
                "source": REPAIR_MARKER,
            },
        )
    )
    return result


async def run_pko_prolongation_import_repair(
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
    results = [await _reset_one(db, row) for row in rows]
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(rows),
        "reset": sum(1 for r in results if r["skipped"] is None),
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("pko prolongation import repair: %s/%s", summary["reset"], len(rows))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    skipped = [
        f"{r['contract_id']}:{r['skipped']}"
        for r in summary["results"]
        if r["skipped"] is not None
    ]
    return f"reset {summary['reset']}/{summary['requested']}" + (
        f"; skipped {', '.join(skipped)}" if skipped else ""
    )
