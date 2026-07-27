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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.services.traffit.client import TraffitClient
from app.services.traffit.mappers import (
    select_all_files_with_priority,
    select_primary_cv_file,
    traffit_activity_to_activity,
    traffit_client_to_nexus,
    traffit_crm_person_to_nexus,
    traffit_employee_to_candidate,
    traffit_recruitment_history_to_stage,
    traffit_recruitment_to_job,
    traffit_source_to_candidate_tag,
    traffit_talent_to_pool,
    traffit_user_to_nexus,
    traffit_workflow_state_to_stage_def,
    traffit_workflow_to_template,
)
from app.services.traffit.rejection_backfill import (
    backfill_rejection_descriptions_from_activities,
    backfill_rejection_notes_from_activities,
)

logger = logging.getLogger(__name__)


ORPHAN_CLIENT_NAME = "__traffit_orphans"
_CV_FILENAME_RE = re.compile(
    r"(^|[^a-z])(cv|resume|curriculum)([^a-z]|$)",
    re.IGNORECASE,
)


def _traffit_document_kind(filename: str, *, is_primary: bool) -> str:
    """Conservative classification: ambiguous Traffit attachments stay other."""

    if is_primary or _CV_FILENAME_RE.search(filename):
        return "cv"
    return "other"


@dataclass
class PhaseProgress:
    phase: str
    processed: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    total_source: int = 0
    # Notes promoted from activities → notes table (only set by the activities
    # phase). Surfaced so the daily sync can report "no notatka missing".
    notes_promoted: int = 0
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
            "notes_promoted": self.notes_promoted,
            "error_samples": self.error_samples[:20],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


