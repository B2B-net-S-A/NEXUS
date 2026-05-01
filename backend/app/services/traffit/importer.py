"""Orchestrator dla one-time migracji Traffit → Nexus.

Idempotent — drugi run = 0 inserts, N updates (te które się zmieniły).
Wzór: `talent_radar_importer.py` (ON CONFLICT (external_source, external_id)).

Phases (Faza 4):
- clients      → upsert do `clients`
- contacts     → upsert do `contacts` (lookup client_id po external_id)

Phases (Faza 5):
- users-map    → buduje (in-memory) mapę traffit_user_id → nexus_user_id po emailu
- workflows    → workflow → pipeline_templates + pipeline_stage_defs
- candidates   → upsert do `candidates` (employee → candidate, BEZ CV files)
- jobs         → upsert do `jobs` (recruitment → job z pipeline_template lookup)
- talents      → upsert do `talent_pools`

- reconcile    → counts Traffit vs Nexus dla wszystkich faz

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
    traffit_employee_to_candidate,
    traffit_recruitment_to_job,
    traffit_talent_to_pool,
    traffit_workflow_state_to_stage_def,
    traffit_workflow_to_template,
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


# ── Faza 5 UPSERT statements ─────────────────────────────────────────────────


_UPSERT_PIPELINE_TEMPLATE = text(
    """
    INSERT INTO pipeline_templates (
        external_id, external_source, name, description, is_default,
        archived, created_at, updated_at
    ) VALUES (
        :external_id, :external_source, :name, :description, :is_default,
        false, NOW(), NOW()
    )
    ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        name        = EXCLUDED.name,
        description = COALESCE(EXCLUDED.description, pipeline_templates.description),
        updated_at  = NOW()
    RETURNING id, (xmax = 0) AS was_insert
    """
)


_UPSERT_CANDIDATE = text(
    """
    INSERT INTO candidates (
        external_id, external_source, name, lastname, email, phone, linkedin,
        location, status, ai_summary, languages, cv_filename,
        cv_extracted_data, source, created_by,
        notes_count, champion, availability_status,
        linkedin_sync_status,
        created_at, updated_at
    ) VALUES (
        :external_id, :external_source, :name, :lastname, :email, :phone,
        :linkedin, :location,
        CAST(:status AS candidatestatus),
        :ai_summary,
        CAST(:languages AS JSONB),
        :cv_filename,
        CAST(:cv_extracted_data AS JSONB),
        :source, :created_by,
        0, false,
        CAST('unknown' AS availabilitystatus),
        CAST('disabled' AS linkedinsyncstatus),
        NOW(), NOW()
    )
    ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        name              = EXCLUDED.name,
        lastname          = EXCLUDED.lastname,
        email             = COALESCE(EXCLUDED.email, candidates.email),
        phone             = COALESCE(EXCLUDED.phone, candidates.phone),
        linkedin          = COALESCE(EXCLUDED.linkedin, candidates.linkedin),
        location          = COALESCE(EXCLUDED.location, candidates.location),
        status            = EXCLUDED.status,
        ai_summary        = COALESCE(EXCLUDED.ai_summary, candidates.ai_summary),
        languages         = EXCLUDED.languages,
        cv_filename       = COALESCE(EXCLUDED.cv_filename, candidates.cv_filename),
        cv_extracted_data = candidates.cv_extracted_data || EXCLUDED.cv_extracted_data,
        updated_at        = NOW()
    RETURNING id, (xmax = 0) AS was_insert
    """
)


_UPSERT_JOB = text(
    """
    INSERT INTO jobs (
        external_id, external_source, title, status, client_id,
        pipeline_template_id, recruiter_id, reference_number, deadline,
        custom_fields,
        remote_policy, priority, recruitment_type, work_mode, headcount,
        needs_sourcing,
        created_at, updated_at
    ) VALUES (
        :external_id, :external_source, :title,
        CAST(:status AS jobstatus),
        :client_id, :pipeline_template_id, :recruiter_id,
        :reference_number,
        CAST(:deadline AS DATE),
        CAST(:custom_fields AS JSONB),
        CAST('hybrid' AS remotepolicy),
        CAST('medium' AS jobpriority),
        CAST('body_leasing' AS recruitmenttype),
        CAST('fulltime' AS workmode),
        1, false,
        NOW(), NOW()
    )
    ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        title                = EXCLUDED.title,
        status               = EXCLUDED.status,
        client_id            = COALESCE(EXCLUDED.client_id, jobs.client_id),
        pipeline_template_id = COALESCE(
            EXCLUDED.pipeline_template_id, jobs.pipeline_template_id
        ),
        recruiter_id         = COALESCE(EXCLUDED.recruiter_id, jobs.recruiter_id),
        reference_number     = COALESCE(
            EXCLUDED.reference_number, jobs.reference_number
        ),
        deadline             = COALESCE(EXCLUDED.deadline, jobs.deadline),
        custom_fields        = jobs.custom_fields || EXCLUDED.custom_fields,
        updated_at           = NOW()
    RETURNING id, (xmax = 0) AS was_insert
    """
)


_UPSERT_TALENT_POOL = text(
    """
    INSERT INTO talent_pools (
        external_id, external_source, name, description, created_by,
        is_marketplace, created_at
    ) VALUES (
        :external_id, :external_source, :name, :description, :created_by,
        false, NOW()
    )
    ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        name        = EXCLUDED.name,
        description = COALESCE(EXCLUDED.description, talent_pools.description)
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
        """Compare counters Traffit vs Nexus dla wszystkich migrowanych encji."""
        report: dict[str, Any] = {}
        for entity, traffit_path, nexus_table in (
            ("clients", "/clients/", "clients"),
            ("contacts", "/crm_persons/", "contacts"),
            ("candidates", "/employees/", "candidates"),
            ("jobs", "/recruitments/", "jobs"),
            ("talent_pools", "/talents/", "talent_pools"),
            ("pipeline_templates", "/workflows/", "pipeline_templates"),
        ):
            try:
                t_count = await self.traffit.total_count(traffit_path)
            except Exception as e:  # noqa: BLE001
                report[entity] = {"error": f"traffit count failed: {e!r}"}
                continue
            n_count = await self.db.scalar(
                text(
                    f"SELECT count(*) FROM {nexus_table} "
                    f"WHERE external_source='traffit'"
                )
            )
            report[entity] = {
                "traffit": t_count,
                "nexus": int(n_count or 0),
                "match": t_count == int(n_count or 0),
            }
        return report

    # ── Faza 5 helpers ──────────────────────────────────────────────────────

    async def build_user_id_map(self) -> dict[str, int]:
        """Pull /users/ from Traffit, lookup by email in Nexus.

        Zwraca {traffit_user_id: nexus_user_id}. Brakujące (no email match)
        są pomijane — caller widzi mapping size.
        """
        traffit_users: list[dict[str, Any]] = []
        async for u in self.traffit.get_paginated(
            "/users/", page_size=self.batch_size
        ):
            traffit_users.append(u)

        emails = [
            (u.get("id"), (u.get("email") or "").strip().lower())
            for u in traffit_users
            if u.get("id") is not None and u.get("email")
        ]
        if not emails:
            return {}

        # Pull Nexus users by email
        result = await self.db.execute(
            text(
                "SELECT id, lower(email) AS email FROM users WHERE email IS NOT NULL"
            )
        )
        nexus_by_email: dict[str, int] = {row.email: row.id for row in result}

        return {
            str(traffit_id): nexus_by_email[email]
            for traffit_id, email in emails
            if email in nexus_by_email
        }

    async def _build_workflow_external_id_map(self) -> dict[str, int]:
        result = await self.db.execute(
            text(
                "SELECT id, external_id FROM pipeline_templates "
                "WHERE external_source='traffit' AND external_id IS NOT NULL"
            )
        )
        return {row.external_id: row.id for row in result}

    # ── Faza 5: workflows → pipeline_templates ──────────────────────────────

    async def import_workflows(self) -> PhaseProgress:
        progress = PhaseProgress(
            phase="workflows", started_at=datetime.now(timezone.utc)
        )
        try:
            progress.total_source = await self.traffit.total_count("/workflows/")
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        async for raw in self.traffit.get_paginated(
            "/workflows/", page_size=self.batch_size
        ):
            progress.processed += 1
            try:
                # Workflow detail (z `states`) — list view zwraca tylko id/name
                wf_id = raw.get("id")
                detail_resp = await self.traffit._get_raw(  # noqa: SLF001
                    f"/workflows/{wf_id}", page=1, page_size=1
                )
                if detail_resp.status_code != 200:
                    progress.add_error(
                        f"workflow {wf_id} detail HTTP {detail_resp.status_code}"
                    )
                    continue
                detail = detail_resp.json()
                template_payload = traffit_workflow_to_template(detail)
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map workflow id={raw.get('id')}: {e!r}")
                continue

            if self.dry_run:
                progress.inserted += 1
                continue
            try:
                tmpl_result = await self.db.execute(
                    _UPSERT_PIPELINE_TEMPLATE, template_payload
                )
                tmpl_row = tmpl_result.fetchone()
                if tmpl_row is None:
                    continue
                template_id = tmpl_row[0]
                if tmpl_row[1]:
                    progress.inserted += 1
                else:
                    progress.updated += 1

                # Stage defs — sortuj po `order`, potem mapuj kolejność 0..N
                states = detail.get("states") or []
                states_sorted = sorted(
                    states, key=lambda s: (s.get("order") or 0, s.get("id") or 0)
                )
                # Replace existing stages for this template (clean slate)
                await self.db.execute(
                    text(
                        "DELETE FROM pipeline_stage_defs WHERE template_id=:tid"
                    ),
                    {"tid": template_id},
                )
                for idx, state in enumerate(states_sorted):
                    sd = traffit_workflow_state_to_stage_def(state, idx)
                    await self.db.execute(
                        text(
                            """
                            INSERT INTO pipeline_stage_defs (
                                template_id, name, "order",
                                category, is_terminal, terminal_type,
                                legacy_enum_value,
                                tracker_enabled, scorecard_schema,
                                created_at, updated_at
                            ) VALUES (
                                :template_id, :name, :order,
                                CAST(:category AS stagecategoryenum),
                                :is_terminal,
                                CASE WHEN :terminal_type IS NULL THEN NULL
                                     ELSE CAST(:terminal_type AS terminaltype) END,
                                :legacy_enum_value,
                                false, '{}'::jsonb,
                                NOW(), NOW()
                            )
                            """
                        ),
                        {
                            "template_id": template_id,
                            "name": sd["name"],
                            "order": sd["order"],
                            "category": sd["category"],
                            "is_terminal": sd["is_terminal"],
                            "terminal_type": sd.get("terminal_type"),
                            "legacy_enum_value": sd["legacy_enum_value"],
                        },
                    )
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert workflow ext={template_payload.get('external_id')}: {e!r}"
                )
                await self.db.rollback()

        if not self.dry_run:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Workflows import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    # ── Faza 5: candidates ──────────────────────────────────────────────────

    async def import_candidates(self) -> PhaseProgress:
        progress = PhaseProgress(
            phase="candidates", started_at=datetime.now(timezone.utc)
        )
        try:
            progress.total_source = await self.traffit.total_count("/employees/")
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        user_map = await self.build_user_id_map()
        logger.info("Candidates: user_id_map size=%d", len(user_map))

        commit_every = 500
        since_commit = 0

        async for raw in self.traffit.get_paginated(
            "/employees/", page_size=self.batch_size
        ):
            progress.processed += 1
            try:
                payload = traffit_employee_to_candidate(raw, user_map)
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map employee id={raw.get('id')}: {e!r}")
                continue
            if self.dry_run:
                progress.inserted += 1
                continue
            try:
                params = dict(payload)
                params["languages"] = json.dumps(payload["languages"])
                params["cv_extracted_data"] = json.dumps(
                    payload["cv_extracted_data"]
                )
                result = await self.db.execute(_UPSERT_CANDIDATE, params)
                row = result.fetchone()
                if row is None:
                    continue
                if row[1]:
                    progress.inserted += 1
                else:
                    progress.updated += 1
                since_commit += 1
                if since_commit >= commit_every:
                    await self.db.commit()
                    since_commit = 0
                    logger.info(
                        "Candidates progress: %d/%d",
                        progress.processed,
                        progress.total_source,
                    )
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert candidate ext={payload.get('external_id')}: {e!r}"
                )
                await self.db.rollback()
                since_commit = 0

        if not self.dry_run and since_commit > 0:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Candidates import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    # ── Faza 5: jobs ────────────────────────────────────────────────────────

    async def import_jobs(self) -> PhaseProgress:
        progress = PhaseProgress(
            phase="jobs", started_at=datetime.now(timezone.utc)
        )
        try:
            progress.total_source = await self.traffit.total_count("/recruitments/")
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        client_map = await self._build_client_external_id_map()
        workflow_map = await self._build_workflow_external_id_map()
        user_map = await self.build_user_id_map()
        logger.info(
            "Jobs lookup maps: clients=%d workflows=%d users=%d",
            len(client_map),
            len(workflow_map),
            len(user_map),
        )

        async for raw in self.traffit.get_paginated(
            "/recruitments/", page_size=self.batch_size
        ):
            progress.processed += 1
            try:
                payload = traffit_recruitment_to_job(
                    raw, client_map, workflow_map, user_map
                )
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map recruitment id={raw.get('id')}: {e!r}")
                continue

            # Skip jobs bez znanego klienta (NOT NULL constraint na client_id
            # nie ma — pole jest nullable — ale rzadko sensowne mieć job
            # bez klienta. Logujemy jako skipped dla audit.)
            if payload.get("client_id") is None:
                progress.skipped += 1
                if len(progress.error_samples) < 20:
                    progress.error_samples.append(
                        f"skip job ext={payload['external_id']}: no client mapping"
                    )
                continue

            if self.dry_run:
                progress.inserted += 1
                continue
            try:
                params = dict(payload)
                params["custom_fields"] = json.dumps(payload["custom_fields"])
                result = await self.db.execute(_UPSERT_JOB, params)
                row = result.fetchone()
                if row is None:
                    continue
                if row[1]:
                    progress.inserted += 1
                else:
                    progress.updated += 1
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert job ext={payload.get('external_id')}: {e!r}"
                )
                await self.db.rollback()

        if not self.dry_run:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Jobs import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    # ── Faza 5: talents ─────────────────────────────────────────────────────

    async def import_talents(self) -> PhaseProgress:
        progress = PhaseProgress(
            phase="talents", started_at=datetime.now(timezone.utc)
        )
        try:
            progress.total_source = await self.traffit.total_count("/talents/")
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        user_map = await self.build_user_id_map()

        async for raw in self.traffit.get_paginated(
            "/talents/", page_size=self.batch_size
        ):
            progress.processed += 1
            try:
                payload = traffit_talent_to_pool(raw, user_map)
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map talent id={raw.get('id')}: {e!r}")
                continue
            if self.dry_run:
                progress.inserted += 1
                continue
            try:
                result = await self.db.execute(_UPSERT_TALENT_POOL, payload)
                row = result.fetchone()
                if row is None:
                    continue
                if row[1]:
                    progress.inserted += 1
                else:
                    progress.updated += 1
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert talent ext={payload.get('external_id')}: {e!r}"
                )
                await self.db.rollback()

        if not self.dry_run:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Talents import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress
