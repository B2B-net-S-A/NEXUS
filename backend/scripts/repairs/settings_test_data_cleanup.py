"""Sprzątanie śladów testów z Ustawień (decyzja Artura 20.10.2026).

Inwentarz: ``docs/settings-test-data-inventory.md`` (PR #2437). Artur
zgodził się na cztery pozycje:

A. klient „[QA-E2E-2026-09-13] …” znika z list Ustawień — reguła CV, karta
   klienta (z ich zdarzeniami i publikacją), przypisanie Delivery Leada
   i portfele. Sam klient i jego zamknięte rekrutacje zostają, bo siedzą na
   nich karty prawdziwych kandydatów;
B. zarchiwizowany szablon procesu „ZZZ-claude-reorder-smoke-…” (etapy
   i powody odrzucenia idą kaskadą), tylko gdy nic go nie używa;
C. wzór umowy „(smoke test)” — kontrakty tracą tylko wskazanie wzoru
   (``ON DELETE SET NULL``), treść szkicu zostaje;
D. konto serwisowe ``claude-traffit-ops`` — klucze odwołane, konto
   wyłączone, nic nie jest kasowane (sync Traffita wyłączony od 14.10.2026).

Jednorazowo (paragon w ``app_settings`` + advisory lock). Każdy wiersz jest
przypięty do ``id`` i odcisku; niezgodny zostaje nietknięty i trafia do
paragonu jako pominięty. Każda pozycja biegnie w savepoincie, więc
nieoczekiwane powiązanie blokuje tylko ją. Paragon niesie wyłącznie id
i liczby.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

logger = logging.getLogger(__name__)

REPAIR_MARKER = "settings_test_data_cleanup_2026_10_20"
REVOKE_REASON = "Sync Traffita wyłączony 14.10.2026; sprzątanie Ustawień 20.10.2026."


@dataclass(frozen=True)
class PinnedRow:
    """Wiersz przypięty do id i klienta, do którego należy."""

    row_id: int
    client_id: int


@dataclass(frozen=True)
class PinnedNamed:
    row_id: int
    name: str


@dataclass(frozen=True)
class SettingsCleanupPlan:
    qa_clients: tuple[PinnedNamed, ...]
    cv_rules: tuple[PinnedRow, ...]
    playbooks: tuple[PinnedRow, ...]
    dl_assignments: tuple[PinnedRow, ...]
    portfolio_scopes: tuple[PinnedRow, ...]
    pipeline_template: PinnedNamed
    contract_template: PinnedNamed
    # ``name`` = slug konta serwisowego.
    service_account: PinnedNamed


PROD_PLAN = SettingsCleanupPlan(
    qa_clients=(
        PinnedNamed(64636, "[QA-E2E-2026-09-13] Klient Testowy"),
        PinnedNamed(64637, "[QA-E2E-2026-09-13] Klient Wieloosobowy"),
    ),
    cv_rules=(PinnedRow(965, 64636),),
    playbooks=(PinnedRow(644, 64636),),
    dl_assignments=(PinnedRow(37, 64636),),
    portfolio_scopes=(PinnedRow(172, 64636), PinnedRow(173, 64637)),
    pipeline_template=PinnedNamed(73, "ZZZ-claude-reorder-smoke-1780661184"),
    contract_template=PinnedNamed(1, "Umowa B2B — szablon domyślny (smoke test)"),
    service_account=PinnedNamed(1, "claude-traffit-ops"),
)


async def _count(db: AsyncSession, sql: str, **params: Any) -> int:
    return int((await db.execute(text(sql), params)).scalar_one())


async def _delete_pinned(
    db: AsyncSession,
    table: str,
    pins: tuple[PinnedRow, ...],
    clients: set[int],
    summary: dict[str, Any],
) -> list[int]:
    """Usuń wiersze ``table`` po (id, client_id); zwraca klientów usuniętych wierszy."""

    done: list[int] = []
    for pin in pins:
        key = f"{table}:{pin.row_id}"
        if pin.client_id not in clients:
            summary["skipped"][key] = "client_not_pinned"
            continue
        result = await db.execute(
            text(f"DELETE FROM {table} WHERE id = :id AND client_id = :cid"),
            {"id": pin.row_id, "cid": pin.client_id},
        )
        if result.rowcount != 1:
            summary["skipped"][key] = "missing"
            continue
        summary["deleted"].setdefault(table, []).append(pin.row_id)
        done.append(pin.client_id)
    return done


async def _qa_clients_out_of_settings(
    db: AsyncSession, plan: SettingsCleanupPlan, summary: dict[str, Any]
) -> None:
    clients: set[int] = set()
    for pin in plan.qa_clients:
        name = (
            await db.execute(
                text("SELECT name FROM clients WHERE id = :id"), {"id": pin.row_id}
            )
        ).scalar_one_or_none()
        if name == pin.name:
            clients.add(pin.row_id)
        else:
            summary["skipped"][f"clients:{pin.row_id}"] = (
                "missing" if name is None else "fingerprint_mismatch"
            )
    if not clients:
        return

    for client_id in await _delete_pinned(
        db, "client_cv_rules", plan.cv_rules, clients, summary
    ):
        for table in ("client_cv_rule_events", "client_cv_rule_publications"):
            result = await db.execute(
                text(f"DELETE FROM {table} WHERE client_id = :cid"), {"cid": client_id}
            )
            summary["history_rows_deleted"] += result.rowcount
    for client_id in await _delete_pinned(
        db, "client_playbooks", plan.playbooks, clients, summary
    ):
        result = await db.execute(
            text("DELETE FROM client_playbook_events WHERE client_id = :cid"),
            {"cid": client_id},
        )
        summary["history_rows_deleted"] += result.rowcount
    await _delete_pinned(
        db, "delivery_lead_client_assignments", plan.dl_assignments, clients, summary
    )
    await _delete_pinned(
        db, "client_portfolio_scopes", plan.portfolio_scopes, clients, summary
    )


async def _smoke_pipeline_template(
    db: AsyncSession, plan: SettingsCleanupPlan, summary: dict[str, Any]
) -> None:
    pin = plan.pipeline_template
    key = f"pipeline_templates:{pin.row_id}"
    row = (
        await db.execute(
            text(
                "SELECT name, archived, is_default FROM pipeline_templates "
                "WHERE id = :id FOR UPDATE"
            ),
            {"id": pin.row_id},
        )
    ).one_or_none()
    if row is None:
        summary["skipped"][key] = "missing"
        return
    if row.name != pin.name or not row.archived or row.is_default:
        summary["skipped"][key] = "fingerprint_mismatch"
        return
    in_use = await _count(
        db,
        "SELECT (SELECT count(*) FROM jobs WHERE pipeline_template_id = :id)"
        " + (SELECT count(*) FROM candidate_stages cs"
        "    JOIN pipeline_stage_defs sd ON sd.id = cs.stage_def_id"
        "    WHERE sd.template_id = :id)"
        " + (SELECT count(*) FROM candidate_stages cs"
        "    JOIN rejection_reasons rr ON rr.id = cs.rejection_reason_id"
        "    WHERE rr.template_id = :id)",
        id=pin.row_id,
    )
    if in_use:
        summary["skipped"][key] = "in_use"
        return
    # Jawnie, nie przez kaskadę: FK powodów w modelu nie ma ``ondelete``.
    for table in ("rejection_reasons", "pipeline_stage_defs"):
        await db.execute(
            text(f"DELETE FROM {table} WHERE template_id = :id"), {"id": pin.row_id}
        )
    await db.execute(
        text("DELETE FROM pipeline_templates WHERE id = :id"), {"id": pin.row_id}
    )
    summary["deleted"]["pipeline_templates"] = [pin.row_id]


async def _smoke_contract_template(
    db: AsyncSession, plan: SettingsCleanupPlan, summary: dict[str, Any]
) -> None:
    pin = plan.contract_template
    key = f"contract_templates:{pin.row_id}"
    row = (
        await db.execute(
            text(
                "SELECT name, is_default FROM contract_templates WHERE id = :id FOR UPDATE"
            ),
            {"id": pin.row_id},
        )
    ).one_or_none()
    if row is None:
        summary["skipped"][key] = "missing"
        return
    if row.name != pin.name or row.is_default:
        summary["skipped"][key] = "fingerprint_mismatch"
        return
    summary["contracts_unlinked_from_template"] = await _count(
        db,
        "SELECT count(*) FROM contracts WHERE draft_template_id = :id",
        id=pin.row_id,
    )
    await db.execute(
        text("DELETE FROM contract_templates WHERE id = :id"), {"id": pin.row_id}
    )
    summary["deleted"]["contract_templates"] = [pin.row_id]


async def _retire_service_account(
    db: AsyncSession, plan: SettingsCleanupPlan, summary: dict[str, Any]
) -> None:
    pin = plan.service_account
    key = f"service_accounts:{pin.row_id}"
    slug = (
        await db.execute(
            text("SELECT slug FROM service_accounts WHERE id = :id FOR UPDATE"),
            {"id": pin.row_id},
        )
    ).scalar_one_or_none()
    if slug != pin.name:
        summary["skipped"][key] = "missing" if slug is None else "fingerprint_mismatch"
        return
    revoked = await db.execute(
        text(
            "UPDATE service_account_keys SET revoked_at = now(), revoke_reason = :reason "
            "WHERE service_account_id = :id AND revoked_at IS NULL"
        ),
        {"id": pin.row_id, "reason": REVOKE_REASON},
    )
    await db.execute(
        text(
            "UPDATE service_accounts SET is_active = false, updated_at = now() WHERE id = :id"
        ),
        {"id": pin.row_id},
    )
    summary["service_account_disabled"] = pin.row_id
    summary["service_account_keys_revoked"] = revoked.rowcount


_STEPS = (
    ("qa_clients", _qa_clients_out_of_settings),
    ("pipeline_template", _smoke_pipeline_template),
    ("contract_template", _smoke_contract_template),
    ("service_account", _retire_service_account),
)


async def run_settings_test_data_cleanup(
    db: AsyncSession,
    *,
    marker: str = REPAIR_MARKER,
    plan: SettingsCleanupPlan = PROD_PLAN,
) -> Optional[dict[str, Any]]:
    """Wykonaj sprzątanie raz; ``None`` = już wykonane. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "deleted": {},
        "history_rows_deleted": 0,
        "contracts_unlinked_from_template": 0,
        "service_account_disabled": None,
        "service_account_keys_revoked": 0,
        "skipped": {},
    }
    for step, run in _STEPS:
        before = copy.deepcopy(summary)
        try:
            async with db.begin_nested():
                await run(db, plan, summary)
        except IntegrityError as exc:
            # Powiązanie, którego inwentarz nie widział — pozycja zostaje,
            # a paragon nie może twierdzić, że coś z niej usunięto.
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            summary.clear()
            summary.update(before)
            summary["skipped"][step] = f"blocked_by_reference ({sqlstate})"
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("settings test data cleanup: %s", summarize_for_log(summary))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    deleted = ", ".join(
        f"{table} {len(ids)}" for table, ids in sorted(summary["deleted"].items())
    )
    return (
        f"deleted [{deleted or 'none'}], "
        f"history rows {summary['history_rows_deleted']}, "
        f"contracts unlinked {summary['contracts_unlinked_from_template']}, "
        f"service account keys revoked {summary['service_account_keys_revoked']}, "
        f"skipped {len(summary['skipped'])}"
    )


__all__ = [
    "PROD_PLAN",
    "REPAIR_MARKER",
    "PinnedNamed",
    "PinnedRow",
    "SettingsCleanupPlan",
    "run_settings_test_data_cleanup",
    "summarize_for_log",
]
