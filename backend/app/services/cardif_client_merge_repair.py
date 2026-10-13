"""Pełne scalenie „BNP Paribas Cardif” (52) → Cardif Assurances (38335), 13.10.2026.

Duplikat powstał z mapowania w Traffit. Migracja 0244 przepięła w sierpniu
cztery wskazane wiersze; reszta historii została na rekordzie 52, a podpisana
umowa 1520/2026 straciła kontrakt (kontrakt założony przy podpisie u klienta 52
usunięto, właściwy powstał osobno u 38335) i pokazywała „Kontrakt usunięty —
brak kontraktora”.

Korekta jednorazowo:

- przenosi rekrutacje (z procesami), kontakty, kartę klienta, wiedzę,
  materiały i alerty Delivery Leada;
- kontrakty przepina ścieżką „Przepnij na innego klienta”
  (``contract_client_reassign``) — kontrakt z blokerem zostaje i trafia do
  paragonu;
- wiąże umowę z kontraktem tak jak akcja „Powiąż z kontraktem”; treść
  podpisanego dokumentu (``render_payload``) zostaje, zmienia się klient
  wiersza i nazwa w rejestrze (jak w 0244);
- oznacza rekord 52 jako scalony z 38335 (decyzja z 13.10.2026) — te same
  pola co ``POST /api/clients/{id}/merge-into/{target}``, tylko gdy nic już
  scalenia nie blokuje.

Na rekordzie 52 zostaje wpis katalogu (zakres portfela, wiersz importu,
przydział DL) i dziennik — tak jak u wcześniej scalonych klientów.
Paragon: liczby i id, bez nazwisk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.dl_alert import DlAlert
from app.models.job import Job
from app.models.recruitment_process import RecruitmentProcess
from app.services import contract_client_reassign as reassign
from app.services.client_deletion import (
    _configured,
    _merge_singleton_conflicts,
    assess_client_merge_blockers,
)
from app.services.critical_events import record_executed
from app.services.ezdrowie_client_merge_repair import _remaining_references
from app.services.index_outbox_service import JOB, record_bulk_reindex

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0435_cardif_client_merge"
SOURCE = REPAIR_MARKER

# Wpis katalogu rekordu źródłowego — zostaje (inwariant manifestu portfela).
_EXPECTED_REMAINING = frozenset(
    {
        "client_portfolio_scopes.client_id",
        "client_import_rows.matched_client_id",
        "delivery_lead_client_assignments.client_id",
    }
)
# Kolumny klienta bez klucza obcego — ``_remaining_references`` ich nie widzi.
_UNKEYED_CLIENT_TABLES = ("order_gaps", "order_change_events", "order_change_checks")


@dataclass(frozen=True)
class AgreementLink:
    generated_id: int
    contract_number: str
    contract_id: int


@dataclass(frozen=True)
class CardifMergeTarget:
    source_id: int
    target_id: int
    # Id są zaszyte, więc nazwa jest kontrolą, że na tej bazie znaczą to samo
    # co na produkcji (jak w 0244).
    name_token: str
    agreement: Optional[AgreementLink] = None


TARGET = CardifMergeTarget(
    source_id=52,
    target_id=38335,
    name_token="cardif",
    agreement=AgreementLink(
        generated_id=110, contract_number="1520/2026", contract_id=689
    ),
)


def _named(client: Client, token: str) -> bool:
    return token.casefold() in (client.name or "").casefold()


async def _skip_reason(
    db: AsyncSession,
    source: Optional[Client],
    canonical: Optional[Client],
    target: CardifMergeTarget,
) -> Optional[str]:
    if source is None or canonical is None:
        return "client_missing"
    if not (_named(source, target.name_token) and _named(canonical, target.name_token)):
        return "identity_mismatch"
    if source.merged_into_client_id not in (None, target.target_id):
        return "source_merged_elsewhere"
    if (
        canonical.deleted_at is not None
        or canonical.merged_into_client_id is not None
        or canonical.hidden
        or canonical.archived_at is not None
    ):
        return "target_not_live"
    if _configured(source.id, None) is not None:
        return "source_configured"
    if await _merge_singleton_conflicts(db, source.id, canonical.id) is not None:
        return "duplicate_singletons"
    return None


async def _move_jobs(
    db: AsyncSession, target: CardifMergeTarget
) -> tuple[list[int], int]:
    job_ids = list(
        (
            await db.scalars(
                select(Job.id).where(Job.client_id == target.source_id).order_by(Job.id)
            )
        ).all()
    )
    if job_ids:
        await db.execute(
            update(Job)
            .where(Job.id.in_(job_ids))
            .values(client_id=target.target_id)
            .execution_options(synchronize_session=False)
        )
        # Payload wektorów rekrutacji niesie ``client_id`` („Podobne
        # rekrutacje” filtrują po nim) — intencja ponownego osadzenia.
        await record_bulk_reindex(db, JOB, job_ids)
    # ``recruitment_processes.client_id`` to kopia ``jobs.client_id``.
    processes = await db.execute(
        update(RecruitmentProcess)
        .where(
            RecruitmentProcess.client_id == target.source_id,
            RecruitmentProcess.job_id.in_(
                select(Job.id).where(Job.client_id == target.target_id)
            ),
        )
        .values(client_id=target.target_id)
        .execution_options(synchronize_session=False)
    )
    return job_ids, int(processes.rowcount or 0)


async def _move_contracts(
    db: AsyncSession, target: CardifMergeTarget
) -> tuple[list[int], list[dict[str, Any]]]:
    moved: list[int] = []
    blocked: list[dict[str, Any]] = []
    contract_ids = list(
        (
            await db.scalars(
                select(Contract.id)
                .where(Contract.client_id == target.source_id)
                .order_by(Contract.id)
            )
        ).all()
    )
    for contract_id in contract_ids:
        contract = await reassign.lock_contract(db, contract_id)
        if contract is None:
            continue
        orders = await reassign.lock_orders(db, contract_id)
        plan = await reassign.build_plan(db, contract, target.target_id, orders=orders)
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
            target_client_id=target.target_id,
            fingerprint=plan.fingerprint,
            user_id=None,
        )
        moved.append(contract_id)
    return moved, blocked


async def _move_alerts(db: AsyncSession, target: CardifMergeTarget) -> int:
    result = await db.execute(
        update(DlAlert)
        .where(DlAlert.client_id == target.source_id)
        .values(
            client_id=target.target_id,
            link=func.replace(
                DlAlert.link,
                f"/clients/{target.source_id}?",
                f"/clients/{target.target_id}?",
            ),
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def _api_helpers() -> tuple[Any, Any]:
    """Funkcje z ``app.api`` — leniwie i przed blokadami wierszy.

    Bloki korekt w entrypoincie nie ładują routerów; przy kolejnych startach
    (marker już jest) ta korekta też ich nie potrzebuje.
    """

    from app.api.b2b_contract_generator import apply_contract_link
    from app.api.clients import _move_client_materials_on_merge

    return apply_contract_link, _move_client_materials_on_merge


async def _link_agreement(
    db: AsyncSession, link: AgreementLink, canonical: Client, apply_contract_link: Any
) -> dict[str, Any]:
    """Podpisana umowa bez kontraktu → właściwy kontrakt u klienta docelowego.

    Bramki jak w „Powiąż z kontraktem”, ale osoba po id (bez dopasowania po
    nazwisku). Niespełniona bramka pomija sam krok — reszta scalenia idzie.
    """

    result: dict[str, Any] = {
        "generated_id": link.generated_id,
        "contract_id": link.contract_id,
        "skipped": None,
    }
    # Kontrakt przed wierszem rejestru — kolejność blokad z akcji w rejestrze.
    contract = await db.scalar(
        select(Contract).where(Contract.id == link.contract_id).with_for_update()
    )
    row = await db.scalar(
        select(B2BGeneratedContract)
        .where(
            B2BGeneratedContract.id == link.generated_id,
            B2BGeneratedContract.contract_number == link.contract_number,
        )
        .with_for_update()
    )
    if row is None:
        result["skipped"] = "agreement_missing"
    elif row.signature_status != "signed_both":
        result["skipped"] = "agreement_not_signed"
    elif contract is None:
        result["skipped"] = "contract_missing"
    elif contract.status == ContractStatus.void:
        result["skipped"] = "contract_void"
    elif contract.client_id != canonical.id:
        result["skipped"] = "contract_client_mismatch"
    elif row.candidate_id is None or row.candidate_id != contract.candidate_id:
        result["skipped"] = "other_person"
    if result["skipped"]:
        return result

    if row.contract_id is not None:
        current = await db.get(Contract, row.contract_id)
        if current is not None and current.status != ContractStatus.void:
            result["skipped"] = "agreement_already_linked"
            return result
    other = await db.scalar(
        select(B2BGeneratedContract.id).where(
            B2BGeneratedContract.contract_id == contract.id,
            B2BGeneratedContract.id != row.id,
            B2BGeneratedContract.contract_status != "cancelled",
        )
    )
    if other is not None:
        result["skipped"] = "contract_has_other_agreement"
        return result

    await apply_contract_link(db, row, contract, user_id=None)
    # Kolumna „Klient” rejestru (i nazwa w przyszłych aneksach) — jak w 0244.
    # ``render_payload`` to treść podpisanego dokumentu i zostaje.
    row.client_name = canonical.name
    await db.flush()
    return result


async def _unexpected_references(
    db: AsyncSession, client_id: int, remaining: dict[str, int]
) -> dict[str, int]:
    unexpected = {
        key: count for key, count in remaining.items() if key not in _EXPECTED_REMAINING
    }
    for table in _UNKEYED_CLIENT_TABLES:
        count = await db.scalar(
            text(f"SELECT count(*) FROM {table} WHERE client_id = :cid"),
            {"cid": client_id},
        )
        if count:
            unexpected[f"{table}.client_id"] = int(count)
    return unexpected


async def merge_client(db: AsyncSession, target: CardifMergeTarget) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_id": target.source_id,
        "target_id": target.target_id,
        "skipped": None,
    }
    apply_contract_link, move_client_materials = _api_helpers()
    # Blokada obu wierszy po id — jak scalenie z API (zapis warunków umowy
    # i karty klienta bierze blokadę wiersza klienta).
    clients = {
        client.id: client
        for client in (
            await db.scalars(
                select(Client)
                .where(Client.id.in_((target.source_id, target.target_id)))
                .order_by(Client.id)
                .with_for_update()
            )
        ).all()
    }
    source = clients.get(target.source_id)
    canonical = clients.get(target.target_id)
    result["skipped"] = await _skip_reason(db, source, canonical, target)
    if result["skipped"]:
        return result

    job_ids, processes_moved = await _move_jobs(db, target)
    contracts_moved, contracts_blocked = await _move_contracts(db, target)
    materials_moved = await move_client_materials(
        db, target.source_id, target.target_id
    )
    alerts_moved = await _move_alerts(db, target)
    agreement = (
        await _link_agreement(db, target.agreement, canonical, apply_contract_link)
        if target.agreement is not None
        else None
    )
    await db.flush()

    remaining = await _remaining_references(db, target.source_id)
    unexpected = await _unexpected_references(db, target.source_id, remaining)
    # Ta sama reguła co ``merge-into``: scalony wiersz nie może trzymać
    # żywych danych. Gdy coś jednak zostało (kontrakt z blokerem, umowa
    # z niespełnioną bramką), dane są przeniesione, a flaga czeka na człowieka.
    merge_blockers = sorted(
        blocker.code
        for blocker in await assess_client_merge_blockers(
            db, source, target_id=target.target_id
        )
    )
    merged = not merge_blockers and not unexpected
    if merged and source.merged_into_client_id is None:
        source.merged_into_client_id = target.target_id
        source.archived_at = source.archived_at or datetime.now(timezone.utc)
        db.add(
            Activity(
                entity_type="client",
                entity_id=source.id,
                action="merged",
                user_id=None,
                details={
                    "merged_into_client_id": target.target_id,
                    "moved": materials_moved,
                    "source": SOURCE,
                },
            )
        )

    counts = {
        "jobs": len(job_ids),
        "processes": processes_moved,
        "contracts": len(contracts_moved),
        "alerts": alerts_moved,
        **materials_moved,
    }
    await record_executed(
        db,
        actor=None,
        event_type="client.merge",
        entity_type="client",
        entity_id=source.id,
        entity_label=source.name,
        client_id=canonical.id,
        reason_code="duplicate_merged",
        reason=(
            f"Dane duplikatu przeniesione na klienta #{canonical.id} "
            "(korekta danych ze zgłoszenia)."
        ),
        details={
            "merged_into_client_id": canonical.id,
            "merged": merged,
            "moved": counts,
            "source": SOURCE,
        },
    )

    result.update(
        {
            "jobs_moved": job_ids,
            "processes_moved": processes_moved,
            "contracts_moved": contracts_moved,
            "contracts_blocked": contracts_blocked,
            "materials_moved": materials_moved,
            "alerts_moved": alerts_moved,
            "agreement": agreement,
            "merged": merged,
            "merge_blockers": merge_blockers,
            "remaining_references": remaining,
            "unexpected_references": unexpected,
        }
    )
    return result


async def run_cardif_client_merge(
    db: AsyncSession,
    *,
    target: CardifMergeTarget = TARGET,
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
    logger.info("cardif client merge: %s", summarize_for_log(summary))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    if summary.get("skipped"):
        return f"skipped: {summary['skipped']}"
    agreement = summary.get("agreement")
    if agreement is None:
        agreement_state = "none"
    else:
        agreement_state = agreement.get("skipped") or "linked"
    return (
        f"jobs {len(summary.get('jobs_moved') or [])}, "
        f"processes {summary.get('processes_moved') or 0}, "
        f"contracts {len(summary.get('contracts_moved') or [])}, "
        f"blocked {len(summary.get('contracts_blocked') or [])}, "
        f"materials {sum((summary.get('materials_moved') or {}).values())}, "
        f"alerts {summary.get('alerts_moved') or 0}, "
        f"agreement {agreement_state}, "
        f"merged {bool(summary.get('merged'))}, "
        f"unexpected {sum((summary.get('unexpected_references') or {}).values())}"
    )
