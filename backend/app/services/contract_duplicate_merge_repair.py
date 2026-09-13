"""Jednorazowe scalenie zduplikowanego kontraktu ze zgłoszenia (09.2026).

Czytnik poczty zamówień (09.09.2026, przed regułą „jedyny imiennik wymaga
człowieka") dopiął zamówienie do INNEGO rekordu kandydata o tym samym imieniu
i nazwisku i założył mu drugi kontrakt u tego samego klienta. Zgłoszenie
wskazuje kontrakt do zachowania i duplikat do usunięcia.

Scalenie idzie tą samą drogą co sierpniowe czyszczenie duplikatów
(``app.services.contract_merge``): katalog FK do ``contracts`` czytany z bazy
(nieznana tabela = odmowa), przepięcie wierszy potomnych na kontrakt
zachowany, przepięcie historii polimorficznej (Activity, powiadomienia,
deduplikacja alertów), sprawdzenie, że nic nie wskazuje już na duplikat,
fizyczne ``DELETE`` bez soft-delete i wpis ``contracts_merged`` na kontrakcie
zachowanym. Różnice wobec sierpnia są świadome:

* **pola**: wyłącznie uzupełnianie PUSTYCH pól kontraktu zachowanego — nic, co
  już na nim jest, nie zostaje nadpisane (sierpień brał np. najwcześniejszą
  datę startu). Decyzje o końcu współpracy duplikatu (data końca,
  wypowiedzenie) nie przechodzą na żywy kontrakt;
* **stawki**: kroki harmonogramu z zamówienia (``source_order_id``) idą za
  zamówieniem; ręczne kroki duplikatu przechodzą tylko tam, gdzie kontrakt
  zachowany nie ma stawki tego rodzaju — inaczej scalenie jest pomijane
  z powodem (harmonogram wygrywa z kolumną, więc przeniesienie nadpisałoby
  stawkę);
* **dowody podpisu** duplikatu (podpisy, wygenerowane umowy B2B) należą do
  innego rekordu osoby — ich obecność zatrzymuje scalenie z powodem;
* **zamówienie z maila** pozostawione jako szkic tylko dlatego, że wisiało
  na złym kontrakcie, przechodzi przez tę samą bramkę co po podpisie umowy
  (``complete_signed_mail_drafts``), a kontrakt synchronizuje się z zamówieniami
  jak po zwykłym zapisie zamówienia;
* **Historia zdarzeń**: usunięcie duplikatu trafia do ``critical_events``
  (Ustawienia → Historia zdarzeń) obok wpisu w dzienniku kontraktu.

Repo jest publiczne: lista NIE zawiera nazwisk — tylko identyfikatory
kontraktów, rekordów osób i klienta sprawdzone na produkcji. Pozycja, której
identyfikatory się nie zgadzają, zostaje nietknięta z kodem powodu w paragonie.

Blok jest jednorazowy (marker w ``app_settings`` + advisory lock) i odpalany
z ``entrypoint.sh``. Paragon pod kluczem ``NNNN_…`` niesie wyłącznie liczniki,
ID i kody powodów (czyta go publiczny log workflow ``migration-receipts``);
migawka duplikatu leży pod kluczem innego kształtu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.contract import Contract, ContractStatus
from app.services.contract_merge import (
    _alias_alert_dedup,
    _assert_no_fk_rows,
    _contract_fk_catalog,
    _is_empty,
    _repoint_polymorphic,
    _reparent_fks,
    _stable,
)
from app.services.contract_order_sync import resync_contract_safely
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.critical_events import record_executed
from app.services.order_mail_signature import complete_signed_mail_drafts

logger = logging.getLogger(__name__)

REPAIR_MARKER = "0308_contract_duplicate_merge"
DETAILS_KEY = "repair_details_0308_contract_duplicate_merge"
SOURCE = REPAIR_MARKER

_LIVE_STATUSES = (ContractStatus.active, ContractStatus.ending)

# Pola uzupełniane na kontrakcie zachowanym, gdy są na nim PUSTE.
_FILL_FIELDS = (
    "job_id",
    "start_date",
    "client_order_start_date",
    "client_order_end_date",
    "client_pm_name",
    "client_pm_email",
    "client_pm_contact_id",
    "work_mode",
    "line_manager",
    "office_location",
    "team_name",
    "project_name",
    "handover_notes",
    "target_rate_min",
    "target_rate_max",
    "project_code",
    "prolongation_status",
    "engagement_model",
    "hours_pool_total",
    "hours_pool_consumed",
    "order_consumption",
    "order_consumption_unit",
    "draft_content_html",
    "draft_template_id",
    "draft_updated_at",
    "draft_updated_by",
)

# Stawka z kolumny: uzupełniana tylko razem z krokami harmonogramu duplikatu
# (jeśli je ma) i tylko gdy kontrakt zachowany nie ma stawki tego rodzaju.
_RATE_KINDS = (
    ("candidate", "rate_candidate", "candidate_rate_schedule"),
    ("client", "rate_client", "client_rate_schedule"),
    ("framework", "framework_rate", "framework_rate_schedule"),
)

# Decyzje o końcu współpracy duplikatu nie przechodzą na żywy kontrakt.
_NOT_TRANSFERRED = (
    "end_date",
    "terminated_at",
    "termination_reason",
    "termination_lessons",
)


@dataclass(frozen=True)
class DuplicateContractMerge:
    """Jedna para ze zgłoszenia — wyłącznie identyfikatory, bez nazwisk."""

    keep_contract_id: int
    keep_candidate_id: int
    delete_contract_id: int
    delete_candidate_id: int
    client_id: int


# Zgłoszenie „Ticket 12" (09.2026), identyfikatory odczytane z produkcji
# 13.09.2026: duplikat założony z maila zamówień 09.09.2026 na innym rekordzie
# osoby, zachowywany kontrakt z podpisaną umową B2B.
TICKET_MERGES: tuple[DuplicateContractMerge, ...] = (
    DuplicateContractMerge(
        keep_contract_id=562,
        keep_candidate_id=28087,
        delete_contract_id=656,
        delete_candidate_id=464136,
        client_id=122,
    ),
)


async def _load(db: AsyncSession, contract_id: int) -> Optional[Contract]:
    return await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(*RATE_SCHEDULE_LOADS)
        .with_for_update(of=Contract)
        .execution_options(populate_existing=True)
    )


async def _count(db: AsyncSession, sql: str, contract_id: int) -> int:
    return int(await db.scalar(text(sql), {"c": contract_id}) or 0)


async def _blocker(
    db: AsyncSession, spec: DuplicateContractMerge, keep: Contract, drop: Contract
) -> Optional[str]:
    if (keep.candidate_id, keep.client_id) != (
        spec.keep_candidate_id,
        spec.client_id,
    ) or (drop.candidate_id, drop.client_id) != (
        spec.delete_candidate_id,
        spec.client_id,
    ):
        return "identity_mismatch"
    if keep.status not in _LIVE_STATUSES:
        return f"keep_status_{keep.status.value}"
    if drop.status == ContractStatus.void:
        return "delete_status_void"
    if await _count(
        db,
        "SELECT (SELECT count(*) FROM document_signatures WHERE contract_id = :c)"
        " + (SELECT count(*) FROM b2b_generated_contracts WHERE contract_id = :c)",
        drop.id,
    ):
        return "signed_evidence_on_duplicate"
    if await _count(
        db, "SELECT count(*) FROM b2b_contract_details WHERE contract_id = :c", drop.id
    ) and await _count(
        db, "SELECT count(*) FROM b2b_contract_details WHERE contract_id = :c", keep.id
    ):
        return "b2b_details_conflict"
    for kind, column, schedule in _RATE_KINDS:
        manual_steps = [
            step
            for step in getattr(drop, schedule)
            if getattr(step, "source_order_id", None) is None
        ]
        if manual_steps and (
            getattr(keep, schedule) or getattr(keep, column) is not None
        ):
            return f"rate_schedule_conflict_{kind}"
    # Krok przychodu z zamówienia duplikatu staje się CAŁYM harmonogramem
    # kontraktu bez harmonogramu, a przed swoją datą resolver bierze najbliższy
    # przyszły krok — inna kwota przeceniłaby wstecz miesiące sprzed zamówienia.
    if not keep.client_rate_schedule and keep.rate_client is not None:
        if any(
            step.rate != keep.rate_client
            for step in drop.client_rate_schedule
            if step.source_order_id is not None
        ):
            return "client_rate_baseline_conflict"
    has_rates = any(
        getattr(keep, column) is not None and getattr(drop, column) is not None
        for _kind, column, _schedule in _RATE_KINDS
    )
    if has_rates and (
        keep.rate_unit != drop.rate_unit
        or keep.resolved_rate_client_currency != drop.resolved_rate_client_currency
        or keep.resolved_rate_candidate_currency
        != drop.resolved_rate_candidate_currency
    ):
        return "rate_unit_or_currency_mismatch"
    return None


def _fill_fields(keep: Contract, drop: Contract) -> dict[str, dict[str, Any]]:
    filled: dict[str, dict[str, Any]] = {}
    for field in _FILL_FIELDS:
        if _is_empty(getattr(keep, field)) and not _is_empty(getattr(drop, field)):
            setattr(keep, field, getattr(drop, field))
            filled[field] = {"from": _stable(getattr(drop, field))}
    for _kind, column, schedule in _RATE_KINDS:
        if (
            getattr(keep, column) is None
            and not getattr(keep, schedule)
            and getattr(drop, column) is not None
        ):
            setattr(keep, column, getattr(drop, column))
            filled[column] = {"from": _stable(getattr(drop, column))}
    existing = keep.documents if isinstance(keep.documents, list) else []
    incoming = drop.documents if isinstance(drop.documents, list) else []
    added = [item for item in incoming if item not in existing]
    if added:
        keep.documents = existing + added
        filled["documents"] = {"added": len(added)}
    if {"rate_candidate", "rate_client"} & set(filled):
        if (
            keep.rate_client is not None
            and keep.rate_candidate is not None
            and keep.resolved_rate_client_currency
            == keep.resolved_rate_candidate_currency
        ):
            keep.margin = Decimal(keep.rate_client) - Decimal(keep.rate_candidate)
    return filled


def _snapshot(contract: Contract) -> dict[str, Any]:
    return _stable(
        {
            column.key: getattr(contract, column.key)
            for column in Contract.__table__.columns
        }
    )


async def _merge_one(
    db: AsyncSession, spec: DuplicateContractMerge
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    item: dict[str, Any] = {
        "keep_contract_id": spec.keep_contract_id,
        "delete_contract_id": spec.delete_contract_id,
        "skipped": None,
    }
    # Stała kolejność blokad (rosnące ID), jak w sierpniowym scaleniu.
    first, second = sorted((spec.keep_contract_id, spec.delete_contract_id))
    loaded = {first: await _load(db, first), second: await _load(db, second)}
    keep, drop = loaded[spec.keep_contract_id], loaded[spec.delete_contract_id]
    if keep is None or drop is None:
        item["skipped"] = "not_found"
        return item, None
    reason = await _blocker(db, spec, keep, drop)
    if reason is not None:
        item["skipped"] = reason
        return item, None

    details: dict[str, Any] = {
        "delete_contract_id": drop.id,
        "delete_snapshot": _snapshot(drop),
        "not_transferred": {
            field: _stable(getattr(drop, field))
            for field in _NOT_TRANSFERRED
            if not _is_empty(getattr(drop, field))
        },
    }
    filled = _fill_fields(keep, drop)
    await db.flush()
    keep_id, drop_id = keep.id, drop.id
    client_id = keep.client_id
    drop_status = drop.status.value
    # Dalej surowy SQL na wierszach potomnych — obiekty ORM obu kontraktów
    # (z załadowanymi harmonogramami) byłyby po nim nieaktualne.
    db.expunge_all()

    catalog = await _contract_fk_catalog(db)
    moved = await _reparent_fks(db, catalog, [drop_id], keep_id)
    moved.update(await _repoint_polymorphic(db, [drop_id], keep_id, {}))
    moved["contract_alert_dedup_aliases"] = await _alias_alert_dedup(
        db, [drop_id], keep_id
    )
    await _assert_no_fk_rows(db, catalog, [drop_id])
    deleted = await db.execute(
        text("DELETE FROM contracts WHERE id = :id"), {"id": drop_id}
    )
    if int(deleted.rowcount or 0) != 1:
        raise RuntimeError("duplicate contract DELETE count mismatch")

    activated = await complete_signed_mail_drafts(db, keep_id, actor_id=None)
    survivor = await db.scalar(
        select(Contract)
        .where(Contract.id == keep_id)
        .options(*RATE_SCHEDULE_LOADS)
        .execution_options(populate_existing=True)
    )
    await resync_contract_safely(db, survivor, actor_id=None)

    moved_counts = {key: value for key, value in moved.items() if value}
    db.add(
        Activity(
            entity_type="contract",
            entity_id=keep_id,
            action="contracts_merged",
            user_id=None,
            external_source=SOURCE,
            external_id=f"merge:{keep_id}:{drop_id}",
            details={
                "source": SOURCE,
                "survivor_contract_id": keep_id,
                "deleted_contract_ids": [drop_id],
                "deleted_status": drop_status,
                "filled_fields": sorted(filled),
                "reparented": moved_counts,
                "mail_orders_activated": activated,
            },
        )
    )
    await record_executed(
        db,
        actor=None,
        event_type="contract.delete",
        entity_type="contract",
        entity_id=drop_id,
        entity_label=f"Kontrakt #{drop_id}",
        client_id=client_id,
        reason_code="duplicate_merged",
        reason=(
            f"Duplikat scalony z kontraktem #{keep_id} i usunięty trwale "
            "(korekta danych ze zgłoszenia)."
        ),
        details={
            "merged_into_contract_id": keep_id,
            "reparented": moved_counts,
            "source": SOURCE,
        },
    )
    await db.flush()

    item.update(
        {
            "filled_fields": sorted(filled),
            "reparented": moved_counts,
            "mail_orders_activated": activated,
        }
    )
    details["filled"] = filled
    return item, details


async def run_contract_duplicate_merge_repair(
    db: AsyncSession,
    *,
    merges: tuple[DuplicateContractMerge, ...] = TICKET_MERGES,
    marker: str = REPAIR_MARKER,
    details_key: str = DETAILS_KEY,
) -> Optional[dict[str, Any]]:
    """Scal pary ze zgłoszenia. ``None`` = już było. Wołający commituje."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    # Stary kontener przy wdrożeniu trzyma blokady zamówień/kontraktów; bez
    # limitu start czekałby w nieskończoność. Przekroczenie = rollback,
    # następny start ponawia (jak w korekcie 0306).
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    if await db.get(AppSetting, marker) is not None:
        return None

    results: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for spec in merges:
        item, snapshot = await _merge_one(db, spec)
        results.append(item)
        if snapshot is not None:
            details.append(snapshot)

    applied = [item for item in results if item["skipped"] is None]
    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "merges_requested": len(merges),
        "merges_applied": len(applied),
        "merges_skipped": [
            {
                "delete_contract_id": item["delete_contract_id"],
                "reason": item["skipped"],
            }
            for item in results
            if item["skipped"] is not None
        ],
        "merged": applied,
    }
    db.add(AppSetting(key=marker, value=_stable(summary)))
    db.add(AppSetting(key=details_key, value={"merged": _stable(details)}))
    await db.flush()
    logger.info("contract duplicate merge: %s/%s applied", len(applied), len(merges))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    skipped = ", ".join(
        f"{item['delete_contract_id']}:{item['reason']}"
        for item in summary["merges_skipped"]
    )
    return f"merged {summary['merges_applied']}/{summary['merges_requested']}" + (
        f" (skipped {skipped})" if skipped else ""
    )
