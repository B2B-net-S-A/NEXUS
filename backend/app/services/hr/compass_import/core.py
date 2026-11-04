"""Wspólny przebieg importu: partia → plan na sucho → zapis, mapa id.

* Plan (``ModulePlan``) liczy decyzję dla każdego wiersza paczki bez zapisu.
  Raport partii niesie liczby i identyfikatory źródła — imiona i kwoty nie
  trafiają ani do raportu, ani do logów.
* Zapis przelicza plan na świeżych danych (między „na sucho” a „zapisz” ktoś
  mógł coś zmienić) i wymaga tej samej paczki (``bundle_sha256`` partii).
* Mapa id (``hr_import_id_map``) czyni import idempotentnym: drugi zapis tej
  samej paczki kończy się samymi „bez zmian”. Wiersz mapy wskazuje partię,
  która ostatnio zapisała cel; ``applied_at`` partii to czas transakcji zapisu
  (``now()`` bazy, ten sam co ``updated_at`` zapisanych wierszy).
* Ponowny import nie nadpisuje zmian zrobionych w NEXUSIE: wiersz celu
  zmieniony po zapisie partii (``changed_in_nexus``) dostaje „bez zmian”
  albo „conflict”, nigdy „update”.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_ops import HrImportBatch, HrImportIdMap

from .bundle import Bundle

Action = Literal["create", "update", "unchanged", "skip", "conflict"]


class ImportFlowError(RuntimeError):
    """Partia nie może przejść do kolejnego kroku (zła paczka, zły stan)."""


@dataclass
class RowPlan:
    """Decyzja dla jednego wiersza źródła. ``apply`` wykonuje importer modułu."""

    source_id: str
    action: Action
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModulePlan:
    module: str
    rows: list[RowPlan] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return dict(Counter(row.action for row in self.rows))

    def reasons(self) -> dict[str, int]:
        return dict(Counter(row.reason for row in self.rows if row.reason))

    def report(self) -> dict[str, Any]:
        """Raport partii: liczby, powody i id źródła dla pozycji do decyzji."""
        attention = [
            {"source_id": row.source_id, "action": row.action, "reason": row.reason}
            for row in self.rows
            if row.action in ("skip", "conflict")
        ]
        return {
            "module": self.module,
            "total": len(self.rows),
            "counts": self.counts(),
            "reasons": self.reasons(),
            "attention": attention,
        }


Planner = Callable[[AsyncSession, Bundle], Awaitable[ModulePlan]]
Applier = Callable[
    [AsyncSession, ModulePlan, HrImportBatch, Optional[int]], Awaitable[dict[str, int]]
]


async def mapped_target(
    db: AsyncSession, module: str, source_id: str
) -> Optional[HrImportIdMap]:
    return await db.scalar(
        select(HrImportIdMap).where(
            HrImportIdMap.module == module, HrImportIdMap.source_id == source_id
        )
    )


async def remember(
    db: AsyncSession,
    *,
    module: str,
    source_id: str,
    target_table: str,
    target_id: object,
    decision: str,
    batch: HrImportBatch,
) -> None:
    existing = await mapped_target(db, module, source_id)
    if existing is not None:
        existing.target_table = target_table
        existing.target_id = str(target_id)
        existing.batch_id = batch.id
        return
    db.add(
        HrImportIdMap(
            module=module,
            source_id=source_id,
            target_table=target_table,
            target_id=str(target_id),
            decision=decision,
            batch_id=batch.id,
        )
    )


async def last_written_at(
    db: AsyncSession, mapped: Optional[HrImportIdMap]
) -> Optional[datetime]:
    """Kiedy import ostatnio zapisał cel wiersza mapy (czas transakcji zapisu)."""

    if mapped is None:
        return None
    if mapped.batch_id is not None:
        applied = await db.scalar(
            select(HrImportBatch.applied_at).where(HrImportBatch.id == mapped.batch_id)
        )
        if applied is not None:
            return applied
    return mapped.created_at


async def changed_in_nexus(
    db: AsyncSession, mapped: Optional[HrImportIdMap], updated_at: Optional[datetime]
) -> bool:
    """Cel zmieniony w NEXUSIE po ostatnim zapisie importu (decyzja, anulowanie,
    akceptacja, blokada płac) — import go nie nadpisuje."""

    written = await last_written_at(db, mapped)
    return written is not None and updated_at is not None and updated_at > written


async def dry_run(
    db: AsyncSession,
    *,
    module: str,
    bundle: Bundle,
    planner: Planner,
    actor_user_id: Optional[int],
) -> tuple[HrImportBatch, ModulePlan]:
    plan = await planner(db, bundle)
    batch = HrImportBatch(
        module=module,
        bundle_sha256=bundle.sha256,
        schema_version=bundle.version,
        status="dry_run",
        report={"dry_run": plan.report(), "exported_at": bundle.exported_at},
        created_by=actor_user_id,
    )
    db.add(batch)
    await db.flush()
    return batch, plan


async def apply(
    db: AsyncSession,
    *,
    batch: HrImportBatch,
    bundle: Bundle,
    planner: Planner,
    applier: Applier,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    if batch.status != "dry_run":
        raise ImportFlowError("Zapisać można tylko partię po przebiegu na sucho.")
    if batch.bundle_sha256 != bundle.sha256:
        raise ImportFlowError("To nie jest ta sama paczka, którą sprawdzono na sucho.")
    plan = await planner(db, bundle)
    counts = await applier(db, plan, batch, actor_user_id)
    batch.status = "applied"
    batch.applied_by = actor_user_id
    # Czas transakcji (jak ``updated_at`` zapisanych wierszy): późniejsza zmiana
    # w NEXUSIE ma ``updated_at`` większy niż ten znacznik.
    batch.applied_at = await db.scalar(select(func.now()))
    batch.report = {
        **(batch.report or {}),
        "applied": {**plan.report(), "written": counts},
    }
    await db.flush()
    return counts