@dataclass(frozen=True)
class WithdrawnReasonFallback:
    """Warstwowy fallback ``rejection_reason_id`` dla ruchów legacy ``withdrawn``.

    DB wymusza ``ck_candidate_stages_withdrawn_requires_reason``
    (stage='withdrawn' ⇒ rejection_reason_id NOT NULL, migracja 0068), a
    Traffit ``recruitment_history`` nie niesie powodu.

    Pierwotna wersja rozwiązywała powód WYŁĄCZNIE przez ``jobs.pipeline_template_id``.
    Na produkcji 4058 z 4075 jobów ma ten FK NULL (99,6%), więc mapa pokrywała
    17 jobów i praktycznie każdy ruch ``withdrawn`` padał na constraincie —
    324 błędy fazy ``pipelines`` na KAŻDYM syncu i permanentny
    ``checks.traffit=degraded``.

    Kolejność rozwiązywania (pierwszy trafiony wygrywa):

    1. ``by_job`` — template joba (zachowuje dotychczasową semantykę tam,
       gdzie job faktycznie ma pipeline),
    2. ``by_stage_def`` — template definicji etapu, z której przyszedł ruch
       (workflow Traffita, w którym ten stan ``withdrawn`` istnieje),
    3. ``default_id`` — ``legacy_unknown`` domyślnego template'u (globalna
       siatka bezpieczeństwa).

    Wszystkie warstwy wskazują ten sam seed co backfill 0068: ``legacy_unknown``
    (category='withdrawn', ``active=false``, order 999), więc powód nigdy nie
    trafia do pick-listy rekrutera ani nie udaje realnej przyczyny wycofania.
    """

    by_job: dict[int, int] = field(default_factory=dict)
    by_stage_def: dict[int, int] = field(default_factory=dict)
    default_id: Optional[int] = None

    def resolve(
        self,
        legacy_enum: str,
        job_id: Optional[int],
        stage_def_id: Optional[int],
    ) -> Optional[int]:
        """Fallback TYLKO dla ``withdrawn`` (constraint tego wymaga).

        ``rejected``/inne przechodzą z NULL — realny powód uzupełnia
        ``rejection_backfill`` z activities, a ręczne ruchy rekruterów mają
        własny wybór z UI.
        """
        if legacy_enum != "withdrawn":
            return None
        if job_id is not None:
            hit = self.by_job.get(job_id)
            if hit is not None:
                return hit
        if stage_def_id is not None:
            hit = self.by_stage_def.get(stage_def_id)
            if hit is not None:
                return hit
        return self.default_id


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
        CAST(:external_id AS varchar(100)),
        CAST(:external_source AS varchar(50)),
        CAST(:name AS varchar(100)),
        CAST(:description AS text),
        CAST(:is_default AS boolean),
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
        location, status, profile_about, languages, cv_filename,
        cv_extracted_data, source, created_by,
        notes_count, champion, availability_status,
        linkedin_sync_status,
        created_at, updated_at
    ) VALUES (
        :external_id, :external_source, :name, :lastname, :email, :phone,
        :linkedin, :location,
        CAST(:status AS candidatestatus),
        :profile_about,
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
        profile_about     = COALESCE(
            EXCLUDED.profile_about,
            candidates.profile_about
        ),
        languages         = EXCLUDED.languages,
        cv_filename       = COALESCE(EXCLUDED.cv_filename, candidates.cv_filename),
        cv_extracted_data = candidates.cv_extracted_data || EXCLUDED.cv_extracted_data,
        updated_at        = NOW()
    RETURNING id, (xmax = 0) AS was_insert
    """
)


# Used when a Traffit candidate's email matches an existing record
# (e.g. seeded from talent_radar). Adopt the row as Traffit-sourced and
# stash the previous external_source under cv_extracted_data.legacy_source
# so we don't lose origin attribution.
_UPDATE_CANDIDATE_ADOPT = text(
    """
    UPDATE candidates
    SET external_source = CAST(:external_source AS varchar(50)),
        external_id     = CAST(:external_id AS varchar(100)),
        name            = CAST(:name AS varchar(100)),
        lastname        = CAST(:lastname AS varchar(100)),
        phone           = COALESCE(CAST(:phone AS varchar(50)), candidates.phone),
        linkedin        = COALESCE(CAST(:linkedin AS varchar(255)), candidates.linkedin),
        location        = COALESCE(CAST(:location AS varchar(255)), candidates.location),
        status          = CAST(:status AS candidatestatus),
        profile_about   = COALESCE(
            CAST(:profile_about AS text),
            candidates.profile_about
        ),
        languages       = CAST(:languages AS JSONB),
        cv_filename     = COALESCE(CAST(:cv_filename AS varchar(255)),
                                   candidates.cv_filename),
        cv_extracted_data = candidates.cv_extracted_data
                            || CAST(:cv_extracted_data AS JSONB)
                            || jsonb_build_object(
                                 'legacy_source', candidates.external_source
                               ),
        updated_at      = NOW()
    WHERE id = :nexus_id
    RETURNING id
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


# ── Faza A UPSERT statements ─────────────────────────────────────────────────


# Insert NEW Traffit-imported user. password_hash placeholder = bcrypt-invalid,
# is_active=false zwykle (zachowuje payload Traffit). Idempotent na
# (external_source, external_id).
_UPSERT_USER = text(
    """
    INSERT INTO users (
        external_id, external_source, email, name, role,
        is_active, password_hash, profile_completed,
        created_at, updated_at
    ) VALUES (
        CAST(:external_id AS varchar(100)),
        CAST(:external_source AS varchar(50)),
        CAST(:email AS varchar(255)),
        CAST(:name AS varchar(255)),
        CAST(:role AS userrole),
        CAST(:is_active AS boolean),
        CAST(:password_hash AS varchar(255)),
        true,
        NOW(), NOW()
    )
    ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        name      = EXCLUDED.name,
        role      = EXCLUDED.role,
        is_active = EXCLUDED.is_active,
        updated_at = NOW()
    RETURNING id, (xmax = 0) AS was_insert
    """
)

# Mark istniejącego (po email) Nexus usera jako Traffit-imported. Nie zmienia
# password_hash/role (zachowuje istniejący Nexus account).
_UPDATE_USER_ADOPT = text(
    """
    UPDATE users
    SET external_id     = CAST(:external_id AS varchar(100)),
        external_source = CAST(:external_source AS varchar(50)),
        updated_at      = NOW()
    WHERE id = :nexus_id
    RETURNING id
    """
)


# Insert/UPSERT candidate document. external_id format: "<emp_id>-<file_id>".
# `is_primary` może być TRUE tylko dla jednego pliku per kandydat (caller
# odpowiada za logikę markowania — patrz select_all_files_with_priority).
#
# Po migracji do Hetzner Object Storage (audit-2026-05-07): file_content jest
# NULL (legacy fallback), a binary content trzymany w S3 pod kluczem
# `storage_key`. Caller wysyła plik do S3 PRZED wywołaniem tego UPSERT.
_UPSERT_CANDIDATE_DOCUMENT = text(
    """
    INSERT INTO candidate_documents (
        candidate_id, filename, storage_key, content_type,
        size_bytes, document_kind, is_primary, uploaded_at,
        external_id, external_source,
        created_at, updated_at
    ) VALUES (
        CAST(:candidate_id AS integer),
        CAST(:filename AS varchar(500)),
        CAST(:storage_key AS varchar(500)),
        CAST(:content_type AS varchar(100)),
        CAST(:size_bytes AS integer),
        CAST(:document_kind AS candidatedocumentkind),
        CAST(:is_primary AS boolean),
        :uploaded_at,
        CAST(:external_id AS varchar(100)),
        CAST(:external_source AS varchar(50)),
        NOW(), NOW()
    )
    ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        filename     = EXCLUDED.filename,
        storage_key  = COALESCE(EXCLUDED.storage_key, candidate_documents.storage_key),
        content_type = COALESCE(EXCLUDED.content_type, candidate_documents.content_type),
        size_bytes   = COALESCE(EXCLUDED.size_bytes, candidate_documents.size_bytes),
        document_kind = EXCLUDED.document_kind,
        is_primary   = EXCLUDED.is_primary,
        uploaded_at  = COALESCE(EXCLUDED.uploaded_at, candidate_documents.uploaded_at),
        updated_at   = NOW()
    RETURNING id, (xmax = 0) AS was_insert
    """
)


# Promote Traffit candidate notes (held in `activities`) into the dedicated
# `notes` table so the candidate "Notatki" UI shows them. This is the exact
# logic from Alembic 0077 — lifted here so it runs on every sync (the migration
# was one-time). Idempotent via NOT EXISTS (candidate_id, created_at), which is
# safe against the ~43k notes already promoted by 0077 (same created_at as their
# source activity). New rows are stamped source_ref='traffit:activity:<id>' for
# traceability. The /*SINCE*/ placeholder is replaced with a created_at cutoff
# in delta mode (empty string in full mode).
_PROMOTE_NOTES_SQL = """
INSERT INTO notes (
    candidate_id, content, note_type, author_id, source_ref,
    created_at, updated_at
)
SELECT
    a.entity_id,
    LEFT(
        COALESCE(
            a.details #>> '{content,content}',
            a.details ->> 'content',
            ''
        ),
        50000
    ),
    CASE
        WHEN a.action = 'traffit:Email' THEN 'email'::notetype
        WHEN a.action = 'traffit:Reply' THEN 'email'::notetype
        WHEN a.action = 'traffit:Rozmowa telefoniczna' THEN 'call'::notetype
        WHEN a.action = 'traffit:Spotkanie' THEN 'meeting'::notetype
        WHEN a.details ->> 'traffit_type_value' ILIKE '%interview%'
            THEN 'interview'::notetype
        ELSE 'general'::notetype
    END,
    a.user_id,
    'traffit:activity:' || a.external_id,
    a.created_at,
    a.updated_at
FROM activities a
WHERE a.external_source = 'traffit'
  AND a.action IN (
      'traffit:Notatka',
      'traffit:Email',
      'traffit:Reply',
      'traffit:Rozmowa telefoniczna',
      'traffit:Spotkanie'
  )
  AND a.entity_type = 'candidate'
  AND a.entity_id IS NOT NULL
  AND COALESCE(
      a.details #>> '{content,content}',
      a.details ->> 'content',
      ''
  ) <> ''
  /*SINCE*/
  AND NOT EXISTS (
      SELECT 1 FROM notes n
      WHERE n.candidate_id = a.entity_id
        AND n.created_at = a.created_at
  )
"""


# ── Importer ─────────────────────────────────────────────────────────────────


class TraffitImporter:
    """Run one-time migration phases. Idempotent — safe to re-run."""

    def __init__(
        self,
        traffit: TraffitClient,
        db: AsyncSession,
        *,
        dry_run: bool = False,
        batch_size: int = 100,
    ) -> None:
        self.traffit = traffit
        self.db = db
        self.dry_run = dry_run
        self.batch_size = batch_size

    # ── Delta helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _delta_filter(field_name: str, since: Optional[datetime]) -> Optional[dict]:
        """Build a Traffit ``X-Request-Filter`` dict for an incremental sync.

        Day-granular (the discovery doc's documented format is a date string),
        which is fine for a daily job — the caller applies a generous lookback
        window and all upserts are idempotent, so the boundary day is never
        missed. ``None`` since → full scan (no filter).
        """
        if since is None:
            return None
        return {
            field_name: {
                "value": since.strftime("%Y-%m-%d"),
                "comparison": ">=",
            }
        }

    async def promote_notes(self, since: Optional[datetime] = None) -> int:
        """Promote Traffit candidate activities → `notes` table (idempotent).

        Replicates Alembic 0077 so new Traffit notes/emails/calls/meetings reach
        the candidate "Notatki" UI on every sync. Returns rows inserted.
        """
        if self.dry_run:
            return 0
        since_clause = ""
        params: dict[str, Any] = {}
        if since is not None:
            since_clause = "AND a.created_at >= :since"
            params["since"] = since
        sql = _PROMOTE_NOTES_SQL.replace("/*SINCE*/", since_clause)
        result = await self.db.execute(text(sql), params)
        await self.db.commit()
        return result.rowcount or 0

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
        async for u in self.traffit.get_paginated("/users/", page_size=self.batch_size):
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
            text("SELECT id, lower(email) AS email FROM users WHERE email IS NOT NULL")
        )
        nexus_by_email: dict[str, int] = {row.email: row.id for row in result}

        return {
            str(traffit_id): nexus_by_email[email]
            for traffit_id, email in emails
            if email in nexus_by_email
        }

    # ── Faza A: users import ────────────────────────────────────────────────

    async def import_users(self) -> PhaseProgress:
        """Import 141 Traffit users → Nexus users.

        Logika:
        - Email match istniejący Nexus user → UPDATE z external_id (adopt)
        - Brak match → INSERT nowy disabled user (is_active=false,
          password_hash placeholder, role z permission_group)

        Po imporcie `build_user_id_map` zwróci 141 entries (zamiast 1-10),
        co umożliwia poprawną atrybucję re-runu activities/pipelines.
        """
        progress = PhaseProgress(phase="users", started_at=datetime.now(timezone.utc))
        try:
            progress.total_source = await self.traffit.total_count("/users/")
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        # Pre-load istniejących Nexus users `email → id` (case-insensitive)
        result = await self.db.execute(
            text(
                "SELECT id, lower(email) AS email FROM users "
                "WHERE email IS NOT NULL AND email <> ''"
            )
        )
        nexus_email_to_id: dict[str, int] = {
            row.email: row.id for row in result.fetchall() if row.email
        }
        logger.info("Users import: existing Nexus users %d", len(nexus_email_to_id))

        async for raw in self.traffit.get_paginated(
            "/users/", page_size=self.batch_size
        ):
            progress.processed += 1
            try:
                payload = traffit_user_to_nexus(raw)
            except ValueError as e:
                # Missing email or id — skip, log
                progress.skipped += 1
                if len(progress.error_samples) < 20:
                    progress.error_samples.append(
                        f"skip user id={raw.get('id')}: {e!s}"
                    )
                continue
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map user id={raw.get('id')}: {e!r}")
                continue

            if self.dry_run:
                progress.inserted += 1
                continue

            existing_id = nexus_email_to_id.get(payload["email"])
            try:
                if existing_id is not None:
                    # Adopt — mark istniejącego usera jako Traffit-imported
                    await self.db.execute(
                        _UPDATE_USER_ADOPT,
                        {
                            "nexus_id": existing_id,
                            "external_id": payload["external_id"],
                            "external_source": payload["external_source"],
                        },
                    )
                    progress.updated += 1
                else:
                    result = await self.db.execute(_UPSERT_USER, payload)
                    row = result.fetchone()
                    if row is None:
                        continue
                    if row[1]:
                        progress.inserted += 1
                        # Cache fresh email→id dla intra-run dedup (gdyby
                        # Traffit miał 2 userów z tym samym emailem)
                        nexus_email_to_id[payload["email"]] = row[0]
                    else:
                        progress.updated += 1
            except Exception as e:  # noqa: BLE001
                msg = f"upsert user ext={payload['external_id']}: {e!r}"
                progress.add_error(msg)
                if progress.errors <= 5:
                    logger.warning("User upsert error: %s", msg[:300])
                await self.db.rollback()

        if not self.dry_run:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Users import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

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
                # Idempotent UPSERT per stage_def (was DELETE+INSERT but that
                # broke FK from candidate_stages.stage_def_id on daily re-runs).
                # ON CONFLICT (external_source, external_id) DO UPDATE keeps
                # FK references intact while updating order/category/etc.
                # Traffit workflows can have duplicate state names within one
                # workflow (e.g. B2B has two "Zaakceptowany" states). The Nexus
                # constraint uq_stage_name_in_template forbids that, so suffix
                # later occurrences with the source state id to keep names unique.
                seen_names: set[str] = set()
                for idx, state in enumerate(states_sorted):
                    sd = traffit_workflow_state_to_stage_def(state, idx)
                    base = sd["name"]
                    if base in seen_names:
                        sd["name"] = f"{base} (#{sd['traffit_state_id']})"[:100]
                    seen_names.add(sd["name"])
                    await self.db.execute(
                        text(
                            """
                            INSERT INTO pipeline_stage_defs (
                                template_id, name, "order",
                                category, is_terminal, terminal_type,
                                legacy_enum_value,
                                external_id, external_source,
                                tracker_enabled, scorecard_schema,
                                created_at, updated_at
                            ) VALUES (
                                CAST(:template_id AS integer),
                                CAST(:name AS varchar(100)),
                                CAST(:order AS integer),
                                CAST(:category AS stagecategoryenum),
                                CAST(:is_terminal AS boolean),
                                CAST(:terminal_type AS terminaltype),
                                CAST(:legacy_enum_value AS varchar(50)),
                                CAST(:external_id AS varchar(100)),
                                'traffit',
                                false, '{}'::jsonb,
                                NOW(), NOW()
                            )
                            ON CONFLICT (external_source, external_id)
                            WHERE external_id IS NOT NULL
                            DO UPDATE SET
                                template_id       = EXCLUDED.template_id,
                                name              = EXCLUDED.name,
                                "order"           = EXCLUDED."order",
                                category          = EXCLUDED.category,
                                is_terminal       = EXCLUDED.is_terminal,
                                terminal_type     = EXCLUDED.terminal_type,
                                legacy_enum_value = EXCLUDED.legacy_enum_value,
                                updated_at        = NOW()
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
                            "external_id": sd["traffit_state_id"],
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

    async def import_candidates(
        self, since: Optional[datetime] = None
    ) -> PhaseProgress:
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

        # Pre-load existing email → nexus_id mapping. Many emails already
        # exist from talent_radar/manual seed; ix_candidates_email is unique,
        # so straight INSERT would fail. Adopt those rows as Traffit-sourced
        # via _UPDATE_CANDIDATE_ADOPT instead.
        email_map_result = await self.db.execute(
            text(
                "SELECT id, lower(email) FROM candidates "
                "WHERE email IS NOT NULL AND email <> ''"
            )
        )
        email_to_id: dict[str, int] = {
            row[1]: row[0] for row in email_map_result.fetchall() if row[1]
        }
        logger.info("Candidates: existing email_to_id size=%d", len(email_to_id))

        # ``(external_source, external_id)`` jest UNIQUE
        # (``ux_candidates_external_source_id``). Ścieżka "adopt" stempluje
        # external_id na wiersz dopasowany po mailu — jeśli ten external_id
        # NALEŻY JUŻ do innego wiersza (Traffit dopisał maila pracownikowi,
        # który w Nexusie istnieje też jako osobny rekord), UPDATE wywala
        # UniqueViolation (prod: ``upsert candidate ext=48895``).
        # Nie kradniemy cudzej tożsamości: aktualizujemy wtedy prawowitego
        # właściciela external_id. Scalenie obu wierszy to decyzja dedupu
        # (dedup_service), nie importera.
        ext_to_id = await self._build_candidate_external_id_map()
        logger.info("Candidates: existing ext_to_id size=%d", len(ext_to_id))

        commit_every = 100
        since_commit = 0
        adopted = 0
        collisions = 0

        async for raw in self.traffit.get_paginated(
            "/employees/",
            page_size=self.batch_size,
            filter_=self._delta_filter("updated_at", since),
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

            email_lc = (payload.get("email") or "").strip().lower()
            existing_id = email_to_id.get(email_lc) if email_lc else None
            owner_id = ext_to_id.get(str(payload["external_id"]))
            if (
                existing_id is not None
                and owner_id is not None
                and owner_id != existing_id
            ):
                # external_id ma już właściciela — adoptuj JEGO, nie wiersz
                # dopasowany po mailu. _UPDATE_CANDIDATE_ADOPT nie rusza
                # kolumny email, więc żaden unique index nie jest naruszany.
                if collisions < 5:
                    logger.warning(
                        "Candidates ext=%s: email pasuje do id=%s, ale "
                        "external_id należy do id=%s — aktualizuję właściciela",
                        payload["external_id"],
                        existing_id,
                        owner_id,
                    )
                collisions += 1
                existing_id = owner_id

            try:
                if existing_id is not None:
                    # Adopt existing candidate (e.g. from talent_radar).
                    params = {
                        "nexus_id": existing_id,
                        "external_id": payload["external_id"],
                        "external_source": payload["external_source"],
                        "name": payload["name"],
                        "lastname": payload["lastname"],
                        "phone": payload.get("phone"),
                        "linkedin": payload.get("linkedin"),
                        "location": payload.get("location"),
                        "status": payload["status"],
                        "profile_about": payload.get("profile_about"),
                        "languages": json.dumps(payload["languages"]),
                        "cv_filename": payload.get("cv_filename"),
                        "cv_extracted_data": json.dumps(payload["cv_extracted_data"]),
                    }
                    await self.db.execute(_UPDATE_CANDIDATE_ADOPT, params)
                    progress.updated += 1
                    adopted += 1
                else:
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
                        # Newly inserted — record its email so subsequent
                        # Traffit candidates with the same email adopt it.
                        if email_lc:
                            email_to_id[email_lc] = row[0]
                        # ...i jego external_id, żeby kolejny rekord o tym
                        # samym ext nie próbował go ukraść innemu wierszowi.
                        ext_to_id[str(payload["external_id"])] = row[0]
                    else:
                        progress.updated += 1
                since_commit += 1
                if since_commit >= commit_every:
                    await self.db.commit()
                    since_commit = 0
                    logger.info(
                        "Candidates progress: %d/%d "
                        "(inserted=%d updated=%d adopted=%d ext_collisions=%d "
                        "errors=%d)",
                        progress.processed,
                        progress.total_source,
                        progress.inserted,
                        progress.updated,
                        adopted,
                        collisions,
                        progress.errors,
                    )
            except Exception as e:  # noqa: BLE001
                msg = f"upsert candidate ext={payload.get('external_id')}: {e!r}"
                progress.add_error(msg)
                if progress.errors <= 5 or progress.errors % 200 == 0:
                    logger.warning("Candidates upsert error: %s", msg[:300])
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

    async def import_jobs(self, since: Optional[datetime] = None) -> PhaseProgress:
        progress = PhaseProgress(phase="jobs", started_at=datetime.now(timezone.utc))
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

        # Pre-load existing reference_numbers so we can disambiguate Traffit
        # duplicates (same nrRef across different recruitments) without
        # racing the uq_jobs_reference_number constraint mid-loop.
        existing_refs_result = await self.db.execute(
            text(
                "SELECT reference_number, external_id FROM jobs "
                "WHERE reference_number IS NOT NULL"
            )
        )
        # ref -> external_id of the row that already owns it (None if it was
        # set manually pre-import); during this run we update the same dict.
        ref_owner: dict[str, Optional[str]] = {
            row[0]: row[1] for row in existing_refs_result.fetchall()
        }

        async for raw in self.traffit.get_paginated(
            "/recruitments/",
            page_size=self.batch_size,
            filter_=self._delta_filter("updated_at", since),
        ):
            progress.processed += 1
            try:
                payload = traffit_recruitment_to_job(
                    raw, client_map, workflow_map, user_map
                )
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map recruitment id={raw.get('id')}: {e!r}")
                continue

            # Skip jobs bez znanego klienta — DB ma NOT NULL constraint
            # na `client_id` od migracji 0120 (2026-05-27), więc bezklientowy
            # INSERT i tak by się wywalił. Logujemy jako skipped dla audit.
            if payload.get("client_id") is None:
                progress.skipped += 1
                if len(progress.error_samples) < 20:
                    progress.error_samples.append(
                        f"skip job ext={payload['external_id']}: no client mapping"
                    )
                continue

            # Disambiguate duplicate reference_number (Traffit allows it,
            # Nexus has uq_jobs_reference_number). First occurrence keeps the
            # raw nrRef; later ones get a "(#external_id)" suffix.
            ref = payload.get("reference_number")
            ext_id = payload["external_id"]
            if ref:
                owner = ref_owner.get(ref)
                if owner is not None and owner != ext_id:
                    suffixed = f"{ref} (#{ext_id})"[:100]
                    payload["reference_number"] = suffixed
                    ref_owner[suffixed] = ext_id
                else:
                    ref_owner[ref] = ext_id

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
        progress = PhaseProgress(phase="talents", started_at=datetime.now(timezone.utc))
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

    # ── Faza 5b helpers — lookup maps dla pipelines/activities/sources ──────

    async def _build_withdrawn_fallback_reason_map(self) -> WithdrawnReasonFallback:
        """Buduje warstwowy fallback powodu wycofania — patrz
        :class:`WithdrawnReasonFallback`.

        Traffit ``recruitment_history`` nie niesie powodu — trafia on osobno do
        ``rejection_note`` przez rejection_backfill (join po activities).

        Używamy dokładnie tego samego seeda co backfill 0068:
        ``legacy_unknown`` (category='withdrawn', inactive, order 999) per
        template. Templates utworzone PO 0068 mogą go nie mieć — dosiewamy
        idempotentnie (poza dry-run), zanim zbudujemy mapy.
        """
        if not self.dry_run:
            await self.db.execute(
                text(
                    """
                    INSERT INTO rejection_reasons
                        (template_id, name, category, "order", active,
                         created_at, updated_at)
                    SELECT id, 'legacy_unknown', 'withdrawn', 999, FALSE,
                           NOW(), NOW()
                    FROM pipeline_templates
                    ON CONFLICT (template_id, name, category) DO NOTHING
                    """
                )
            )
            await self.db.commit()
        by_job_result = await self.db.execute(
            text(
                """
                SELECT j.id AS job_id, rr.id AS reason_id
                FROM jobs j
                JOIN rejection_reasons rr
                  ON rr.template_id = j.pipeline_template_id
                WHERE rr.name = 'legacy_unknown'
                  AND rr.category = 'withdrawn'
                """
            )
        )
        # Warstwa 2: template definicji etapu. Job bez pipeline'u (99,6% bazy)
        # nadal zna workflow Traffita, z którego przyszedł ruch.
        by_stage_def_result = await self.db.execute(
            text(
                """
                SELECT sd.id AS stage_def_id, rr.id AS reason_id
                FROM pipeline_stage_defs sd
                JOIN rejection_reasons rr
                  ON rr.template_id = sd.template_id
                WHERE rr.name = 'legacy_unknown'
                  AND rr.category = 'withdrawn'
                """
            )
        )
        # Warstwa 3: globalna siatka bezpieczeństwa — domyślny template.
        default_result = await self.db.execute(
            text(
                """
                SELECT rr.id AS reason_id
                FROM rejection_reasons rr
                JOIN pipeline_templates pt ON pt.id = rr.template_id
                WHERE rr.name = 'legacy_unknown'
                  AND rr.category = 'withdrawn'
                ORDER BY pt.is_default DESC, pt.id ASC
                LIMIT 1
                """
            )
        )
        default_row = default_result.fetchone()
        return WithdrawnReasonFallback(
            by_job={row.job_id: row.reason_id for row in by_job_result},
            by_stage_def={
                row.stage_def_id: row.reason_id for row in by_stage_def_result
            },
            default_id=default_row.reason_id if default_row else None,
        )

    @staticmethod
    def _fallback_rejection_reason_id(
        legacy_enum: str,
        job_id: Optional[int],
        stage_def_id: Optional[int],
        withdrawn_fallback: WithdrawnReasonFallback,
    ) -> Optional[int]:
        """Cienki wrapper na :meth:`WithdrawnReasonFallback.resolve`."""
        return withdrawn_fallback.resolve(legacy_enum, job_id, stage_def_id)

    async def _build_candidate_external_id_map(self) -> dict[str, int]:
        result = await self.db.execute(
            text(
                "SELECT id, external_id FROM candidates "
                "WHERE external_source='traffit' AND external_id IS NOT NULL"
            )
        )
        return {row.external_id: row.id for row in result}

    async def _build_job_external_id_map(self) -> dict[str, int]:
        result = await self.db.execute(
            text(
                "SELECT id, external_id FROM jobs "
                "WHERE external_source='traffit' AND external_id IS NOT NULL"
            )
        )
        return {row.external_id: row.id for row in result}

    async def _build_stage_def_lookup(
        self,
    ) -> tuple[dict[str, int], dict[str, str]]:
        """Zwraca dwie mapy: external_id → stage_def_id, external_id → legacy_enum.

        Jeśli ten sam Traffit state.id istnieje w kilku templates (różne
        workflowy), wygrywa pierwszy znaleziony — to zwykły edge case.
        """
        result = await self.db.execute(
            text(
                "SELECT id, external_id, legacy_enum_value "
                "FROM pipeline_stage_defs "
                "WHERE external_source='traffit' AND external_id IS NOT NULL"
            )
        )
        ext_to_id: dict[str, int] = {}
        ext_to_legacy: dict[str, str] = {}
        for row in result:
            if row.external_id not in ext_to_id:
                ext_to_id[row.external_id] = row.id
                ext_to_legacy[row.external_id] = row.legacy_enum_value or "screening"
        return ext_to_id, ext_to_legacy

    # ── Faza 5b: candidates-cv (binary CV download) ─────────────────────────

    async def import_candidates_cv(
        self, since: Optional[datetime] = None
    ) -> PhaseProgress:
        """Pobiera primary CV dla Traffit candidates bez ustawionego CV pointera.

        Idempotent: bierze tylko kandydatów z `cv_storage_key IS NULL`. W trybie
        delta (`since`) zawęża do kandydatów zmienionych od ostatniego syncu —
        nowy kandydat dostaje CV; faktyczne (multi-)pliki ogarnia
        import_candidate_files (które w delta podmienia/dodaje nowe pliki).
        Per-kandydat: GET /employees/{id}/files → primary → /content (binary).
        """
        progress = PhaseProgress(
            phase="candidates_cv", started_at=datetime.now(timezone.utc)
        )

        since_clause = "AND updated_at >= :since" if since is not None else ""
        cv_params: dict[str, Any] = {"since": since} if since is not None else {}
        result = await self.db.execute(
            text(
                f"""
                SELECT id, external_id FROM candidates
                WHERE external_source='traffit'
                  AND external_id IS NOT NULL
                  AND cv_file_content IS NULL
                  AND cv_storage_key IS NULL
                  {since_clause}
                ORDER BY id
                """
            ),
            cv_params,
        )
        targets = list(result)
        progress.total_source = len(targets)
        if not targets:
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        commit_every = 100
        since_commit = 0
        assert self.traffit._http is not None  # noqa: SLF001

        for row in targets:
            progress.processed += 1
            traffit_id = row.external_id
            try:
                files_resp = await self.traffit._get_raw(  # noqa: SLF001
                    f"/employees/{traffit_id}/files", page=1, page_size=50
                )
                if files_resp.status_code != 200:
                    progress.add_error(
                        f"emp {traffit_id} files HTTP {files_resp.status_code}"
                    )
                    continue
                files = files_resp.json()
                if not isinstance(files, list):
                    progress.skipped += 1
                    continue
                primary = select_primary_cv_file(files)
                if not primary:
                    progress.skipped += 1
                    continue
                file_id = primary["id"]
                filename = primary.get("name") or "cv"

                if self.dry_run:
                    progress.inserted += 1
                    continue

                # Binary content — bypass JSON header
                token = await self.traffit._ensure_token()  # noqa: SLF001
                url = (
                    f"{self.traffit.config.api_base}"
                    f"/employees/{traffit_id}/files/{file_id}/content"
                )
                await self.traffit._throttle()  # noqa: SLF001
                content_resp = await self.traffit._http.get(  # noqa: SLF001
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if content_resp.status_code != 200:
                    progress.add_error(
                        f"emp {traffit_id} file {file_id} HTTP "
                        f"{content_resp.status_code}"
                    )
                    continue

                cv_bytes = content_resp.content
                # Upload do Hetzner Object Storage (audit-2026-05-07 Faza 3 cd.).
                # Backend nie zapisuje już BYTEA do candidates.cv_file_content
                # — tylko storage_key.
                from app.services.object_storage import upload_cv as _upload_cv

                # Sync boto3 put — offload so the import loop does not block
                # the event loop for each CV upload.
                cv_storage_key = await run_in_threadpool(
                    _upload_cv,
                    content=cv_bytes,
                    filename=filename,
                    content_type=None,
                )

                await self.db.execute(
                    text(
                        """
                        UPDATE candidates SET
                            cv_storage_key = :storage_key,
                            cv_filename = :filename,
                            updated_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    {
                        "storage_key": cv_storage_key,
                        "filename": filename,
                        "id": row.id,
                    },
                )
                progress.inserted += 1
                since_commit += 1
                if since_commit >= commit_every:
                    await self.db.commit()
                    since_commit = 0
                    logger.info(
                        "CV download progress: %d/%d",
                        progress.processed,
                        progress.total_source,
                    )
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"emp {traffit_id}: {e!r}")
                await self.db.rollback()
                since_commit = 0

        if not self.dry_run and since_commit > 0:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Candidates CV done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    # ── Faza: enrich-names (parse stored CV → fill name/email/phone) ────────

    async def enrich_missing_names(
        self, since: Optional[datetime] = None
    ) -> PhaseProgress:
        """Recover name/email/phone for candidates imported as ``"? ?"``.

        Traffit records with neither a name nor a usable email land as
        ``name="?"`` / ``lastname="?"``. This phase runs after ``candidates_cv``
        (so a CV pointer exists), parses the stored CV through the shared
        backfill, and fills the blank fields — so the daily sync self-heals and
        ``"? ?"`` rows never accumulate. Scoped to ``since`` in delta mode (only
        this run's fresh rows); full reconcile (``since=None``) sweeps any
        stragglers. Skipped in dry-run.

        Maps the backfill's resolved/unresolved counts onto PhaseProgress so the
        watermark reports them: inserted = names resolved, skipped = still blank.
        """
        progress = PhaseProgress(
            phase="candidates_enrich_names", started_at=datetime.now(timezone.utc)
        )
        if self.dry_run:
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        from app.services.cv_backfill import backfill_missing_names

        stats = await backfill_missing_names(self.db, since=since, prefer_llm=True)
        progress.total_source = stats.get("total", 0)
        progress.processed = stats.get("processed", 0)
        progress.inserted = stats.get("resolved", 0)
        progress.skipped = stats.get("unresolved", 0)
        progress.errors = stats.get("errors", 0)
        progress.finished_at = datetime.now(timezone.utc)
        logger.info("Enrich missing names done: %s", stats)
        return progress

    # ── Faza A: candidates-files (multi-file CV w candidate_documents) ──────

    async def import_candidate_files(
        self, since: Optional[datetime] = None
    ) -> PhaseProgress:
        """Pobiera pliki kandydatów Traffit do `candidate_documents`.

        Idempotent: ON CONFLICT (external_source, external_id) DO UPDATE.
        external_id format: `"<traffit_employee_id>-<file_id>"`.

        Per-kandydat:
        1. GET /employees/{traffit_id}/files → lista plików
        2. select_all_files_with_priority — sortuje pdf>docx>doc, marker is_primary
        3. Per plik: GET /employees/{traffit_id}/files/{file_id}/content → binary
        4. UPSERT do candidate_documents

        Tryby:
        - **full** (`since=None`): bierze kandydatów którzy NIE mają jeszcze
          żadnych traffit-sourced plików (HAVING count = 0) — szybki bo pomija
          już zaimportowanych.
        - **delta** (`since`): bierze kandydatów zmienionych od ostatniego syncu
          (`updated_at >= since`) NAWET jeśli mają już pliki, ale pobiera tylko
          te file_id których jeszcze nie ma (po external_id) — łapie nowe/podmienione
          CV bez re-downloadu istniejących.
        """
        progress = PhaseProgress(
            phase="candidates_files", started_at=datetime.now(timezone.utc)
        )

        if since is None:
            # Full mode: skip candidates that already have any traffit files.
            result = await self.db.execute(
                text(
                    """
                    SELECT c.id, c.external_id
                    FROM candidates c
                    LEFT JOIN candidate_documents cd
                      ON cd.candidate_id = c.id AND cd.external_source = 'traffit'
                    WHERE c.external_source = 'traffit'
                      AND c.external_id IS NOT NULL
                    GROUP BY c.id, c.external_id
                    HAVING count(cd.id) = 0
                    ORDER BY c.id
                    """
                )
            )
        else:
            # Delta mode: recently-changed candidates regardless of existing
            # files; we skip already-present file_ids per candidate below.
            result = await self.db.execute(
                text(
                    """
                    SELECT c.id, c.external_id
                    FROM candidates c
                    WHERE c.external_source = 'traffit'
                      AND c.external_id IS NOT NULL
                      AND c.updated_at >= :since
                    ORDER BY c.id
                    """
                ),
                {"since": since},
            )
        targets = list(result)
        progress.total_source = len(targets)
        if not targets:
            progress.finished_at = datetime.now(timezone.utc)
            logger.info("Candidates files: nothing to do (already imported)")
            return progress

        # Pre-load existing traffit doc external_ids for the target candidates so
        # delta runs don't re-download files we already have.
        existing_docs: dict[int, set[str]] = {}
        target_ids = [r.id for r in targets]
        if target_ids:
            doc_rows = await self.db.execute(
                text(
                    "SELECT candidate_id, external_id FROM candidate_documents "
                    "WHERE external_source='traffit' "
                    "AND external_id IS NOT NULL "
                    "AND candidate_id = ANY(:ids)"
                ),
                {"ids": target_ids},
            )
            for dr in doc_rows:
                existing_docs.setdefault(dr.candidate_id, set()).add(dr.external_id)

        logger.info("Candidates files: %d candidates to process", len(targets))

        commit_every = 50  # commit po 50 candidates (każdy może mieć kilka files)
        since_commit = 0
        assert self.traffit._http is not None  # noqa: SLF001

        for row in targets:
            progress.processed += 1
            traffit_id = row.external_id
            try:
                files_resp = await self.traffit._get_raw(  # noqa: SLF001
                    f"/employees/{traffit_id}/files", page=1, page_size=50
                )
                if files_resp.status_code != 200:
                    progress.add_error(
                        f"emp {traffit_id} files HTTP {files_resp.status_code}"
                    )
                    continue
                files_raw = files_resp.json()
                if not isinstance(files_raw, list) or not files_raw:
                    progress.skipped += 1
                    continue

                files_sorted = select_all_files_with_priority(files_raw)
                if not files_sorted:
                    progress.skipped += 1
                    continue

                if self.dry_run:
                    progress.inserted += len(files_sorted)
                    continue

                # Pobierz binary dla każdego pliku
                for f in files_sorted:
                    file_id = f["id"]
                    ext_id = f"{traffit_id}-{file_id}"[:100]
                    # Delta: skip files we already imported (no re-download).
                    if ext_id in existing_docs.get(row.id, ()):
                        progress.skipped += 1
                        continue
                    filename = f.get("name") or f"file-{file_id}"
                    is_primary = bool(f.get("is_primary", False))
                    uploaded_at_raw = f.get("file_uploaded") or f.get("created_at")

                    token = await self.traffit._ensure_token()  # noqa: SLF001
                    url = (
                        f"{self.traffit.config.api_base}"
                        f"/employees/{traffit_id}/files/{file_id}/content"
                    )
                    await self.traffit._throttle()  # noqa: SLF001
                    content_resp = await self.traffit._http.get(  # noqa: SLF001
                        url,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if content_resp.status_code != 200:
                        progress.add_error(
                            f"emp {traffit_id} file {file_id} HTTP "
                            f"{content_resp.status_code}"
                        )
                        continue

                    file_bytes = content_resp.content
                    content_type = content_resp.headers.get("content-type", "")
                    # Strip charset suffix (e.g. "application/pdf; charset=utf-8")
                    if ";" in content_type:
                        content_type = content_type.split(";", 1)[0].strip()

                    # Parse uploaded_at z formatu Traffita
                    from app.services.traffit.mappers import _parse_traffit_datetime

                    uploaded_at = _parse_traffit_datetime(uploaded_at_raw)

                    # Upload do Hetzner Object Storage (audit-2026-05-07 Faza 3).
                    # Bez S3 envów — fallback na BYTEA byłby tutaj kuszący ale
                    # mamy 49k rekordów już w S3, więc dla spójności wymagamy
                    # storage_key set. Brak envów → propagated wyjątek z upload_cv,
                    # cron retry później gdy env vars są dostępne.
                    from app.services.object_storage import upload_cv

                    # Sync boto3 put — offload off the event loop.
                    storage_key = await run_in_threadpool(
                        upload_cv,
                        content=file_bytes,
                        filename=filename[:500],
                        content_type=content_type[:100] if content_type else None,
                    )

                    if is_primary:
                        await self.db.execute(
                            text(
                                """
                                UPDATE candidate_documents
                                SET is_primary = FALSE, updated_at = NOW()
                                WHERE candidate_id = :candidate_id
                                  AND document_kind = 'cv'
                                  AND is_primary IS TRUE
                                  AND source_deleted_at IS NULL
                                  AND external_id IS DISTINCT FROM :external_id
                                """
                            ),
                            {
                                "candidate_id": row.id,
                                "external_id": ext_id,
                            },
                        )
                    await self.db.execute(
                        _UPSERT_CANDIDATE_DOCUMENT,
                        {
                            "candidate_id": row.id,
                            "filename": filename[:500],
                            "storage_key": storage_key,
                            "content_type": content_type[:100]
                            if content_type
                            else None,
                            "size_bytes": len(file_bytes),
                            "document_kind": _traffit_document_kind(
                                filename,
                                is_primary=is_primary,
                            ),
                            "is_primary": is_primary,
                            "uploaded_at": uploaded_at,
                            "external_id": ext_id,
                            "external_source": "traffit",
                        },
                    )
                    progress.inserted += 1

                since_commit += 1
                if since_commit >= commit_every:
                    await self.db.commit()
                    since_commit = 0
                    logger.info(
                        "Files import progress: %d/%d candidates "
                        "(inserted=%d skipped=%d errors=%d)",
                        progress.processed,
                        progress.total_source,
                        progress.inserted,
                        progress.skipped,
                        progress.errors,
                    )
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"emp {traffit_id}: {e!r}")
                await self.db.rollback()
                since_commit = 0

        if not self.dry_run and since_commit > 0:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Candidates files done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    # ── Faza 5b: pipelines (recruitment_history → candidate_stages) ─────────

    async def import_pipelines(self, since: Optional[datetime] = None) -> PhaseProgress:
        progress = PhaseProgress(
            phase="pipelines", started_at=datetime.now(timezone.utc)
        )
        try:
            progress.total_source = await self.traffit.total_count(
                "/employees/recruitment_history"
            )
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        cand_map = await self._build_candidate_external_id_map()
        job_map = await self._build_job_external_id_map()
        sd_id_map, sd_legacy_map = await self._build_stage_def_lookup()
        user_map = await self.build_user_id_map()
        withdrawn_fallback = await self._build_withdrawn_fallback_reason_map()
        logger.info(
            "Pipelines lookups: candidates=%d jobs=%d stage_defs=%d users=%d "
            "withdrawn_fallbacks=by_job:%d/by_stage_def:%d/default:%s",
            len(cand_map),
            len(job_map),
            len(sd_id_map),
            len(user_map),
            len(withdrawn_fallback.by_job),
            len(withdrawn_fallback.by_stage_def),
            withdrawn_fallback.default_id,
        )

        # Commit po każdym successful upsert (zamiast per-batch). Eliminuje
        # batch rollback gdy jeden record narusza check_constraint
        # (np. withdrawn_requires_reason). Pierwszy run miał ~18k stage moves
        # zgubione w batchach po 500 — per-record commit odzyskuje całość.
        # Trade-off: ~2x slower z powodu fsync na każdy commit (akceptowalne
        # dla 152k rekordów = ~85 min API-bound i tak).
        commit_every = 1
        since_commit = 0
        unresolved_withdrawn = 0

        async for raw in self.traffit.get_paginated(
            "/employees/recruitment_history",
            page_size=self.batch_size,
            filter_=self._delta_filter("created_at", since),
        ):
            progress.processed += 1
            try:
                payload = traffit_recruitment_history_to_stage(
                    raw, cand_map, job_map, sd_id_map, sd_legacy_map, user_map
                )
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map history id={raw.get('id')}: {e!r}")
                continue
            if payload is None:
                progress.skipped += 1
                continue
            if self.dry_run:
                # Dry-run nie zasiewa legacy_unknown, więc nie ma sensu liczyć
                # fallbacku — zachowujemy dotychczasowe zachowanie 1:1.
                progress.inserted += 1
                continue
            # withdrawn wymaga powodu (constraint 0068); fallback
            # 'legacy_unknown' — patrz WithdrawnReasonFallback.
            rejection_reason_id = self._fallback_rejection_reason_id(
                payload["stage_legacy_enum"],
                payload["job_id"],
                payload["stage_def_id"],
                withdrawn_fallback,
            )
            if payload["stage_legacy_enum"] == "withdrawn" and (
                rejection_reason_id is None
            ):
                # Nierozwiązywalne tylko gdy baza nie ma ANI JEDNEGO
                # pipeline_template (a wtedy nie ma też stage_defs, więc ten
                # ruch i tak nie byłby 'withdrawn'). Świadomy skip z jawnym
                # powodem — NIE błąd: wiersz i tak padłby na constraincie,
                # a `errors>0` blokuje watermark i trzyma health=degraded.
                progress.skipped += 1
                unresolved_withdrawn += 1
                # Własny licznik, nie progress.skipped — ten drugi zbiera też
                # rekordy spoza Nexusa (na prodzie 224), więc guard na nim
                # nigdy by nie wypuścił tego logu.
                if unresolved_withdrawn <= 5:
                    logger.warning(
                        "Pipelines skip ext=%s: withdrawn bez fallback reason "
                        "(brak seeda legacy_unknown w rejection_reasons)",
                        payload["external_id"],
                    )
                continue
            try:
                result = await self.db.execute(
                    text(
                        """
                        INSERT INTO candidate_stages (
                            external_id, external_source,
                            candidate_id, job_id, stage_def_id, stage,
                            moved_at, moved_by, rejection_reason_id,
                            verification_status,
                            created_at, updated_at
                        ) VALUES (
                            :external_id, 'traffit',
                            :candidate_id, :job_id, :stage_def_id,
                            CAST(:stage AS pipelinestage),
                            CAST(:moved_at AS TIMESTAMPTZ), :moved_by,
                            :rejection_reason_id,
                            CAST('active' AS verificationstatus),
                            NOW(), NOW()
                        )
                        ON CONFLICT (external_source, external_id)
                        WHERE external_id IS NOT NULL
                        DO UPDATE SET
                            stage_def_id = EXCLUDED.stage_def_id,
                            stage        = EXCLUDED.stage,
                            moved_at     = EXCLUDED.moved_at,
                            moved_by     = COALESCE(
                                EXCLUDED.moved_by, candidate_stages.moved_by
                            ),
                            -- Fallback nigdy nie nadpisuje realnego powodu
                            -- (wybranego przez rekrutera lub z backfillu).
                            rejection_reason_id = COALESCE(
                                candidate_stages.rejection_reason_id,
                                EXCLUDED.rejection_reason_id
                            ),
                            updated_at   = NOW()
                        RETURNING id, (xmax = 0) AS was_insert
                        """
                    ),
                    {
                        "external_id": payload["external_id"],
                        "candidate_id": payload["candidate_id"],
                        "job_id": payload["job_id"],
                        "stage_def_id": payload["stage_def_id"],
                        "stage": payload["stage_legacy_enum"],
                        "moved_at": payload["moved_at"],
                        "moved_by": payload["moved_by"],
                        "rejection_reason_id": rejection_reason_id,
                    },
                )
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
                    # Log progress co 500 records (commit jest per-1 ale spam
                    # na każde 1 byłby nie do zniesienia)
                    if progress.processed % 500 == 0:
                        logger.info(
                            "Pipelines progress: %d/%d "
                            "(inserted=%d updated=%d errors=%d)",
                            progress.processed,
                            progress.total_source,
                            progress.inserted,
                            progress.updated,
                            progress.errors,
                        )
            except Exception as e:  # noqa: BLE001
                msg = f"upsert stage ext={payload.get('external_id')}: {e!r}"
                progress.add_error(msg)
                if progress.errors <= 5 or progress.errors % 500 == 0:
                    logger.warning("Pipelines upsert error: %s", msg[:300])
                await self.db.rollback()
                since_commit = 0

        if not self.dry_run and since_commit > 0:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Pipelines import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    # ── Faza 5b: candidate activities ───────────────────────────────────────

    async def import_candidate_activities(
        self, since: Optional[datetime] = None
    ) -> PhaseProgress:
        progress = PhaseProgress(
            phase="candidate_activities", started_at=datetime.now(timezone.utc)
        )
        try:
            progress.total_source = await self.traffit.total_count(
                "/employees/activities"
            )
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        cand_map = await self._build_candidate_external_id_map()
        user_map = await self.build_user_id_map()
        logger.info(
            "Activities lookups: candidates=%d users=%d",
            len(cand_map),
            len(user_map),
        )

        commit_every = 500
        since_commit = 0

        async for raw in self.traffit.get_paginated(
            "/employees/activities",
            page_size=self.batch_size,
            filter_=self._delta_filter("created_at", since),
        ):
            progress.processed += 1
            try:
                payload = traffit_activity_to_activity(raw, cand_map, user_map)
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map activity id={raw.get('id')}: {e!r}")
                continue
            if payload is None:
                progress.skipped += 1
                continue
            if self.dry_run:
                progress.inserted += 1
                continue
            try:
                result = await self.db.execute(
                    text(
                        """
                        INSERT INTO activities (
                            external_id, external_source,
                            entity_type, entity_id, action, details,
                            user_id, created_at, updated_at
                        ) VALUES (
                            :external_id, 'traffit',
                            :entity_type, :entity_id, :action,
                            CAST(:details AS JSONB),
                            :user_id, NOW(), NOW()
                        )
                        ON CONFLICT (external_source, external_id)
                        WHERE external_id IS NOT NULL
                        DO UPDATE SET
                            details   = EXCLUDED.details,
                            user_id   = COALESCE(EXCLUDED.user_id, activities.user_id),
                            updated_at = NOW()
                        RETURNING id, (xmax = 0) AS was_insert
                        """
                    ),
                    {
                        "external_id": payload["external_id"],
                        "entity_type": payload["entity_type"],
                        "entity_id": payload["entity_id"],
                        "action": payload["action"],
                        "details": json.dumps(payload["details"]),
                        "user_id": payload["user_id"],
                    },
                )
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
                        "Activities progress: %d/%d",
                        progress.processed,
                        progress.total_source,
                    )
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert activity ext={payload.get('external_id')}: {e!r}"
                )
                await self.db.rollback()
                since_commit = 0

        if not self.dry_run and since_commit > 0:
            await self.db.commit()

        # Promote candidate notes (Notatka/Email/Reply/Rozmowa/Spotkanie) from
        # `activities` into the dedicated `notes` table so the candidate
        # "Notatki" tab shows them. Idempotent (replicates Alembic 0077) and
        # scoped to the same delta window — this is what keeps "no notatka
        # missing" true on every recurring run, not just the one-time migration.
        if not self.dry_run:
            try:
                promoted = await self.promote_notes(since)
                progress.notes_promoted = promoted
                logger.info("Activities: promoted %d notes → notes table", promoted)
            except Exception as e:  # noqa: BLE001
                await self.db.rollback()
                progress.add_error(f"promote_notes: {e!r}")

        # Self-heal: the rejection *reason* lives only on these activities
        # (details.content.rejection.name), never on the recruitment_history
        # record that produced the rejected candidate_stages row. Stitch them
        # back together by (candidate_id, exact moved_at) so the candidates
        # list shows "Po Interview · job" instead of a bare "Odrzucony". Runs
        # after `pipelines` (phase 8) so the rejected stages already exist.
        if not self.dry_run:
            try:
                healed = await backfill_rejection_notes_from_activities(self.db)
                await self.db.commit()
                logger.info(
                    "Activities self-heal: %d rejected stages got a rejection_note",
                    healed,
                )
            except Exception as e:  # noqa: BLE001
                await self.db.rollback()
                progress.add_error(f"rejection_note backfill: {e!r}")

            # Second self-heal: stitch the recruiter's free-text rejection comment
            # (content.description) onto candidate_stages.notes so the "Powód
            # odrzucenia" column shows "Po CV — niezainteresowany", not a bare bucket.
            try:
                healed_desc = await backfill_rejection_descriptions_from_activities(
                    self.db
                )
                await self.db.commit()
                logger.info(
                    "Activities self-heal: %d rejected stages got a rejection note (description)",
                    healed_desc,
                )
            except Exception as e:  # noqa: BLE001
                await self.db.rollback()
                progress.add_error(f"rejection description backfill: {e!r}")

        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Activities import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    # ── Faza 5b: candidate sources → tags ───────────────────────────────────

    async def import_candidate_sources(
        self, since: Optional[datetime] = None
    ) -> PhaseProgress:
        """Iteruje /sources/, agreguje per-kandydat i append'uje do tags JSONB."""
        progress = PhaseProgress(
            phase="candidate_sources", started_at=datetime.now(timezone.utc)
        )
        try:
            progress.total_source = await self.traffit.total_count("/sources/")
        except Exception as e:  # noqa: BLE001
            progress.add_error(f"total_count failed: {e!r}")
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        cand_map = await self._build_candidate_external_id_map()

        # Aggregate per candidate w pamięci — przy 75k records to OK
        # (każdy record ~200B → ~15MB max).
        per_candidate: dict[int, list[dict[str, Any]]] = {}

        # /sources/ endpoint na tenant b2bnetwork ma server-side bug w paginacji:
        # losowe HTTP 500 na specyficznych stronach (np. p6, p8, p11 przy size=10),
        # nawet przy page_size=10. Cap do 10 (mniej "złych" stron) + skip_on_5xx
        # żeby nie ubić importu z powodu chwiejnego endpoint'u Traffita.
        # Tracimy ~10 records per failed page, akceptowalne dla audit-log danych.
        sources_page_size = min(self.batch_size, 10)
        async for raw in self.traffit.get_paginated(
            "/sources/",
            page_size=sources_page_size,
            skip_on_5xx=True,
            filter_=self._delta_filter("created_at", since),
        ):
            progress.processed += 1
            try:
                mapped = traffit_source_to_candidate_tag(raw, cand_map)
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"map source id={raw.get('id')}: {e!r}")
                continue
            if mapped is None:
                progress.skipped += 1
                continue
            per_candidate.setdefault(mapped["candidate_id"], []).append(mapped["tag"])

        if self.dry_run:
            progress.inserted = sum(len(v) for v in per_candidate.values())
            progress.finished_at = datetime.now(timezone.utc)
            return progress

        # Apply: read existing tags, dedup po (type, source_id), write back
        for candidate_id, new_tags in per_candidate.items():
            try:
                row = await self.db.execute(
                    text("SELECT tags FROM candidates WHERE id=:id"),
                    {"id": candidate_id},
                )
                rec = row.fetchone()
                existing = rec[0] if rec and rec[0] else []
                if not isinstance(existing, list):
                    existing = []

                seen_ids = {
                    t.get("source_id")
                    for t in existing
                    if isinstance(t, dict) and t.get("type") == "traffit_source"
                }
                added = 0
                for t in new_tags:
                    if t.get("source_id") in seen_ids:
                        continue
                    existing.append(t)
                    seen_ids.add(t.get("source_id"))
                    added += 1
                if added > 0:
                    await self.db.execute(
                        text(
                            "UPDATE candidates SET tags=CAST(:tags AS JSONB), "
                            "updated_at=NOW() WHERE id=:id"
                        ),
                        {"tags": json.dumps(existing), "id": candidate_id},
                    )
                    progress.inserted += added
                else:
                    progress.skipped += 1
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"merge tags candidate={candidate_id}: {e!r}")
                await self.db.rollback()

        await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Sources import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress
