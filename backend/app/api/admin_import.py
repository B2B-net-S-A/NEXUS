"""
Admin-only endpoints for importing data from external sources: Nordea orders
(CSV), Centrum e-Zdrowia MD orders (manifest) and the read-only receipt of the
live order-contract repair (migration 0250).

Import z TalentRadaru (``/api/admin/import-talent-radar``, ``/api/admin/import-tasks``)
usunięty 25.11.2026: źródło (projekt Supabase) wyeksportowano poza repo, a zmienna
``TALENT_RADAR_DSN`` zniknęła z Coolify.

RBAC: AdminUser only.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.schemas.ezdrowie_md_seed import EzdrowieMdSeedManifest
from app.services.contract_order_sync import sync_pending_order_contracts
from app.services.ezdrowie import is_ezdrowie_client
from app.services.ezdrowie_md_seed import EzdrowieMdSeedBlocked, run_ezdrowie_md_seed
from app.services.order_write_errors import commit_order_write
from app.services.nordea_order_import import (
    MAX_NORDEA_IMPORT_BYTES,
    NordeaImportError,
    import_nordea_orders,
    parse_nordea_csv,
    payload_sha256,
)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class LiveOrderContractRepairAudit(BaseModel):
    """Read-only receipt written by migration 0250."""

    key: str
    value: dict
    updated_at: datetime


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/admin/audits/live-order-contract-repair",
    response_model=LiveOrderContractRepairAudit,
)
async def get_live_order_contract_repair_audit(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Return the targeted repair's wider, read-only production audit."""

    key = "0250_live_order_contract_repair"
    row = await db.get(AppSetting, key)
    if row is None:
        raise HTTPException(404, detail="Audyt nie został jeszcze wykonany")
    return LiveOrderContractRepairAudit(
        key=row.key,
        value=row.value,
        updated_at=row.updated_at,
    )


@router.post("/admin/clients/{client_id}/nordea-orders/import")
async def import_nordea_client_orders(
    client_id: int,
    admin: AdminUser,
    dry_run: bool = Query(True),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Preview or apply the validated Nordea order/framework-rate CSV."""

    filename = file.filename or "Nordea.csv"
    if not filename.casefold().endswith(".csv"):
        raise HTTPException(422, detail="Import wymaga pliku CSV")
    payload = await file.read(MAX_NORDEA_IMPORT_BYTES + 1)
    if len(payload) > MAX_NORDEA_IMPORT_BYTES:
        raise HTTPException(413, detail="Plik CSV przekracza limit 2 MB")
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise HTTPException(404, detail="Client not found")

    try:
        rows = parse_nordea_csv(payload)
        report = await import_nordea_orders(
            db,
            client=client,
            rows=rows,
            filename=filename,
            user_id=admin.id,
            dry_run=dry_run,
            sha256=payload_sha256(payload),
        )
        if dry_run:
            await db.rollback()
        else:
            if report["unmatched_file"] or report["ambiguous_file"]:
                await db.rollback()
                raise HTTPException(
                    409,
                    detail={
                        "message": (
                            "Import nie został zapisany: najpierw rozwiąż "
                            "niedopasowane lub niejednoznaczne osoby z podglądu."
                        ),
                        "unmatched": len(report["unmatched_file"]),
                        "ambiguous": len(report["ambiguous_file"]),
                    },
                )
            db.add(
                Activity(
                    entity_type="client",
                    entity_id=client_id,
                    action="nordea_orders_imported",
                    user_id=admin.id,
                    external_source="nordea_csv",
                    details={
                        key: report[key]
                        for key in (
                            "filename",
                            "sha256",
                            "rows_total",
                            "contractors_in_file",
                            "matched_contractors",
                            "orders_created",
                            "orders_updated",
                            "orders_unchanged",
                            "contracts_revived",
                            "framework_created",
                            "framework_updated",
                            "framework_unchanged",
                        )
                    },
                )
            )
            # Import zapisuje zamówienia poza `commit_order_write` — kontrakty
            # tych osób dostają okres i stawkę przychodową tą samą regułą.
            await sync_pending_order_contracts(db, actor_id=admin.id)
            await db.commit()
        return report
    except NordeaImportError as exc:
        await db.rollback()
        raise HTTPException(422, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise


# ── Centrum e-Zdrowia: jednorazowy import zamówień MD z manifestu (Faza C) ────


@router.post("/admin/clients/{client_id}/ezdrowie-md-orders/import")
async def import_ezdrowie_md_orders(
    client_id: int,
    manifest: EzdrowieMdSeedManifest,
    admin: AdminUser,
    dry_run: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """Podgląd (``dry_run=true``) albo zapis kart zamówień MD z manifestu.

    Manifest (nazwiska, stawki, historia miesięczna) żyje poza repozytorium.
    Dry-run przechodzi DOKŁADNIE tę samą ścieżką co zapis i kończy się
    rollbackiem — raport pokazuje dopasowania osób (``ambiguous``/``missing``
    do rozstrzygnięcia w manifeście) i policzone zużycie. Apply z jakimkolwiek
    blokerem = 409 i nic nie zapisane.
    """
    if manifest.client_id != client_id:
        raise HTTPException(422, detail="client_id w manifeście różni się od ścieżki")
    if not is_ezdrowie_client(client_id):
        raise HTTPException(
            422,
            detail="Import zamówień MD z manifestu dotyczy wyłącznie Centrum e-Zdrowia",
        )
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise HTTPException(404, detail="Client not found")
    try:
        report = await run_ezdrowie_md_seed(
            db, manifest=manifest, user_id=admin.id, dry_run=dry_run
        )
    except EzdrowieMdSeedBlocked as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "message": (
                    "Import nie został zapisany: najpierw rozwiąż blokery z podglądu."
                ),
                "blockers": exc.report.blockers,
                "report": exc.report.model_dump(mode="json"),
            },
        ) from exc
    except Exception:
        await db.rollback()
        raise
    if dry_run:
        await db.rollback()
        return report.model_dump(mode="json")
    await commit_order_write(db, actor_id=admin.id)
    return report.model_dump(mode="json")
