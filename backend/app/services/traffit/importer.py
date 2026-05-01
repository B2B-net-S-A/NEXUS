"""Orchestrator dla one-time migracji Traffit → Nexus.

Idempotent — drugi run = 0 inserts, N updates (te które się zmieniły).
Wzór: `talent_radar_importer.py` (ON CONFLICT (external_source, external_id)).

Phases:
- clients   → upsert do `clients`
- contacts  → upsert do `contacts` (z lookup client_id po external_id)
- reconcile → counts Traffit vs Nexus, zapis raportu

Orphan handling: kontakty bez przypisanego klienta lub z nieznanym client_id
trafiają do specjalnego klienta `__traffit_orphans` (auto-utworzony, status=inactive).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.services.traffit.client import TraffitClient
from app.services.traffit.mappers import (
    traffit_client_to_nexus,
    traffit_crm_person_to_nexus,
)

logger = logging.getLogger(__name__)


ORPHAN_CLIENT_NAME = "__traffit_orphans"


@dataclass
class PhaseProgress:
    phase: str
    processed: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    total_source: int = 0
    error_samples: list[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def add_error(self, msg: str) -> None:
        self.errors += 1
        if len(self.error_samples) < 20:
            self.error_samples.append(msg)

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "processed": self.processed,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "total_source": self.total_source,
            "error_samples": self.error_samples[:20],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


# ── UPSERT statements (raw SQL — explicit DDL preference per repo style) ─────


_UPSERT_CLIENT = text(
    """
    INSERT INTO clients (
        external_id, external_source, name, status, notes,
        nda_signed, created_at, updated_at
    ) VALUES (
        :external_id, :external_source, :name,
        CAST(:status AS clientstatus),
        :notes, false, NOW(), NOW()
    )
    ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        name       = EXCLUDED.name,
        status     = EXCLUDED.status,
        notes      = COALESCE(EXCLUDED.notes, clients.notes),
        updated_at = NOW()
    RETURNING id, (xmax = 0) AS was_insert
    """
)


_UPSERT_CONTACT = text(
    """
    INSERT INTO contacts (
        external_id, external_source, client_id, name, email, phone,
        position, department, is_decision_maker, notes, created_at
    ) VALUES (
        :external_id, :external_source, :client_id, :name, :email, :phone,
        :position, :department, :is_decision_maker, :notes, NOW()
    )
    ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        client_id          = EXCLUDED.client_id,
        name               = EXCLUDED.name,
        email              = COALESCE(EXCLUDED.email, contacts.email),
        phone              = COALESCE(EXCLUDED.phone, contacts.phone),
        position           = COALESCE(EXCLUDED.position, contacts.position),
        department         = COALESCE(EXCLUDED.department, contacts.department),
        is_decision_maker  = EXCLUDED.is_decision_maker,
        notes              = COALESCE(EXCLUDED.notes, contacts.notes)
    RETURNING id, (xmax = 0) AS was_insert
    """
)


# ── Importer ─────────────────────────────────────────────────────────────────


class TraffitImporter:
    """Run one-time migration phases. Idempotent — safe to re-run."""

    def __init__(
        self,
        traffit: TraffitClient,
        db: AsyncSession,
        *,
        dry_run: bool = False,
        batch_size: int = 200,
    ) -> None:
        self.traffit = traffit
        self.db = db
        self.dry_run = dry_run
        self.batch_size = batch_size

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _ensure_orphan_client(self) -> int:
        """Get-or-create the `__traffit_orphans` client. Returns its Nexus id."""
        result = await self.db.execute(
            select(Client.id).where(Client.name == ORPHAN_CLIENT_NAME)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        if self.dry_run:
            logger.info("[dry-run] would create orphan client '%s'", ORPHAN_CLIENT_NAME)
            return -1

        # Use literal SQL to avoid touching ClientStatus enum imports here
        result = await self.db.execute(
            text(
                """
                INSERT INTO clients (name, status, notes, nda_signed, created_at, updated_at)
                VALUES (:name, CAST(:status AS clientstatus), :notes, false, NOW(), NOW())
                RETURNING id
                """
            ),
            {
                "name": ORPHAN_CLIENT_NAME,
                "status": "inactive",
                "notes": (
                    "Auto-utworzony przez Traffit importer dla osób kontaktowych "
                    "bez przypisanego klienta. Po migracji można je ręcznie "
                    "przenieść do właściwych klientów lub usunąć cały bucket."
                ),
            },
        )
        new_id = result.scalar_one()
        await self.db.commit()
        logger.info("Created orphan client (id=%d)", new_id)
        return new_id

    async def _build_client_external_id_map(self) -> dict[str, int]:
        """Pull current Nexus state: external_id (Traffit) → Nexus client.id."""
        result = await self.db.execute(
            select(Client.id, Client.external_id).where(
                Client.external_source == "traffit",
                Client.external_id.is_not(None),
            )
        )
        return {ext: nid for nid, ext in result.all() if ext is not None}

    # ── Phase: clients ──────────────────────────────────────────────────────

    async def import_clients(self) -> PhaseProgress:
        progress = PhaseProgress(phase="clients", started_at=datetime.now(timezone.utc))
        try:
            progress.total_source = await self.traffit.total_count("/clients/")
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        async for raw in self.traffit.get_paginated(
            "/clients/", page_size=self.batch_size
        ):
            progress.processed += 1
            try:
                payload = traffit_client_to_nexus(raw)
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map client id={raw.get('id')}: {e!r}")
                continue
            if self.dry_run:
                progress.inserted += 1  # treat as would-insert
                continue
            try:
                result = await self.db.execute(_UPSERT_CLIENT, payload)
                row = result.fetchone()
                if row is None:
                    continue
                if row[1]:
                    progress.inserted += 1
                else:
                    progress.updated += 1
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert client ext={payload.get('external_id')}: {e!r}"
                )
                await self.db.rollback()

        if not self.dry_run:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Clients import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    # ── Phase: contacts (crm_persons) ───────────────────────────────────────

    async def import_contacts(self) -> PhaseProgress:
        progress = PhaseProgress(
            phase="contacts", started_at=datetime.now(timezone.utc)
        )
        try:
            progress.total_source = await self.traffit.total_count("/crm_persons/")
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        client_map = await self._build_client_external_id_map()
        orphan_id = await self._ensure_orphan_client()

        async for raw in self.traffit.get_paginated(
            "/crm_persons/", page_size=self.batch_size
        ):
            progress.processed += 1
            try:
                payload = traffit_crm_person_to_nexus(raw, client_map, orphan_id)
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map crm_person id={raw.get('id')}: {e!r}")
                continue
            if self.dry_run:
                progress.inserted += 1
                continue
            try:
                result = await self.db.execute(_UPSERT_CONTACT, payload)
                row = result.fetchone()
                if row is None:
                    continue
                if row[1]:
                    progress.inserted += 1
                else:
                    progress.updated += 1
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert contact ext={payload.get('external_id')}: {e!r}"
                )
                await self.db.rollback()

        if not self.dry_run:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Contacts import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    # ── Phase: reconcile ────────────────────────────────────────────────────

    async def reconcile(self) -> dict[str, Any]:
        """Compare counters Traffit vs Nexus."""
        traffit_clients = await self.traffit.total_count("/clients/")
        traffit_contacts = await self.traffit.total_count("/crm_persons/")

        nexus_clients = await self.db.scalar(
            text(
                "SELECT count(*) FROM clients WHERE external_source='traffit'"
            )
        )
        nexus_contacts = await self.db.scalar(
            text(
                "SELECT count(*) FROM contacts WHERE external_source='traffit'"
            )
        )
        return {
            "clients": {
                "traffit": traffit_clients,
                "nexus": int(nexus_clients or 0),
                "match": traffit_clients == int(nexus_clients or 0),
            },
            "contacts": {
                "traffit": traffit_contacts,
                "nexus": int(nexus_contacts or 0),
                "match": traffit_contacts == int(nexus_contacts or 0),
            },
        }
