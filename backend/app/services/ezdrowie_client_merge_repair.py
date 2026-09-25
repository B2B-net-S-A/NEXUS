"""Dokończenie scalenia E-Zdrowie 37721 → eZdrowie 115 (25.09.2026).

Rekord 37721 (Traffit id 150) jest od 06.08.2026 oznaczony
``merged_into_client_id=115`` i ukryty, ale nocny import Traffita mapował
id Traffita na własny wiersz i przypinał do niego rekrutacje. Z jednej z nich
powstał kontrakt, zamówienie i umowa B2B — dane Centrum e-Zdrowia leżały na
ukrytym duplikacie.

Import już podąża za scaleniem (``traffit.importer._canonical_client_id``),
a ta korekta jednorazowo przenosi to, co zdążyło trafić na duplikat:

- rekrutacje (``jobs.client_id``) — wprost;
- kontrakty — przez ``contract_client_reassign`` (ta sama ścieżka co akcja
  „Przepnij na innego klienta”: zamówienia, umowy B2B, braki, alerty).
  Kontrakt z blokerem zostaje na miejscu i trafia do paragonu.

Wiersz 37721 zostaje jako ukryty, scalony nagrobek z ``external_id`` — to on
kieruje Traffita na właściwego klienta. Paragon: liczby i id, bez nazwisk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.contract import Contract
from app.models.job import Job
from app.services import contract_client_reassign as reassign

logger = logging.getLogger(__name__)

REPAIR_MARKER = "ezdrowie_client_merge_2026_09"


@dataclass(frozen=True)
class ClientMergeTarget:
    duplicate_id: int
    duplicate_external_id: str
    canonical_id: int


TARGET = ClientMergeTarget(
    duplicate_id=37721, duplicate_external_id="150", canonical_id=115
)


async def _remaining_references(db: AsyncSession, client_id: int) -> dict[str, int]:
    """Wiersze wskazujące FK na klienta — tylko do paragonu (bez przenoszenia)."""

    refs = (
        await db.execute(
            text(
                """
                SELECT c.conrelid::regclass::text AS tbl, a.attname AS col
                FROM pg_constraint c
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                WHERE c.contype = 'f'
                  AND c.confrelid = 'clients'::regclass
                  AND array_length(c.conkey, 1) = 1
                ORDER BY 1, 2
                """
            )
        )
    ).all()
    counts: dict[str, int] = {}
    for tbl, col in refs:
        count = await db.scalar(
            text(f'SELECT count(*) FROM {tbl} WHERE "{col}" = :cid'),
            {"cid": client_id},
        )
        if count:
            counts[f"{tbl}.{col}"] = int(count)
    return counts


async def merge_client(db: AsyncSession, target: ClientMergeTarget) -> dict[str, Any]:
    result: dict[str, Any] = {
        "duplicate_id": target.duplicate_id,
        "canonical_id": target.canonical_id,
        "skipped": None,
    }
    duplicate = await db.scalar(
        select(Client).where(Client.id == target.duplicate_id).with_for_update()
    )
    canonical = await db.get(Client, target.canonical_id)
    if duplicate is None or canonical is None:
        result["skipped"] = "client_missing"
        return result
    if duplicate.merged_into_client_id != target.canonical_id:
        result["skipped"] = "not_merged_into_canonical"
        return result
    if duplicate.external_id != target.duplicate_external_id:
        result["skipped"] = "external_id_mismatch"
        return result
    if canonical.deleted_at is not None or canonical.merged_into_client_id is not None:
        result["skipped"] = "canonical_not_live"
        return result

    job_ids = list(
        (
            await db.scalars(select(Job.id).where(Job.client_id == target.duplicate_id))
        ).all()
    )
    if job_ids:
        await db.execute(
            update(Job)
            .where(Job.id.in_(job_ids))
            .values(client_id=target.canonical_id)
            .execution_options(synchronize_session=False)
        )

    moved: list[int] = []
    blocked: list[dict[str, Any]] = []
    contract_ids = list(
        (
            await db.scalars(
                select(Contract.id)
                .where(Contract.client_id == target.duplicate_id)
                .order_by(Contract.id)
            )
        ).all()
    )
    for contract_id in contract_ids:
        contract = await reassign.lock_contract(db, contract_id)
        if contract is None:
            continue
        orders = await reassign.lock_orders(db, contract_id)
        plan = await reassign.build_plan(
            db, contract, target.canonical_id, orders=orders
        )
        if plan.blockers:
            blocked.append(
                {
                    "contract_id": contract_id,
                    "codes": sorted(b["code"] for b in plan.blockers),
                }
            )
            continue
        await reassign.execute_reassign(
            db,
            contract_id=contract_id,
            target_client_id=target.canonical_id,
            fingerprint=plan.fingerprint,
            user_id=None,
        )
        moved.append(contract_id)

    await db.flush()
    result.update(
        {
            "jobs_moved": job_ids,
            "contracts_moved": moved,
            "contracts_blocked": blocked,
            "remaining_references": await _remaining_references(
                db, target.duplicate_id
            ),
        }
    )
    return result


async def run_ezdrowie_client_merge(
    db: AsyncSession,
    *,
    target: ClientMergeTarget = TARGET,
    marker: str = REPAIR_MARKER,
) -> Optional[dict[str, Any]]:
    """Wykonaj korektę raz; ``None`` = już wykonana. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    result = await merge_client(db, target)
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("ezdrowie client merge: %s", summarize_for_log(summary))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    if summary.get("skipped"):
        return f"skipped: {summary['skipped']}"
    return (
        f"jobs {len(summary.get('jobs_moved') or [])}, "
        f"contracts {len(summary.get('contracts_moved') or [])}, "
        f"blocked {len(summary.get('contracts_blocked') or [])}, "
        f"remaining {sum((summary.get('remaining_references') or {}).values())}"
    )
