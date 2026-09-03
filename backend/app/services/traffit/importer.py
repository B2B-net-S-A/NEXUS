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

import httpx
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.services.candidate_contact_hooks import (
    maybe_close_contact_opportunity,
    maybe_ensure_contact_opportunity,
)
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
from app.services.recruitment_process_commands import (
    sync_external_observed_processes,
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


# Every row-level error message in this module is built as
# ``"<verb> <entity> ext=<id>: <error>"`` (or ``id=``), e.g.
# ``"upsert candidate ext=48895: IntegrityError(...)"``. Reading the key back
# out of the message keeps the 41 ``add_error`` call sites untouched — adding a
# parameter to all of them would be a large diff whose only failure mode is the
# one call site somebody forgets.
_ERROR_REF_RE = re.compile(r"\b(\w+)\s+(?:ext|id)=([^\s:,]+)")

# Refs are tiny strings, but a systemically broken phase must not balloon the
# stats JSONB. Past this many distinct failing rows the problem is not a poison
# row and quarantine is the wrong tool anyway.
_MAX_ERROR_REFS = 500

# HTTP answers that mean "the record no longer exists upstream". Neither is a
# failure: retrying cannot change either one, so both are counted into
# `gone_upstream` and never recorded as errors. Traffit answers 404 today
# (confirmed on prod); 410 is the status an API is supposed to use for a
# deletion it still remembers, so a tenant that starts distinguishing the two
# would otherwise start freezing watermarks the same way 404 used to.
_GONE_STATUS_CODES = frozenset({404, 410})

# Phase row that carries the files sweep's resume cursor. This is the
# ORCHESTRATOR's phase-plan name (``app/tasks/traffit_sync.py::_phase_plan``),
# deliberately not ``PhaseProgress.phase`` for this phase ("candidates_files") —
# the two have differed since the phase was written. The cursor has to land on
# the row the orchestrator already owns, because `_write_sync_cursor` UPSERTs:
# keying it on the progress name would INSERT a second, phantom phase row that
# shows up in GET /sync/status forever and never gets a status or stats.
_FILES_CURSOR_PHASE = "candidate_files"

# Same rule as above: the orchestrator's phase-plan name, so the cursor lands on
# the row that already carries this phase's status and stats.
_ENRICH_NAMES_CURSOR_PHASE = "candidates_enrich_names"
_CV_CURSOR_PHASE = "candidates_cv"
_ACTIVITIES_CURSOR_PHASE = "candidate_activities"

# Re-point `candidates.cv_*` at the candidate's CURRENT active primary CV.
#
# Module-level so the test exercises THIS statement rather than a copy of it —
# a duplicated query drifts from production silently and then proves nothing.
#
# The EXISTS guard is what makes this safe: it fires only when the pointer is
# already a Traffit-owned CV. A CV uploaded directly in Nexus is newer by
# definition and must never be overwritten by Traffit's copy (those rows carry a
# different `external_source`, so they are excluded twice over). `document_kind`
# is repeated inside EXISTS deliberately: the claim being proved is "the current
# pointer is a Traffit CV", not "some Traffit document happens to share this
# storage key". It errs strict — a pointer at a Traffit file classified `other`
# is left alone rather than re-pointed, which is the status quo, not a
# regression.
# Postaw nagrobek na kandydacie, którego Traffit już nie zna.
#
# Wołane WYŁĄCZNIE dla 404/410 na LIŚCIE plików (`/employees/{id}/files`), bo
# to odpowiedź o osobie. 404 na pobraniu pojedynczego pliku znaczy tylko „nie
# ma tego pliku" i nagrobka NIE stawia — pomylenie tych dwóch oznaczałoby
# skasowanie profilu z powodu jednego nieudanego załącznika.
#
# `IS NULL` w warunku sprawia, że znacznik zapamiętuje PIERWSZĄ obserwację
# zniknięcia i nie przesuwa się przy każdym kolejnym biegu — inaczej data
# mówiłaby „kiedy ostatnio sprawdzaliśmy", a nie „od kiedy nie ma".
_TOMBSTONE_CANDIDATE = text(
    """
    UPDATE candidates
       SET external_deleted_at = NOW(), updated_at = NOW()
     WHERE id = CAST(:id AS integer)
       AND external_deleted_at IS NULL
    """
)

_RESYNC_STALE_CV_POINTER = text(
    """
    UPDATE candidates c
    SET cv_storage_key = d.storage_key,
        cv_filename    = d.filename,
        updated_at     = NOW()
    FROM candidate_documents d
    WHERE d.candidate_id = c.id
      AND d.external_source = 'traffit'
      AND d.document_kind = 'cv'
      AND d.is_primary IS TRUE
      AND d.source_deleted_at IS NULL
      AND c.external_source = 'traffit'
      AND c.cv_storage_key IS NOT NULL
      AND c.cv_storage_key IS DISTINCT FROM d.storage_key
      AND EXISTS (
          SELECT 1 FROM candidate_documents d2
          WHERE d2.candidate_id = c.id
            AND d2.external_source = 'traffit'
            AND d2.document_kind = 'cv'
            AND d2.storage_key = c.cv_storage_key
      )
    """
)
_PIPELINES_CURSOR_PHASE = "pipelines"
_CANDIDATES_CURSOR_PHASE = "candidates"


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
    # Whole pages dropped by `skip_on_5xx` (only /sources/ uses it). Counted
    # rather than raised: the endpoint's 5xx are a known, recurring server-side
    # bug, so an unattributable error would pin the watermark and `degraded`
    # forever — but the loss must still be countable somewhere.
    skipped_pages: int = 0
    # Stale `candidates.cv_*` pointers moved to the current primary CV. Its own
    # counter because it is not an import: no row was fetched, only re-aimed.
    resynced_pointers: int = 0
    # Records Traffit answered 404 for — deleted at source, not a transient
    # failure. Counted, never `add_error`: see the call sites for why treating
    # "it is gone" as an error froze phases indefinitely.
    gone_upstream: int = 0
    # Rekrutacje, dla których Traffit nie podał rozwiązywalnego klienta.
    #
    # Nazwa opisuje FAKT U ŹRÓDŁA, nie naszą reakcję — tak jak `gone_upstream`
    # obok. `orphaned` obiecywałoby „tyle wierszy siedzi u zastępczego
    # klienta", a to nieprawda w jednym przypadku: gdy rekrutacja ma już
    # poprawnego klienta w Nexusie i zniknęło samo MAPOWANIE, zostawiamy jej
    # tego klienta. Operator zobaczyłby wtedy 3 i znalazł 2 w kubełku.
    #
    # CELOWO osobny licznik, nie `skipped`: to są wiersze ZAPISANE — zlanie
    # ich ze `skipped` (= pominięte) mówiłoby coś przeciwnego do prawdy.
    unresolved_client: int = 0
    # Kandydaci, którym w TYM biegu postawiono nagrobek. Liczy PIERWSZE
    # oznaczenie (UPDATE ma `external_deleted_at IS NULL`), więc po domknięciu
    # tematu spada do zera — inaczej rósłby w nieskończoność i przestałby
    # odpowiadać na pytanie „czy coś nowego zniknęło".
    tombstoned: int = 0
    error_samples: list[str] = field(default_factory=list)
    # Stable per-row keys ("candidate:48895") for the errors we could attribute
    # to a specific source record. Consumed by the quarantine in
    # ``app/tasks/traffit_sync.py``: a row that fails the same way run after run
    # must stop freezing the delta watermark for everything else.
    error_refs: set[str] = field(default_factory=set)
    # How many of ``errors`` we could pin to a row. NOT ``len(error_refs)``:
    # one row can fail twice in a single run (two phases touch it, or a retry),
    # and then the set has one entry for two errors. Subtracting the set size
    # would invent a phantom "unattributable" error that blocks the watermark
    # forever — the quarantine would never release and the whole mechanism
    # would be a no-op. Counted separately so the arithmetic stays exact.
    attributed_errors: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def add_error(self, msg: str) -> None:
        self.errors += 1
        if len(self.error_samples) < 20:
            self.error_samples.append(msg)
        match = _ERROR_REF_RE.search(msg)
        if match and len(self.error_refs) < _MAX_ERROR_REFS:
            # Entity is part of the key so `candidate ext=7` and `stage ext=7`
            # never collide into one quarantine entry.
            self.error_refs.add(f"{match.group(1)}:{match.group(2)}")
            self.attributed_errors += 1
        # Past the ref cap we deliberately stop attributing: 500+ distinct
        # failing rows is a systemic fault, and counting the overflow as
        # unattributable keeps the watermark frozen, which is the safe answer.

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
            "skipped_pages": self.skipped_pages,
            "resynced_pointers": self.resynced_pointers,
            "gone_upstream": self.gone_upstream,
            "unresolved_client": self.unresolved_client,
            "tombstoned": self.tombstoned,
            "error_samples": self.error_samples[:20],
            "error_refs": sorted(self.error_refs),
            "attributed_errors": self.attributed_errors,
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
        -- ``status`` CELOWO nieobecne (decyzja Fazy B, 2026-08-06): status jest
        -- NEXUS-owned — seedowany przy pierwszym imporcie, potem edytowany
        -- ręcznie z UI. Traffit trzyma go głównie jako default 'active'
        -- (normalize_client_status fallback), więc nadpis przy każdym daily
        -- sync cofał ręczne zmiany w <24h i wpychał 'Aktywny' 130 nieaktywnym.
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
        CAST(:external_id AS text),
        CAST(:external_source AS text),
        CAST(:name AS text),
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
        status, profile_about, cv_filename,
        cv_extracted_data, custom_fields, source, created_by,
        notes_count, champion, availability_status,
        linkedin_sync_status,
        created_at, updated_at
    ) VALUES (
        :external_id, :external_source,
        CAST(:name AS text), CAST(:lastname AS text), :email, :phone,
        :linkedin,
        CAST(:status AS candidatestatus),
        :profile_about,
        :cv_filename,
        CAST(:cv_extracted_data AS JSONB),
        jsonb_build_object(
            '_nexus_identity',
            jsonb_strip_nulls(jsonb_build_object(
                'traffit_name', CAST(:name AS text),
                'traffit_lastname', CAST(:lastname AS text),
                'traffit_source_updated_at',
                    CAST(:traffit_source_updated_at AS text)
            ))
        ),
        :source, :created_by,
        0, false,
        CAST('unknown' AS availabilitystatus),
        CAST('disabled' AS linkedinsyncstatus),
        NOW(), NOW()
    )
    ON CONFLICT (external_source, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        -- Ręczna korekta w NEXUS-ie przejmuje własność tylko nad wskazanym
        -- polem. Traffit nadal odświeża snapshot źródłowy w custom_fields,
        -- dzięki czemu użytkownik może świadomie przywrócić jego wartość.
        name              = CASE
                              WHEN COALESCE(
                                candidates.custom_fields #>>
                                  '{_nexus_identity,name_manual}',
                                'false'
                              ) = 'true'
                              OR (
                                candidates.custom_fields #>>
                                  '{_nexus_identity,traffit_name}' IS NULL
                                AND candidates.name IS DISTINCT FROM EXCLUDED.name
                                AND candidates.name IS DISTINCT FROM
                                    CAST(:traffit_raw_name AS text)
                              )
                              THEN candidates.name
                              ELSE EXCLUDED.name
                            END,
        lastname          = CASE
                              WHEN COALESCE(
                                candidates.custom_fields #>>
                                  '{_nexus_identity,lastname_manual}',
                                'false'
                              ) = 'true'
                              OR (
                                candidates.custom_fields #>>
                                  '{_nexus_identity,traffit_lastname}' IS NULL
                                AND candidates.lastname
                                    IS DISTINCT FROM EXCLUDED.lastname
                                AND candidates.lastname IS DISTINCT FROM
                                    CAST(:traffit_raw_lastname AS text)
                              )
                              THEN candidates.lastname
                              ELSE EXCLUDED.lastname
                            END,
        email             = COALESCE(EXCLUDED.email, candidates.email),
        phone             = COALESCE(EXCLUDED.phone, candidates.phone),
        linkedin          = COALESCE(EXCLUDED.linkedin, candidates.linkedin),
        -- Blacklista jest LEPKA. `EXCLUDED.status` niesie to, co przysłał
        -- Traffit, a tam blacklisty nie ma w żadnym polu: jest wklejona
        -- w imię. Bez tego warunku każdy, kogo admin oznaczył ręcznie
        -- w Nexusie, wracałby na `active` przy najbliższym syncu — czyli
        -- cichy powrót do proponowania osoby, której proponować nie wolno.
        -- Zdjęcie blacklisty jest świadomą decyzją człowieka i musi się
        -- odbyć w Nexusie, a nie przez brak markera w cudzym systemie.
        status            = CASE
                              WHEN candidates.status
                                   = CAST('blacklisted' AS candidatestatus)
                              THEN candidates.status
                              ELSE EXCLUDED.status
                            END,
        profile_about     = COALESCE(
            EXCLUDED.profile_about,
            candidates.profile_about
        ),
        cv_filename       = COALESCE(EXCLUDED.cv_filename, candidates.cv_filename),
        cv_extracted_data = candidates.cv_extracted_data
                            || EXCLUDED.cv_extracted_data
                            || CASE
                                 WHEN COALESCE(
                                   candidates.cv_extracted_data
                                     ->>'_manual_override_city',
                                   'false'
                                 ) = 'true'
                                 THEN jsonb_build_object(
                                   '_manual_override_city', true
                                 )
                                 ELSE '{}'::jsonb
                               END
                            || CASE
                                 WHEN COALESCE(
                                   candidates.cv_extracted_data
                                     ->>'_manual_override_country',
                                   'false'
                                 ) = 'true'
                                 THEN jsonb_build_object(
                                   '_manual_override_country', true
                                 )
                                 ELSE '{}'::jsonb
                               END,
        custom_fields     = jsonb_set(
                              CASE
                                WHEN jsonb_typeof(candidates.custom_fields)
                                     = 'object'
                                THEN candidates.custom_fields
                                ELSE '{}'::jsonb
                              END,
                              '{_nexus_identity}',
                              CASE
                                WHEN jsonb_typeof(
                                  candidates.custom_fields
                                    -> '_nexus_identity'
                                ) = 'object'
                                THEN candidates.custom_fields
                                       -> '_nexus_identity'
                                ELSE '{}'::jsonb
                              END
                              || CASE
                                   WHEN candidates.custom_fields #>>
                                          '{_nexus_identity,traffit_name}'
                                          IS NULL
                                        AND COALESCE(
                                          candidates.custom_fields #>>
                                            '{_nexus_identity,name_manual}',
                                          'false'
                                        ) <> 'true'
                                        AND candidates.name
                                            IS DISTINCT FROM EXCLUDED.name
                                        AND candidates.name IS DISTINCT FROM
                                            CAST(:traffit_raw_name AS text)
                                   THEN jsonb_build_object(
                                     'name_manual', true,
                                     'name_ownership_reason',
                                       'bootstrap_mismatch',
                                     'name_set_at', NOW()
                                   )
                                   ELSE '{}'::jsonb
                                 END
                              || CASE
                                   WHEN candidates.custom_fields #>>
                                          '{_nexus_identity,traffit_lastname}'
                                          IS NULL
                                        AND COALESCE(
                                          candidates.custom_fields #>>
                                            '{_nexus_identity,lastname_manual}',
                                          'false'
                                        ) <> 'true'
                                        AND candidates.lastname
                                            IS DISTINCT FROM EXCLUDED.lastname
                                        AND candidates.lastname IS DISTINCT FROM
                                            CAST(:traffit_raw_lastname AS text)
                                   THEN jsonb_build_object(
                                     'lastname_manual', true,
                                     'lastname_ownership_reason',
                                       'bootstrap_mismatch',
                                     'lastname_set_at', NOW()
                                   )
                                   ELSE '{}'::jsonb
                                 END
                              || CASE
                                   WHEN jsonb_typeof(
                                     EXCLUDED.custom_fields
                                       -> '_nexus_identity'
                                   ) = 'object'
                                   THEN EXCLUDED.custom_fields
                                          -> '_nexus_identity'
                                   ELSE '{}'::jsonb
                                 END,
                              true
                            ),
        updated_at        = NOW(),
        -- Kandydat jest w żywym feedzie `/employees/`, więc ewentualny
        -- nagrobek jest nieaktualny. Bez tego czyszczenia pojedyncze 404
        -- (chwilowa awaria Traffita, rekord przywrócony z kosza) zostawiałoby
        -- trwałe „usunięty u źródła" na wskroś żywym profilu.
        external_deleted_at = NULL
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
    SET external_source = CAST(:external_source AS text),
        external_id     = CAST(:external_id AS text),
        name            = CASE
                            WHEN COALESCE(
                              candidates.custom_fields #>>
                                '{_nexus_identity,name_manual}',
                              'false'
                            ) = 'true'
                            OR (
                              candidates.custom_fields #>>
                                '{_nexus_identity,traffit_name}' IS NULL
                              AND candidates.name
                                  IS DISTINCT FROM CAST(:name AS text)
                              AND candidates.name IS DISTINCT FROM
                                  CAST(:traffit_raw_name AS text)
                            )
                            THEN candidates.name
                            ELSE CAST(:name AS text)
                          END,
        lastname        = CASE
                            WHEN COALESCE(
                              candidates.custom_fields #>>
                                '{_nexus_identity,lastname_manual}',
                              'false'
                            ) = 'true'
                            OR (
                              candidates.custom_fields #>>
                                '{_nexus_identity,traffit_lastname}' IS NULL
                              AND candidates.lastname
                                  IS DISTINCT FROM CAST(:lastname AS text)
                              AND candidates.lastname IS DISTINCT FROM
                                  CAST(:traffit_raw_lastname AS text)
                            )
                            THEN candidates.lastname
                            ELSE CAST(:lastname AS text)
                          END,
        phone           = COALESCE(CAST(:phone AS text), candidates.phone),
        linkedin        = COALESCE(CAST(:linkedin AS text), candidates.linkedin),
        status          = CAST(:status AS candidatestatus),
        profile_about   = COALESCE(
            CAST(:profile_about AS text),
            candidates.profile_about
        ),
        cv_filename     = COALESCE(CAST(:cv_filename AS text),
                                   candidates.cv_filename),
        cv_extracted_data = candidates.cv_extracted_data
                            || CAST(:cv_extracted_data AS JSONB)
                            || jsonb_build_object(
                                 'legacy_source', candidates.external_source
                               )
                            || CASE
                                 WHEN COALESCE(
                                   candidates.cv_extracted_data
                                     ->>'_manual_override_city',
                                   'false'
                                 ) = 'true'
                                 THEN jsonb_build_object(
                                   '_manual_override_city', true
                                 )
                                 ELSE '{}'::jsonb
                               END
                            || CASE
                                 WHEN COALESCE(
                                   candidates.cv_extracted_data
                                     ->>'_manual_override_country',
                                   'false'
                                 ) = 'true'
                                 THEN jsonb_build_object(
                                   '_manual_override_country', true
                                 )
                                 ELSE '{}'::jsonb
                               END,
        custom_fields   = jsonb_set(
                            CASE
                              WHEN jsonb_typeof(candidates.custom_fields)
                                   = 'object'
                              THEN candidates.custom_fields
                              ELSE '{}'::jsonb
                            END,
                            '{_nexus_identity}',
                            CASE
                              WHEN jsonb_typeof(
                                candidates.custom_fields -> '_nexus_identity'
                              ) = 'object'
                              THEN candidates.custom_fields
                                     -> '_nexus_identity'
                              ELSE '{}'::jsonb
                            END
                            || CASE
                                 WHEN candidates.custom_fields #>>
                                        '{_nexus_identity,traffit_name}' IS NULL
                                      AND COALESCE(
                                        candidates.custom_fields #>>
                                          '{_nexus_identity,name_manual}',
                                        'false'
                                      ) <> 'true'
                                      AND candidates.name
                                          IS DISTINCT FROM CAST(:name AS text)
                                      AND candidates.name IS DISTINCT FROM
                                          CAST(:traffit_raw_name AS text)
                                 THEN jsonb_build_object(
                                   'name_manual', true,
                                   'name_ownership_reason',
                                     'bootstrap_mismatch',
                                   'name_set_at', NOW()
                                 )
                                 ELSE '{}'::jsonb
                               END
                            || CASE
                                 WHEN candidates.custom_fields #>>
                                        '{_nexus_identity,traffit_lastname}'
                                        IS NULL
                                      AND COALESCE(
                                        candidates.custom_fields #>>
                                          '{_nexus_identity,lastname_manual}',
                                        'false'
                                      ) <> 'true'
                                      AND candidates.lastname
                                          IS DISTINCT FROM CAST(:lastname AS text)
                                      AND candidates.lastname IS DISTINCT FROM
                                          CAST(:traffit_raw_lastname AS text)
                                 THEN jsonb_build_object(
                                   'lastname_manual', true,
                                   'lastname_ownership_reason',
                                     'bootstrap_mismatch',
                                   'lastname_set_at', NOW()
                                 )
                                 ELSE '{}'::jsonb
                               END
                            || jsonb_build_object(
                                 'traffit_name', CAST(:name AS text),
                                 'traffit_lastname', CAST(:lastname AS text)
                               )
                            || CASE
                                 WHEN CAST(:traffit_source_updated_at AS text)
                                      IS NOT NULL
                                 THEN jsonb_build_object(
                                   'traffit_source_updated_at',
                                   CAST(:traffit_source_updated_at AS text)
                                 )
                                 ELSE '{}'::jsonb
                               END,
                            true
                          ),
        updated_at      = NOW()
    WHERE id = :nexus_id
    RETURNING id
    """
)


# Lista `DO UPDATE SET` niżej MUSI równać się `SYNC_WRITABLE`
# z `app/services/job_column_ownership.py` — pilnuje tego
# `tests/test_job_column_ownership.py`. Dopisanie tu kolumny bez decyzji
# „czyja ona jest" znaczyłoby, że sync po cichu nadpisuje pracę zrobioną
# w NEXUSIE, a to jest dokładnie ten tryb awarii, który 0270 zamyka.
#
# Dwie różne semantyki dat i to nie jest niedopatrzenie:
#   `opened_at` idzie przez COALESCE — data otwarcia się nie zmienia, więc
#   payload bez `created_at` nie ma prawa skasować dobrej wartości.
#   `closed_at` jest nadpisywane BEZWARUNKOWO — na produkcji trzyma dziś
#   sfabrykowane znaczniki syncu (backfill `closed_at = updated_at` z
#   entrypointu, usunięty w 0270) i pełny bieg importera ma je zastąpić
#   prawdą. Bezwarunkowość zeruje je też, gdy rekrutacja wróci do otwartych.
_UPSERT_JOB = text(
    """
    INSERT INTO jobs (
        external_id, external_source, title, status, client_id,
        pipeline_template_id, recruiter_id, reference_number, deadline,
        opened_at, closed_at,
        custom_fields,
        remote_policy, priority, recruitment_type, work_mode, headcount,
        needs_sourcing, is_open,
        created_at, updated_at
    ) VALUES (
        :external_id, :external_source, :title,
        CAST(:status AS jobstatus),
        :client_id, :pipeline_template_id, :recruiter_id,
        :reference_number,
        CAST(:deadline AS DATE),
        CAST(:opened_at AS TIMESTAMPTZ),
        CAST(:closed_at AS TIMESTAMPTZ),
        CAST(:custom_fields AS JSONB),
        CAST('hybrid' AS remotepolicy),
        CAST('medium' AS jobpriority),
        CAST('body_leasing' AS recruitmenttype),
        CAST('fulltime' AS workmode),
        1, false, false,
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
        opened_at            = COALESCE(EXCLUDED.opened_at, jobs.opened_at),
        closed_at            = EXCLUDED.closed_at,
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
        CAST(:external_id AS text),
        CAST(:external_source AS text),
        CAST(:email AS text),
        CAST(:name AS text),
        CAST(:role AS userrole),
        CAST(:is_active AS boolean),
        CAST(:password_hash AS text),
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
    SET external_id     = CAST(:external_id AS text),
        external_source = CAST(:external_source AS text),
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
def needs_session_rollback(error: BaseException, *, past_savepoint: bool) -> bool:
    """Czy po tym błędzie trzeba podnieść SESJĘ, czy wystarczył savepoint.

    Dwa przypadki wymagają `db.rollback()`, i tylko one:

    * `past_savepoint` — błąd przyszedł ze ścieżki commita, savepoint jest już
      zamknięty i nic innego sesji nie podniesie;
    * utrata POŁĄCZENIA — gdy backend Postgresa znika (restart, failover,
      `idle_in_transaction_session_timeout`, reaper OOM), `ROLLBACK TO SAVEPOINT`
      nie ma dokąd pójść. Sesja wpada w `PendingRollbackError`, a każdy kolejny
      wiersz fazy pada — jeden blip połączenia kosztuje resztę importu zamiast
      jednej paczki.

    Dla zwykłego błędu INSTRUKCJI odpowiedź brzmi False: savepoint już go cofnął,
    transakcja zewnętrzna żyje, a rollback sesji wyrzuciłby całą niezacommitowaną
    paczkę — czyli dokładnie to, czemu savepoint miał zapobiec.

    `is_active` i `in_transaction()` do rozróżnienia się NIE nadają: przy martwym
    połączeniu raportują to samo co przy zdrowym (zmierzone). Robi to
    `connection_invalidated`, ustawiane przez SQLAlchemy na `DBAPIError`.
    """

    if past_savepoint:
        return True
    return bool(getattr(error, "connection_invalidated", False))


_UPSERT_CANDIDATE_DOCUMENT = text(
    """
    INSERT INTO candidate_documents (
        candidate_id, filename, storage_key, content_type,
        size_bytes, document_kind, is_primary, uploaded_at,
        external_id, external_source,
        created_at, updated_at
    ) VALUES (
        CAST(:candidate_id AS integer),
        CAST(:filename AS text),
        CAST(:storage_key AS text),
        CAST(:content_type AS text),
        CAST(:size_bytes AS integer),
        CAST(:document_kind AS candidatedocumentkind),
        CAST(:is_primary AS boolean),
        :uploaded_at,
        CAST(:external_id AS text),
        CAST(:external_source AS text),
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
  -- Kandydat MUSI istnieć. `notes.candidate_id` ma klucz obcy, a ta promocja to
  -- JEDEN `INSERT ... SELECT`, więc pojedyncza osierocona aktywność nie psuła
  -- własnego wiersza — wywracała CAŁĄ paczkę. Na prodzie jeden taki rekord dawał
  -- `candidate_activities: errors 1` przy 396 779 zaktualizowanych, a ponieważ
  -- błąd fazy wstrzymuje watermark, `__full__` stał od 19 lipca: pełny reconcile
  -- nie mógł się domknąć z powodu jednej notatki.
  --
  -- Pominięcie takiego wiersza nie jest cichą stratą w rozumieniu M2-IMP-01:
  -- kandydata NIE MA w Nexusie, więc notatki i tak nie da się zapisać (mówi to
  -- sam FK). Aktywność źródłowa zostaje nietknięta, a dedup idzie po
  -- `source_ref`, więc gdy kandydat zostanie kiedyś zaimportowany, najbliższy
  -- sync dopisze notatkę. Mechanizm jest samoleczący, w przeciwieństwie do
  -- przewracania całej fazy.
  AND EXISTS (SELECT 1 FROM candidates c WHERE c.id = a.entity_id)
  AND COALESCE(
      a.details #>> '{content,content}',
      a.details ->> 'content',
      ''
  ) <> ''
  /*SINCE*/
  -- Dedup on the SOURCE ROW's identity, with the old timestamp match kept as
  -- a fallback. `source_ref` is what actually identifies the activity; the
  -- timestamp did not, and matching on it alone was wrong twice over:
  --
  --   * two activities of one candidate sharing a `created_at` (an email and
  --     its logged reply, a bulk import stamped in one second) collapsed into
  --     ONE note — the second was suppressed permanently by the first. That is
  --     the exact "notatka missing" class this phase exists to prevent.
  --   * an activity whose `created_at` was later edited in Traffit stopped
  --     matching its own note and got promoted AGAIN, as a duplicate.
  --
  -- The `source_ref IS NULL` arm is not legacy clutter: migration 0077 wrote
  -- these rows WITHOUT a `source_ref`, so keying purely on it would re-promote
  -- every note 0077 created — a duplicate for all ~49k candidates on the next
  -- sync. Those rows stay matched by timestamp until they are backfilled.
  AND NOT EXISTS (
      SELECT 1 FROM notes n
      WHERE n.candidate_id = a.entity_id
        AND (
            n.source_ref = 'traffit:activity:' || a.external_id
            OR (n.source_ref IS NULL AND n.created_at = a.created_at)
        )
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

    async def _build_job_client_map(self) -> dict[str, int]:
        """`jobs.external_id` (Traffit) → obecny `client_id` w Nexusie.

        Czytane RAZ na fazę: alternatywą byłby SELECT per bezklientowa
        rekrutacja, a ta gałąź z definicji dotyczy rekordów, których w
        Traffitcie jest garść — ale mapa i tak jest mała (jeden wiersz na
        rekrutację), więc jeden przebieg jest tańszy niż warunkowe zapytania.
        """
        result = await self.db.execute(
            text(
                "SELECT external_id, client_id FROM jobs "
                "WHERE external_source = 'traffit' AND external_id IS NOT NULL "
                "AND client_id IS NOT NULL"
            )
        )
        return {row[0]: row[1] for row in result}

    async def _ensure_orphan_client(self) -> int:
        """Get-or-create the `__traffit_orphans` client. Returns its Nexus id.

        Bucket jest ZAWSZE ``hidden`` — to worek techniczny na rekrutacje i osoby
        kontaktowe bez klienta, nie firma. Bez tej flagi wchodzi do każdej listy
        klientów jako pełnoprawny wiersz z zerami: `list_clients`, dropdowny,
        `client_directory` i ranking admina filtrują właśnie po
        ``hidden``/``archived_at``/``merged_into_client_id``
        (`services/client_identity.visible_client_predicates`). Na produkcji
        (2026-08-12) siedział na 1. pozycji rankingu klientów. Kod już traktował
        go jako rekord systemowy — `client_portfolio_import.SYSTEM_CLIENT_NAMES`
        wyłącza go ze ścieżki importu portfela — brakowało tylko flagi.

        ``archived_at`` świadomie NIE jest ustawiane: do zniknięcia z list
        wystarcza ``hidden``, a archiwizacja jest stanem cyklu życia importu
        portfela (ścieżka „revive" wymaga ``hidden AND archived_at``), więc
        wchodzenie w nią z tego miejsca mieszałoby dwie różne odpowiedzialności.
        """
        existing_id = await self._hide_orphan_client_if_visible()
        if existing_id is not None:
            return existing_id

        if self.dry_run:
            logger.info("[dry-run] would create orphan client '%s'", ORPHAN_CLIENT_NAME)
            return -1

        # Use literal SQL to avoid touching ClientStatus enum imports here
        result = await self.db.execute(
            text(
                """
                INSERT INTO clients (name, status, notes, nda_signed, hidden, created_at, updated_at)
                VALUES (:name, CAST(:status AS clientstatus), :notes, false, true, NOW(), NOW())
                RETURNING id
                """
            ),
            {
                "name": ORPHAN_CLIENT_NAME,
                "status": "inactive",
                "notes": (
                    "Auto-utworzony przez Traffit importer dla osób kontaktowych "
                    "ORAZ rekrutacji bez przypisanego klienta. Po migracji można "
                    "je ręcznie przenieść do właściwych klientów lub usunąć cały "
                    "bucket."
                ),
            },
        )
        new_id = result.scalar_one()
        await self.db.commit()
        logger.info("Created orphan client (id=%d)", new_id)
        return new_id

    async def _hide_orphan_client_if_visible(self) -> Optional[int]:
        """Zwróć id worka sierot i ukryj go, jeśli jest jeszcze widoczny.

        ``None`` = worek nie istnieje (zakładanie zostaje leniwe — instalacja bez
        sierot nie dostaje pustego wiersza w liście klientów).

        Osobna metoda, a nie gałąź w ``_ensure_orphan_client``, bo TAMTO jest
        wołane LENIWIE — dopiero gdy w danym biegu trafi się sierota. Nocna delta
        widzi tylko rekordy zmienione w Traffitcie, więc naprawa wiersza
        założonego przed tą zmianą mogłaby czekać na pełny reconcile (tygodniowy),
        a przy częstych redeployach — dowolnie długo. Dlatego woła to też start
        fazy ``jobs``: jeden SELECT na bieg, UPDATE wyłącznie gdy flaga jest zła
        (bez bumpowania ``updated_at`` bez powodu).
        """
        result = await self.db.execute(
            select(Client.id, Client.hidden).where(Client.name == ORPHAN_CLIENT_NAME)
        )
        row = result.first()
        if row is None:
            return None
        orphan_id, is_hidden = row
        if not is_hidden and not self.dry_run:
            await self.db.execute(
                text("UPDATE clients SET hidden = true WHERE id = :id"),
                {"id": orphan_id},
            )
            await self.db.commit()
            logger.info(
                "Orphan client (id=%d) ukryty — worek techniczny nie należy do "
                "listy klientów",
                orphan_id,
            )
        return orphan_id

    async def _build_client_external_id_map(self) -> dict[str, int]:
        """Pull current Nexus state: external_id (Traffit) → Nexus client.id."""
        result = await self.db.execute(
            select(Client.id, Client.external_id).where(
                Client.external_source == "traffit",
                Client.external_id.is_not(None),
            )
        )
        return {ext: nid for nid, ext in result.all() if ext is not None}

    async def _probe_total(self, path: str, phase: str) -> int:
        """Best-effort ``total_source`` probe. Never gates the phase.

        ``total_source`` is INFORMATIONAL — it only feeds the progress
        percentage in logs. Until 2026-08-10 nine phases wrapped this call in a
        try/except that recorded an error and RETURNED, so one flaky count call
        meant ZERO records imported that night for candidates, jobs, pipelines,
        sources and the master-data phases alike.

        Worse, the message carries no ``ext=``/``id=``, so it is unattributable:
        ``_blocking_errors`` counts unattributable errors as blocking and the
        quarantine has no row to park, which means a persistently failing probe
        froze the delta watermark forever and pinned ``checks.traffit`` to
        ``degraded`` — with no records to show for it. ``candidate_activities``
        was already exempted from this trap (with that reasoning written out);
        this helper extends the same rule to the remaining phases.
        """
        try:
            return await self.traffit.total_count(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("%s total_count probe failed: %r", phase, e)
            return 0

    # ── Phase: clients ──────────────────────────────────────────────────────

    async def import_clients(self) -> PhaseProgress:
        progress = PhaseProgress(phase="clients", started_at=datetime.now(timezone.utc))
        progress.total_source = await self._probe_total("/clients/", "Clients")

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
            was_insert: Optional[bool] = None
            try:
                # SAVEPOINT per rekord, tak jak w `import_workflows` /
                # `import_candidates`. Goły `db.rollback()` w handlerze podnosi
                # SESJĘ, a ta faza commituje RAZ na końcu — więc jeden zły wiersz
                # kasował wszystko, co zapisano wcześniej w tym biegu, podczas gdy
                # `progress.inserted`/`updated` (zbijane przed rollbackiem) dalej
                # raportowały te rekordy jako zapisane. Dokładnie ten tryb awarii
                # opisano dla `workflows`: `processed: 2, updated: 2, errors: 1`
                # znaczyło „0 z 2 zapisanych", 23 biegi z rzędu.
                async with self.db.begin_nested():
                    result = await self.db.execute(_UPSERT_CLIENT, payload)
                    row = result.fetchone()
                    if row is not None:
                        was_insert = bool(row[1])
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert client ext={payload.get('external_id')}: {e!r}"
                )
                # Savepoint już cofnął sam zapis, więc transakcja zewnętrzna
                # żyje i rollback SESJI byłby tym, co wyrzuca paczkę. Podnosimy
                # ją tylko przy utracie połączenia — wtedy `ROLLBACK TO SAVEPOINT`
                # nie ma dokąd pójść i każdy kolejny wiersz fazy padnie.
                if needs_session_rollback(e, past_savepoint=False):
                    await self.db.rollback()
                continue
            # Liczone dopiero, gdy savepoint się utrzymał — inkrementacja w
            # środku jest tym, co na prodzie kazało statystykom opisywać PRÓBY
            # zamiast ZAPISÓW.
            if was_insert is None:
                continue
            if was_insert:
                progress.inserted += 1
            else:
                progress.updated += 1

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
        progress.total_source = await self._probe_total("/crm_persons/", "Contacts")

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
            was_insert: Optional[bool] = None
            try:
                # SAVEPOINT per rekord, tak jak w `import_workflows` /
                # `import_candidates`. Goły `db.rollback()` w handlerze podnosi
                # SESJĘ, a ta faza commituje RAZ na końcu — więc jeden zły wiersz
                # kasował wszystko, co zapisano wcześniej w tym biegu, podczas gdy
                # `progress.inserted`/`updated` (zbijane przed rollbackiem) dalej
                # raportowały te rekordy jako zapisane. Dokładnie ten tryb awarii
                # opisano dla `workflows`: `processed: 2, updated: 2, errors: 1`
                # znaczyło „0 z 2 zapisanych", 23 biegi z rzędu.
                async with self.db.begin_nested():
                    result = await self.db.execute(_UPSERT_CONTACT, payload)
                    row = result.fetchone()
                    if row is not None:
                        was_insert = bool(row[1])
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert contact ext={payload.get('external_id')}: {e!r}"
                )
                # Savepoint już cofnął sam zapis, więc transakcja zewnętrzna
                # żyje i rollback SESJI byłby tym, co wyrzuca paczkę. Podnosimy
                # ją tylko przy utracie połączenia — wtedy `ROLLBACK TO SAVEPOINT`
                # nie ma dokąd pójść i każdy kolejny wiersz fazy padnie.
                if needs_session_rollback(e, past_savepoint=False):
                    await self.db.rollback()
                continue
            if was_insert is None:
                continue
            if was_insert:
                progress.inserted += 1
            else:
                progress.updated += 1

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
        progress.total_source = await self._probe_total("/users/", "Users")

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
            # `None` = nic nie zapisano (wiersz nie wrócił); "inserted"/"updated"
            # rozstrzygane dopiero po utrzymaniu się savepointu.
            outcome: Optional[str] = None
            fresh_user_id: Optional[int] = None
            try:
                # SAVEPOINT per rekord, tak jak w `import_workflows` /
                # `import_candidates`. Goły `db.rollback()` w handlerze podnosi
                # SESJĘ, a ta faza commituje RAZ na końcu — więc jeden zły wiersz
                # kasował wszystko, co zapisano wcześniej w tym biegu, podczas gdy
                # `progress.inserted`/`updated` (zbijane przed rollbackiem) dalej
                # raportowały te rekordy jako zapisane.
                async with self.db.begin_nested():
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
                        outcome = "updated"
                    else:
                        result = await self.db.execute(_UPSERT_USER, payload)
                        row = result.fetchone()
                        if row is not None:
                            if row[1]:
                                outcome = "inserted"
                                fresh_user_id = row[0]
                            else:
                                outcome = "updated"
            except Exception as e:  # noqa: BLE001
                msg = f"upsert user ext={payload['external_id']}: {e!r}"
                progress.add_error(msg)
                if progress.errors <= 5:
                    logger.warning("User upsert error: %s", msg[:300])
                # Savepoint już cofnął sam zapis, więc transakcja zewnętrzna
                # żyje i rollback SESJI byłby tym, co wyrzuca paczkę. Podnosimy
                # ją tylko przy utracie połączenia — wtedy `ROLLBACK TO SAVEPOINT`
                # nie ma dokąd pójść i każdy kolejny wiersz fazy padnie.
                if needs_session_rollback(e, past_savepoint=False):
                    await self.db.rollback()
                continue
            if outcome == "inserted":
                progress.inserted += 1
                # Cache fresh email→id dla intra-run dedup (gdyby Traffit miał
                # 2 userów z tym samym emailem). Po savepoincie, nie w środku —
                # cofnięty wiersz nie może zostawić po sobie id w mapie.
                if fresh_user_id is not None:
                    nexus_email_to_id[payload["email"]] = fresh_user_id
            elif outcome == "updated":
                progress.updated += 1

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
        progress.total_source = await self._probe_total("/workflows/", "Workflows")

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
                # SAVEPOINT per workflow. The old handler called
                # `self.db.rollback()`, which rolls back the SESSION — and this
                # phase commits once at the very end, so a single bad workflow
                # discarded every workflow already written in the same run.
                # On prod that turned `processed: 2, updated: 2, errors: 1`
                # into "0 of 2 persisted", 23 runs in a row.
                async with self.db.begin_nested():
                    tmpl_result = await self.db.execute(
                        _UPSERT_PIPELINE_TEMPLATE, template_payload
                    )
                    tmpl_row = tmpl_result.fetchone()
                    if tmpl_row is None:
                        continue
                    template_id = tmpl_row[0]
                    was_insert = bool(tmpl_row[1])

                    # Stage defs — sortuj po `order`, potem mapuj kolejność 0..N
                    states = detail.get("states") or []
                    states_sorted = sorted(
                        states, key=lambda s: (s.get("order") or 0, s.get("id") or 0)
                    )
                    await self._rewrite_template_stage_defs(template_id, states_sorted)
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert workflow ext={template_payload.get('external_id')}: {e!r}"
                )
                continue

            # Counted only once the savepoint actually held. Incrementing
            # inside it is how prod came to report `updated: 2` for a run that
            # persisted nothing — the stats described attempts, not writes.
            if was_insert:
                progress.inserted += 1
            else:
                progress.updated += 1

        if not self.dry_run:
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Workflows import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    async def _rewrite_template_stage_defs(
        self, template_id: int, states_sorted: list[dict[str, Any]]
    ) -> None:
        """Re-lay a template's stage defs to match Traffit, collision-free.

        `pipeline_stage_defs` carries two SET-WIDE unique constraints —
        `uq_stage_order_in_template (template_id, "order")` and
        `uq_stage_name_in_template (template_id, name)` — while rows are
        written ONE AT A TIME, keyed on `(external_source, external_id)`.
        Rewriting a set row by row under a set-wide constraint only works if
        no INTERMEDIATE state collides, and a reorder in Traffit guarantees
        one: state B claims order 3 while state A, which still holds order 3,
        has not been rewritten yet. Postgres rejects it mid-loop. That is the
        prod failure — `duplicate key ... "uq_stage_order_in_template"`,
        `Key (template_id, "order")=(15, 0) already exists` — and no cyclic
        swap has a safe write order, so sequencing cannot fix it.

        Neither constraint is DEFERRABLE (entrypoint.sh already works around
        the same edge with a shift trick), so we park first: every row of the
        template goes to `("order" = -id, name = '~<id>')`. Both are unique
        per row because `id` is the PK, negative orders can never meet the
        final layout (all >= 0), and the sentinel name is not a shape a real
        Traffit state has. The band is then empty and the real layout applies
        in any order.

        Rows Traffit no longer sends are NOT deleted — `candidate_stages.
        stage_def_id` points at them — so they are re-homed after the live
        ones instead, keeping their relative order and their names.
        """
        existing = list(
            await self.db.execute(
                text(
                    """
                    SELECT id, external_id, name, "order"
                    FROM pipeline_stage_defs
                    WHERE template_id = CAST(:t AS integer)
                    ORDER BY "order"
                    """
                ),
                {"t": template_id},
            )
        )

        # Traffit workflows can have duplicate state names within one workflow
        # (e.g. B2B has two "Zaakceptowany" states). uq_stage_name_in_template
        # forbids that, so suffix later occurrences with the source state id.
        seen_names: set[str] = set()
        incoming: list[dict[str, Any]] = []
        for idx, state in enumerate(states_sorted):
            sd = traffit_workflow_state_to_stage_def(state, idx)
            base = sd["name"]
            if base in seen_names:
                sd["name"] = f"{base} (#{sd['traffit_state_id']})"[:100]
            seen_names.add(sd["name"])
            incoming.append(sd)

        live_ext = {sd["traffit_state_id"] for sd in incoming}
        stale = [r for r in existing if r.external_id not in live_ext]

        if existing:
            # Park. `id` is the PK, so both parked values are unique per row.
            await self.db.execute(
                text(
                    """
                    UPDATE pipeline_stage_defs
                       SET "order" = -id, name = '~' || id::text
                     WHERE template_id = CAST(:t AS integer)
                    """
                ),
                {"t": template_id},
            )

        for sd in incoming:
            # Idempotent UPSERT per stage_def (was DELETE+INSERT but that broke
            # the FK from candidate_stages.stage_def_id on daily re-runs).
            # ON CONFLICT (external_source, external_id) DO UPDATE keeps FK
            # references intact while updating order/category/etc.
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
                        CAST(:name AS text),
                        CAST(:order AS integer),
                        CAST(:category AS stagecategoryenum),
                        CAST(:is_terminal AS boolean),
                        CAST(:terminal_type AS terminaltype),
                        CAST(:legacy_enum_value AS text),
                        CAST(:external_id AS text),
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

        # Re-home the rows Traffit no longer sends, after the live ones. Their
        # names go back untouched unless a live state has taken one — the live
        # state is the current truth, so the retired row yields and is suffixed.
        for offset, row in enumerate(stale):
            name = row.name
            if name in seen_names:
                name = f"{name} (#{row.external_id or row.id})"[:100]
            if name in seen_names:
                # A live state is literally named like the suffixed form.
                # Retrying the suffix cannot converge — past 100 chars the
                # truncation returns the same string and the loop spins — so
                # fall back to the parked sentinel, which `id` makes unique by
                # construction.
                name = f"~{row.id}"
            seen_names.add(name)
            await self.db.execute(
                text(
                    """
                    UPDATE pipeline_stage_defs
                       SET "order" = CAST(:o AS integer),
                           name = CAST(:n AS text),
                           updated_at = NOW()
                     WHERE id = CAST(:i AS integer)
                    """
                ),
                {"o": len(incoming) + offset, "n": name, "i": row.id},
            )

    # ── Faza 5: candidates ──────────────────────────────────────────────────

    async def import_candidates(
        self, since: Optional[datetime] = None
    ) -> PhaseProgress:
        progress = PhaseProgress(
            phase="candidates", started_at=datetime.now(timezone.utc)
        )
        progress.total_source = await self._probe_total("/employees/", "Candidates")

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
        # NOWO wstawieni — ci na pewno nie mają wektora.
        new_candidate_ids: list[int] = []
        # ZAKTUALIZOWANI, ale WYŁĄCZNIE w trybie delta (`since is not None`).
        #
        # Do 2026-08-21 update'y były pomijane całkowicie, ze świadomym
        # uzasadnieniem kosztowym: pełny reconcile dotyka wszystkich ~55 tys.
        # wierszy co tydzień, więc intencja dla każdego z nich kazałaby workerowi
        # przeliczyć całą bazę na Voyage'u raz w tygodniu, a `mark_stale`
        # unieważniłby przy okazji CAŁY cache dopasowań — i to za przepisanie
        # wartości, które się nie zmieniły. To uzasadnienie zostaje w mocy i
        # dlatego pełny sweep nadal niczego tu nie zbiera.
        #
        # Ale wniosek „zmieniony przeważnie ma nadal poprawny wektor" był
        # nieprawdziwy: `DO UPDATE SET` nadpisuje `name`, `lastname` i
        # `profile_about`, a dwa pierwsze to dosłownie pierwsze wywołania
        # `parts.append` w `_build_candidate_text_v1`. Kandydat, któremu w
        # Traffit zmieniono profil, zostawał z wektorem sprzed zmiany i z
        # zacache'owanym score'em policzonym z tego samego starego tekstu —
        # rekruter szukał umiejętności dodanej wczoraj i nie znajdował nikogo.
        #
        # Delta godzi jedno z drugim: jej feed jest już PRZEFILTROWANY po
        # `updated_at` w Traffit, więc „updated" znaczy tam realną zmianę u
        # źródła, a wolumen to setki wierszy na noc, nie 55 tysięcy.
        record_updates = since is not None
        updated_candidate_ids: list[int] = []

        # Resumable page cursor — the largest feed (~49k) and the phase every
        # later one depends on. Without it a Coolify restart (every push to
        # main) threw the run away and re-scanned from page 1 next time.
        # Per-mode slots: delta pages are filtered by `since`, full's are not.
        since_iso = since.isoformat() if since else None
        start_page = 1
        _cursor = await self._read_mode_cursor(_CANDIDATES_CURSOR_PHASE, since_iso)
        if (
            _cursor is not None
            and _cursor.get("since") == since_iso
            and _cursor.get("page_size") == self.batch_size
        ):
            start_page = max(1, int(_cursor.get("page") or 1))
            logger.info("Candidates: resuming from page %d", start_page)

        current_page = start_page
        saw_fallback = False
        prev_page = start_page

        async for page_no, items in self.traffit.get_pages(
            "/employees/",
            page_size=self.batch_size,
            filter_=self._delta_filter("updated_at", since),
            start_page=start_page,
        ):
            if page_no < prev_page:
                # Filter rejected (HTTP 400) → client restarted unfiltered from
                # page 1, so page numbers no longer map to `since`.
                saw_fallback = True
            prev_page = page_no
            current_page = page_no
            for raw in items:
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

                # Rozróżnia dwie ścieżki błędu w tym samym `except`: awaria
                # ZAPISU WIERSZA jest już cofnięta przez savepoint, więc transakcja
                # zewnętrzna żyje i sesji rollbackować NIE wolno — to właśnie ten
                # rollback wyrzucał paczkę. Awaria ŚCIEŻKI COMMITA zostawia sesję
                # w stanie nie do użytku i rollbacku wymaga.
                row_committed_to_savepoint = False
                try:
                    # Savepoint, nie goły zapis: bez niego błąd JEDNEGO wiersza
                    # przewraca całą transakcję, a handler ratuje się
                    # `db.rollback()` — czyli rollbackiem SESJI, który wyrzuca
                    # wszystko zapisane od ostatniego commita (do `commit_every`
                    # kandydatów). Ta sama pułapka co przy workflowach wyżej.
                    # Ma to znaczenie zwłaszcza teraz, gdy casty przestały po
                    # cichu ucinać za długie wartości i zaczęły je odrzucać:
                    # pojedynczy zbyt długi rekord ma kosztować SIEBIE, nie paczkę.
                    async with self.db.begin_nested():
                        if existing_id is not None:
                            # Adopt existing candidate (e.g. from talent_radar).
                            params = {
                                "nexus_id": existing_id,
                                "external_id": payload["external_id"],
                                "external_source": payload["external_source"],
                                "name": payload["name"],
                                "lastname": payload["lastname"],
                                "traffit_raw_name": payload["traffit_raw_name"],
                                "traffit_raw_lastname": payload["traffit_raw_lastname"],
                                "traffit_source_updated_at": payload.get(
                                    "traffit_source_updated_at"
                                ),
                                "phone": payload.get("phone"),
                                "linkedin": payload.get("linkedin"),
                                "status": payload["status"],
                                "profile_about": payload.get("profile_about"),
                                "cv_filename": payload.get("cv_filename"),
                                "cv_extracted_data": json.dumps(
                                    payload["cv_extracted_data"]
                                ),
                            }
                            result = await self.db.execute(
                                _UPDATE_CANDIDATE_ADOPT, params
                            )
                            row = result.fetchone()
                            if row is None:
                                continue
                            candidate_id = row[0]
                            progress.updated += 1
                            adopted += 1
                            if record_updates:
                                updated_candidate_ids.append(candidate_id)
                        else:
                            params = dict(payload)
                            params["cv_extracted_data"] = json.dumps(
                                payload["cv_extracted_data"]
                            )
                            result = await self.db.execute(_UPSERT_CANDIDATE, params)
                            row = result.fetchone()
                            if row is None:
                                continue
                            candidate_id = row[0]
                            if row[1]:
                                progress.inserted += 1
                                # Newly inserted — record its email so subsequent
                                # Traffit candidates with the same email adopt it.
                                if email_lc:
                                    email_to_id[email_lc] = row[0]
                                # ...i jego external_id, żeby kolejny rekord o tym
                                # samym ext nie próbował go ukraść innemu wierszowi.
                                ext_to_id[str(payload["external_id"])] = row[0]
                                # Kandydat, którego jeszcze nie było w Nexusie, nie ma
                                # też wektora — a bez wektora nie istnieje w
                                # rekomendacjach, hybrid searchu ani w Marketplace.
                                # Zapisujemy INTENCJĘ (tani INSERT), nie embedujemy tu:
                                # jedno wywołanie Voyage na wiersz zamieniłoby import
                                # 55 tys. kandydatów w 55 tys. sekwencyjnych calli.
                                new_candidate_ids.append(row[0])
                            else:
                                progress.updated += 1
                                if record_updates:
                                    updated_candidate_ids.append(row[0])
                        if payload.get("languages"):
                            from app.services.candidate_language_writer import (
                                sync_candidate_languages_from_source,
                            )

                            await sync_candidate_languages_from_source(
                                self.db,
                                candidate_id=candidate_id,
                                raw_languages=payload["languages"],
                                provenance="traffit",
                                source_ref=f"traffit:{payload['external_id']}",
                            )
                        if payload.get("city") or payload.get("country"):
                            from app.services.candidate_location_writer import (
                                sync_candidate_location_from_source,
                            )

                            await sync_candidate_location_from_source(
                                self.db,
                                candidate_id=candidate_id,
                                city=payload.get("city"),
                                country=payload.get("country"),
                                overwrite_existing=True,
                            )
                    row_committed_to_savepoint = True
                    since_commit += 1
                    if since_commit >= commit_every:
                        await self._record_new_candidate_index_intent(
                            new_candidate_ids, updated_candidate_ids, progress
                        )
                        if not saw_fallback:
                            await self._write_mode_cursor(
                                _CANDIDATES_CURSOR_PHASE,
                                since_iso,
                                {
                                    "page": current_page,
                                    "since": since_iso,
                                    "page_size": self.batch_size,
                                },
                            )
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
                    # Rollback sesji jest potrzebny w DWÓCH przypadkach, nie w jednym.
                    #
                    # Pierwszy to awaria ścieżki commita (flaga True) — savepoint
                    # został już zamknięty, więc sesji nie podnosi nic innego.
                    #
                    # Drugi wyszedł dopiero z adversarialnego przeglądu i jest
                    # groźniejszy: gdy backend Postgresa ZNIKA (restart, failover,
                    # `idle_in_transaction_session_timeout`, reaper OOM), savepoint
                    # NIE MA SIĘ JAK wycofać. Sesja wpada w `PendingRollbackError` i
                    # jedynym, co ją podnosi, jest właśnie `rollback()`. Flaga jest
                    # wtedy False, więc sam warunek `row_committed_to_savepoint`
                    # świadomie pomijał ratunek: każdy kolejny wiersz padał, a cała
                    # faza rzucała wyjątek zamiast zwrócić `PhaseProgress` — czyli
                    # jeden przelotny blip połączenia kosztował RESZTĘ nocnego
                    # importu zamiast jednej paczki.
                    #
                    # `is_active` / `in_transaction()` do rozróżnienia się NIE
                    # nadają — przy martwym połączeniu raportują dokładnie to samo
                    # co przy zdrowym (zmierzone). Robi to `connection_invalidated`:
                    # False dla błędu instrukcji, True dla utraty połączenia.
                    if needs_session_rollback(
                        e, past_savepoint=row_committed_to_savepoint
                    ):
                        await self.db.rollback()
                        since_commit = 0

        if not self.dry_run:
            await self._record_new_candidate_index_intent(
                new_candidate_ids, updated_candidate_ids, progress
            )
            # Reached the end of the feed → retire this mode's slot so the next
            # run starts a fresh pass.
            await self._clear_mode_cursor(_CANDIDATES_CURSOR_PHASE, since_iso)
            # Unconditional. It used to be `if since_commit > 0 or had_intents`,
            # with `had_intents` captured BEFORE the call above because that
            # helper clears the list in a `finally` (checking after it always
            # read False and dropped the last batch of intents). The retire now
            # always needs persisting, so the guard — and the trap it carried —
            # is gone: committing with nothing staged is a no-op transaction.
            await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Candidates import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    async def _record_new_candidate_index_intent(
        self,
        new_ids: list[int],
        updated_ids: list[int],
        progress: PhaseProgress,
    ) -> None:
        """Zapisz intencję reindeksu i wyczyść oba bufory.

        Obejmuje NOWYCH i ZAKTUALIZOWANYCH. Do 2026-08-21 tylko nowych — a
        importer Traffita jest dominującą ścieżką zapisu w tym produkcie, więc
        kandydat, któremu zmieniło się imię, profil albo umiejętności, zostawał
        z wektorem sprzed zmiany i z zacache'owanym score'em policzonym z tego
        samego, starego tekstu. Objaw: rekruter szuka umiejętności dodanej
        wczoraj, a kandydat się nie pojawia; nic tego nie wykrywa, bo
        `/api/health.checks.traffit` to sonda ŚWIEŻOŚCI, nie kompletności.

        Zaktualizowani dodatkowo unieważniają cache dopasowań — nowi nie mają
        w nim jeszcze żadnego wiersza, więc `mark_stale` byłby dla nich no-opem.

        Best-effort: kolejka indeksu nigdy nie może wywalić importu — kandydat
        w bazie bez wektora jest gorszy niż kandydat z wektorem, ale kandydat,
        którego w ogóle nie ma, jest gorszy od obu.
        """
        if not new_ids and not updated_ids:
            return
        try:
            from app.services.index_outbox_service import (
                CANDIDATE,
                record_bulk_reindex,
            )
            from app.services.match_score_cache import (
                mark_stale_for_many_candidates,
            )

            # Dedup: adopcja potrafi trafić do obu buforów w tym samym biegu.
            all_ids = list(dict.fromkeys([*new_ids, *updated_ids]))
            await record_bulk_reindex(self.db, CANDIDATE, all_ids)
            if updated_ids:
                await mark_stale_for_many_candidates(
                    self.db, list(dict.fromkeys(updated_ids))
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Recording reindex intent failed for %d new / %d updated "
                "candidates: %s",
                len(new_ids),
                len(updated_ids),
                e,
            )
            progress.add_error(f"index intent: {e!r}")
        finally:
            new_ids.clear()
            updated_ids.clear()

    # ── Faza 5: jobs ────────────────────────────────────────────────────────

    async def import_jobs(self, since: Optional[datetime] = None) -> PhaseProgress:
        progress = PhaseProgress(phase="jobs", started_at=datetime.now(timezone.utc))
        progress.total_source = await self._probe_total("/recruitments/", "Jobs")

        client_map = await self._build_client_external_id_map()
        workflow_map = await self._build_workflow_external_id_map()
        # Zakładany LENIWIE — dopiero gdy pojawi się pierwsza sierota. Bez tego
        # każda instalacja dostawałaby pustego `__traffit_orphans` w liście
        # klientów, także ta, w której każda rekrutacja ma klienta.
        #
        # Ale JEŚLI worek już istnieje, ukrywamy go od razu — nie czekając na
        # sierotę w tym konkretnym biegu (patrz docstring metody). Wiersz
        # założony przed dodaniem flagi jest widoczny w każdej liście klientów.
        orphan_client_id: Optional[int] = await self._hide_orphan_client_if_visible()
        # Bieżące przypisania w Nexusie — po to, żeby sierota nie odbierała
        # klienta rekrutacji, która już go ma (patrz komentarz przy użyciu).
        existing_job_clients = await self._build_job_client_map()
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

            # Rekrutacje bez znanego klienta lądują u sieroty, nie w koszu.
            #
            # `jobs.client_id` ma NOT NULL od migracji 0120, więc bezklientowy
            # INSERT i tak by się wywalił — ale pominięcie wiersza NIE jest
            # przez to jedyną opcją, tylko najgorszą z możliwych. Kosztowało
            # to na prodzie 28 rekrutacji (`external_id` 38…95, czyli
            # najstarsze rekordy: klient skasowany w Traffit albo nigdy nie
            # przypisany).
            #
            # I nie chodzi o 28 pustych wierszy. `traffit_recruitment_history_
            # to_stage` zwraca None, gdy `job_id` nie ma w mapie, więc razem
            # z rekrutacją przepadała CAŁA historia kandydatów, którzy przez
            # nią przechodzili — a to jest dokładnie ten rodzaj cichej straty,
            # której ten importer ma zapobiegać.
            #
            # Wzorzec nie jest nowy: kontakty robią dokładnie to od zawsze
            # (`import_contacts` → `_ensure_orphan_client`), co opisuje nawet
            # nagłówek tego pliku. Ta sama sytuacja miała dotąd dwa różne
            # rozstrzygnięcia zależnie od fazy; to była asymetria, nie decyzja.
            if payload.get("client_id") is None:
                # Sierota obsługuje BRAK przypisania, nie odbiera istniejącego.
                #
                # UPSERT robi `client_id = COALESCE(EXCLUDED.client_id,
                # jobs.client_id)`. Dopóki bezklientowe rekrutacje były
                # pomijane, ta gałąź nigdy się nie wykonywała i przypisanie w
                # Nexusie było bezpieczne z definicji. Odkąd zawsze podajemy
                # niepustego klienta, COALESCE zawsze bierze wartość
                # przychodzącą — więc rekrutacja zaimportowana kiedyś z realnym
                # klientem zostałaby po cichu przeniesiona do sierot, gdyby
                # tylko jej klient wypadł z `client_map`.
                #
                # To nie jest scenariusz z kasowania klienta (FK na
                # `jobs.client_id` na to nie pozwala), lecz z utraty samego
                # MAPOWANIA: ktoś czyści `external_id`, zmienia
                # `external_source`, scala duplikaty klientów. Klient w Nexusie
                # wtedy dalej istnieje i jest poprawny — gubimy tylko powiązanie
                # z Traffitem, co jest najgorszym możliwym momentem na
                # przepięcie rekrutacji na zastępczego klienta.
                existing_client_id = existing_job_clients.get(payload["external_id"])
                if existing_client_id is not None:
                    payload["client_id"] = existing_client_id
                else:
                    if orphan_client_id is None:
                        orphan_client_id = await self._ensure_orphan_client()
                    payload["client_id"] = orphan_client_id
                # Liczone w OBU gałęziach, bo licznik opisuje to, co przyszło z
                # Traffita („rekrutacja bez rozwiązywalnego klienta"), a nie to,
                # co z nią zrobiliśmy. Gdyby rósł tylko przy pierwszym
                # przypisaniu, po pierwszym biegu wskazywałby 0, podczas gdy
                # rekrutacje dalej siedziałyby u zastępczego klienta — czyli
                # dokładnie ten wzorzec, który ta seria poprawek likwiduje:
                # zielona liczba nad realną luką. Tak licznik jest stabilny
                # między biegami i widać po nim, czy zjawisko rośnie.
                progress.unresolved_client += 1

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
            was_insert: Optional[bool] = None
            try:
                # SAVEPOINT per rekord, tak jak w `import_workflows` /
                # `import_candidates`. Goły `db.rollback()` w handlerze podnosi
                # SESJĘ, a ta faza commituje RAZ na końcu — więc jeden zły wiersz
                # kasował wszystko, co zapisano wcześniej w tym biegu, podczas gdy
                # `progress.inserted`/`updated` (zbijane przed rollbackiem) dalej
                # raportowały te rekordy jako zapisane.
                async with self.db.begin_nested():
                    params = dict(payload)
                    params["custom_fields"] = json.dumps(payload["custom_fields"])
                    result = await self.db.execute(_UPSERT_JOB, params)
                    row = result.fetchone()
                    if row is not None:
                        was_insert = bool(row[1])
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert job ext={payload.get('external_id')}: {e!r}"
                )
                # Savepoint już cofnął sam zapis, więc transakcja zewnętrzna
                # żyje i rollback SESJI byłby tym, co wyrzuca paczkę. Podnosimy
                # ją tylko przy utracie połączenia — wtedy `ROLLBACK TO SAVEPOINT`
                # nie ma dokąd pójść i każdy kolejny wiersz fazy padnie.
                if needs_session_rollback(e, past_savepoint=False):
                    await self.db.rollback()
                continue
            if was_insert is None:
                continue
            if was_insert:
                progress.inserted += 1
            else:
                progress.updated += 1

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
        progress.total_source = await self._probe_total("/talents/", "Talents")

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
            was_insert: Optional[bool] = None
            try:
                # SAVEPOINT per rekord, tak jak w `import_workflows` /
                # `import_candidates`. Goły `db.rollback()` w handlerze podnosi
                # SESJĘ, a ta faza commituje RAZ na końcu — więc jeden zły wiersz
                # kasował wszystko, co zapisano wcześniej w tym biegu, podczas gdy
                # `progress.inserted`/`updated` (zbijane przed rollbackiem) dalej
                # raportowały te rekordy jako zapisane. Dokładnie ten tryb awarii
                # opisano dla `workflows`: `processed: 2, updated: 2, errors: 1`
                # znaczyło „0 z 2 zapisanych", 23 biegi z rzędu.
                async with self.db.begin_nested():
                    result = await self.db.execute(_UPSERT_TALENT_POOL, payload)
                    row = result.fetchone()
                    if row is not None:
                        was_insert = bool(row[1])
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert talent ext={payload.get('external_id')}: {e!r}"
                )
                # Savepoint już cofnął sam zapis, więc transakcja zewnętrzna
                # żyje i rollback SESJI byłby tym, co wyrzuca paczkę. Podnosimy
                # ją tylko przy utracie połączenia — wtedy `ROLLBACK TO SAVEPOINT`
                # nie ma dokąd pójść i każdy kolejny wiersz fazy padnie.
                if needs_session_rollback(e, past_savepoint=False):
                    await self.db.rollback()
                continue
            if was_insert is None:
                continue
            if was_insert:
                progress.inserted += 1
            else:
                progress.updated += 1

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

        # Full reconcile only: re-point `candidates.cv_*` at the CURRENT primary
        # CV before downloading anything.
        #
        # The scan below only ever fills a NULL pointer, so once a candidate has
        # one it is exempt for good — including after Traffit REPLACES the CV.
        # The new file does arrive (import_candidate_files stores it under a new
        # file_id), but `candidates.cv_storage_key`/`cv_filename` stay pinned to
        # the first one forever, and those two columns are what the bulk CV
        # download reads. Net effect: the recruiter downloads a STALE CV while
        # the current one sits in the same database.
        #
        # Conservative on purpose: only re-points when the existing pointer is
        # itself a Traffit-sourced file (the EXISTS below). A CV uploaded
        # directly in Nexus is newer by definition and must never be clobbered
        # by Traffit's copy.
        if since is None and not self.dry_run:
            resynced = await self.db.execute(_RESYNC_STALE_CV_POINTER)
            if resynced.rowcount:
                await self.db.commit()
                # NOT `progress.updated` — that means "CV downloaded" in this
                # phase, and `/sync/status` showing `updated: 120` for 120 fixed
                # pointers and zero downloads would be a lie by aggregation.
                progress.resynced_pointers += resynced.rowcount
                logger.info(
                    "Candidates CV: re-pointed %d stale primary-CV pointer(s)",
                    resynced.rowcount,
                )

        # Full reconcile only: budget + resume cursor, same shape as the files
        # phase. This selection is only PARTLY self-clearing — a successful
        # download fills `cv_storage_key` and drops out, but a candidate with no
        # CV in Traffit at all is counted `skipped` and stays a target forever.
        # So an unbounded pass re-pays for the same `ORDER BY id` prefix (one
        # /files call each) on every run and never reaches the tail, and a
        # Coolify restart mid-sweep loses the position entirely.
        cursor_phase: Optional[str] = None
        scan_limit: Optional[int] = None
        if since is None:
            cursor_phase = _CV_CURSOR_PHASE
            scan_limit = max(1, int(settings.TRAFFIT_SYNC_FULL_FILES_LIMIT))
            _cursor = await self._read_sync_cursor(cursor_phase)
            after_id = int((_cursor or {}).get("after_id") or 0)
            cv_params["after_id"] = after_id
            cv_params["limit"] = scan_limit
            since_clause += " AND id > :after_id"

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
                {"LIMIT :limit" if scan_limit is not None else ""}
                """
            ),
            cv_params,
        )
        targets = list(result)
        progress.total_source = len(targets)
        exhausted = scan_limit is None or len(targets) < scan_limit
        if not targets:
            if cursor_phase is not None and not self.dry_run:
                await self._clear_sync_cursor(cursor_phase)
                await self.db.commit()
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
                if files_resp.status_code in _GONE_STATUS_CODES:
                    # Deleted in Traffit. "Gone" is an ANSWER, not a failure —
                    # retrying cannot change it. Recording it as an error was
                    # doubly wrong: the old message carried no `ext=`/`id=`, so
                    # `_ERROR_REF_RE` could not key it, `_blocking_errors`
                    # counted it as unattributable-and-blocking, and the
                    # quarantine had no ref to park. Four candidates deleted
                    # upstream therefore froze this phase's watermark forever.
                    progress.gone_upstream += 1
                    # Licznik znika razem ze statystykami biegu, więc sam w
                    # sobie nie mówi NIKOMU, że tej osoby już u źródła nie ma.
                    # Nagrobek zostaje na wierszu.
                    if not self.dry_run:
                        res = await self.db.execute(
                            _TOMBSTONE_CANDIDATE, {"id": row.id}
                        )
                        if res.rowcount:
                            progress.tombstoned += 1
                    continue
                if files_resp.status_code != 200:
                    # Everything else IS retryable — and now attributable, so a
                    # persistently failing row can be quarantined instead of
                    # blocking the other 49k.
                    progress.add_error(
                        f"list files candidate ext={traffit_id}: "
                        f"HTTP {files_resp.status_code}"
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
                if content_resp.status_code in _GONE_STATUS_CODES:
                    # File removed in Traffit between listing and fetch.
                    progress.gone_upstream += 1
                    continue
                if content_resp.status_code != 200:
                    progress.add_error(
                        f"fetch file {file_id} candidate ext={traffit_id}: "
                        f"HTTP {content_resp.status_code}"
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
                    if cursor_phase is not None:
                        # Same transaction as the rows it accounts for.
                        #
                        # `row.id` is the candidate this iteration just stored,
                        # and the scan is `ORDER BY id`, so everything below it
                        # has already been considered — including the ones that
                        # came back `skipped` (no CV in Traffit). Moving the
                        # cursor past those is correct, not a miss: they were
                        # examined this run, and because they keep
                        # `cv_storage_key IS NULL` they re-enter the target set
                        # on the next full pass anyway.
                        await self._write_sync_cursor(
                            cursor_phase, {"after_id": row.id}
                        )
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

        if not self.dry_run:
            if cursor_phase is not None:
                if exhausted:
                    await self._clear_sync_cursor(cursor_phase)
                else:
                    await self._write_sync_cursor(
                        cursor_phase, {"after_id": targets[-1].id}
                    )
                await self.db.commit()
            elif since_commit > 0:
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

        # Full reconcile only: budget + resume cursor. The `"?"` selection does
        # NOT shrink on its own — a candidate whose CV yields no name stays `"?"`
        # forever — so an unbounded `ORDER BY id` sweep re-pays for the same
        # prefix every pass (one LLM call per row) and never reaches the tail.
        # Delta keeps its narrow `since` scope and needs neither.
        cursor_phase: Optional[str] = None
        scan_limit: Optional[int] = None
        after_id = 0
        if since is None:
            cursor_phase = _ENRICH_NAMES_CURSOR_PHASE
            scan_limit = max(1, int(settings.TRAFFIT_SYNC_ENRICH_NAMES_LIMIT))
            _cursor = await self._read_sync_cursor(cursor_phase)
            after_id = int((_cursor or {}).get("after_id") or 0)

        stats = await backfill_missing_names(
            self.db,
            since=since,
            after_id=after_id or None,
            limit=scan_limit,
            prefer_llm=True,
        )
        progress.total_source = stats.get("total", 0)
        progress.processed = stats.get("processed", 0)
        progress.inserted = stats.get("resolved", 0)
        progress.skipped = stats.get("unresolved", 0)
        # Report failures as ATTRIBUTABLE per-row errors. Assigning
        # `progress.errors` directly (as this did until 2026-08-10) leaves
        # `error_refs` empty, and `_blocking_errors` treats every unattributable
        # error as blocking with nothing for the quarantine to park — so a single
        # permanently unparseable CV froze the GLOBAL daily watermark forever and
        # pinned `checks.traffit=degraded`. The entity word is deliberately not
        # bare "candidate": the candidates phase keys its refs on the Traffit
        # external id, and these are Nexus ids, so sharing the word would merge
        # two different id spaces into one quarantine entry.
        for cand_id in stats.get("error_ids") or []:
            progress.add_error(f"enrich candidate_name id={cand_id}: backfill failed")
        leftover = int(stats.get("errors") or 0) - len(stats.get("error_ids") or [])
        if leftover > 0:  # defensive: keep the count honest if ids go missing
            progress.errors += leftover

        # Ta faza pisze `raw_cv_text`, `skills`, `experience`, `education`,
        # `ai_summary` i `years_it_experience` — sześć wejść do tekstu
        # embeddingu — i do 2026-08-21 nie zapisywała ŻADNEJ intencji reindeksu.
        # Skutek był najgorszy z możliwych: kandydat wjeżdżał tu jako „? ?",
        # czyli z wektorem zbudowanym praktycznie z niczego, po wzbogaceniu
        # dostawał pełny profil w bazie — i zostawał z tamtym pustym wektorem na
        # zawsze. Nie wchodził do puli retrievalu, więc żaden scoring nie miał
        # szansy go odzyskać, a `checks.traffit` świecił na zielono (to sonda
        # świeżości, nie kompletności).
        #
        # `backfill_missing_names` nie zwraca listy zapisanych id, więc
        # wyprowadzamy je z bazy: `updated_at` ma `onupdate=func.now()`, a
        # poprzednie fazy commitują przed startem tej, więc stempel nowszy niż
        # `progress.started_at` w przemiecionym zakresie id to dokładnie wiersze,
        # które ten backfill zapisał. Nadmiarowy wpis nic nie psuje (worker
        # przeliczy raz za dużo); pominięty kosztuje kandydata niewidocznego
        # w wyszukiwaniu.
        await self._record_enriched_candidate_index_intent(
            progress, after_id=after_id, last_id=stats.get("last_id")
        )

        if cursor_phase is not None:
            # Short batch = swept to the end → retire the cursor so the next full
            # run starts a fresh pass (otherwise it parks at the tail forever).
            if scan_limit is None or progress.total_source < scan_limit:
                await self._clear_sync_cursor(cursor_phase)
            elif stats.get("last_id") is not None:
                await self._write_sync_cursor(
                    cursor_phase, {"after_id": stats["last_id"]}
                )
            else:
                # Unreachable with the current backfill (`last_id = ids[-1]` is
                # always set once `total_source >= 1`), but leaving the cursor
                # untouched here would park the sweep on a stale position
                # forever — the exact no-op failure this phase is being fixed
                # for. Clearing costs one re-swept pass; silence costs the tail.
                await self._clear_sync_cursor(cursor_phase)
            await self.db.commit()

        progress.finished_at = datetime.now(timezone.utc)
        logger.info("Enrich missing names done: %s", stats)
        return progress

    async def _record_enriched_candidate_index_intent(
        self,
        progress: PhaseProgress,
        *,
        after_id: int,
        last_id: Optional[int],
    ) -> None:
        """Intencja reindeksu + unieważnienie cache'u dla wzbogaconych CV.

        Best-effort, jak `_record_candidate_index_intent`: kolejka indeksu nie
        może wywalić nocnego syncu.
        """
        if last_id is None:
            return
        try:
            rows = await self.db.execute(
                text(
                    """
                    SELECT id FROM candidates
                    WHERE external_source = 'traffit'
                      AND id > :after_id
                      AND id <= :last_id
                      AND updated_at >= :started_at
                    """
                ),
                {
                    "after_id": after_id or 0,
                    "last_id": last_id,
                    "started_at": progress.started_at,
                },
            )
            touched = [r[0] for r in rows.fetchall()]
            if not touched:
                return

            from app.services.index_outbox_service import (
                CANDIDATE,
                record_bulk_reindex,
            )
            from app.services.match_score_cache import (
                mark_stale_for_many_candidates,
            )

            await record_bulk_reindex(self.db, CANDIDATE, touched)
            await mark_stale_for_many_candidates(self.db, touched)
            # Własny commit: w trybie delta ta faza nie ma innego, a intencje
            # wiszące w niezacommitowanej sesji przepadłyby przy pierwszym
            # rollbacku kolejnej fazy.
            await self.db.commit()
            logger.info(
                "Enrich missing names: reindex intent for %d enriched candidate(s)",
                len(touched),
            )
        except Exception as e:  # noqa: BLE001
            # Świadomie sam log, bez `progress.add_error`: błąd bez `ext=`/`id=`
            # jest dla `_blocking_errors` NIEATRYBUTOWALNY, więc zamroziłby
            # globalny watermark dzienny, a kwarantanna nie miałaby czego
            # zaparkować — dokładnie ta pułapka, którą ta faza już raz dostała.
            # Nieodświeżony indeks jest gorszy od aktualnego, ale zatrzymany
            # sync jest gorszy od obu.
            logger.warning("Enrich missing names: reindex intent failed: %s", e)

    # ── Faza A: candidates-files (multi-file CV w candidate_documents) ──────

    async def _upsert_candidate_document(self, doc_params: dict[str, Any]) -> None:
        """Insert/update one candidate document, tolerant of the one-active-
        primary-CV invariant.

        The upsert already handles ``(external_source, external_id)`` conflicts.
        But a candidate may hold only ONE active primary CV
        (``ux_candidate_documents_active_primary_cv``), and when two Traffit
        files both arrive flagged ``is_primary`` the second insert violates it.
        That IntegrityError is unattributable, so before this it froze the whole
        daily-sync watermark permanently (prod: emp 57740 stuck since
        2026-07-31). Here the demote+insert run in a SAVEPOINT; on the collision
        we roll it back and store the file as NON-primary instead — the existing
        primary is kept, nothing is lost, and one ambiguous row no longer blocks
        every other candidate.
        """
        is_primary = bool(doc_params.get("is_primary"))
        try:
            async with self.db.begin_nested():
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
                            "candidate_id": doc_params["candidate_id"],
                            "external_id": doc_params["external_id"],
                        },
                    )
                await self.db.execute(_UPSERT_CANDIDATE_DOCUMENT, doc_params)
        except IntegrityError as ie:
            # Downgrade ONLY the one-active-primary-CV invariant to a non-primary
            # store; any other IntegrityError still surfaces. Prefer the driver's
            # structured constraint name (asyncpg exposes ``constraint_name``) and
            # fall back to the message for wrappers/tests that don't carry it.
            constraint = "ux_candidate_documents_active_primary_cv"
            if getattr(
                ie.orig, "constraint_name", None
            ) != constraint and constraint not in str(ie):
                raise
            logger.warning(
                "candidate %s doc %s: active primary-CV collision — storing "
                "as non-primary",
                doc_params["candidate_id"],
                doc_params["external_id"],
            )
            # Keep Traffit's document_kind — it IS a CV, just not the primary one,
            # and a non-primary CV doesn't touch the constraint; only cede the
            # primary flag.
            async with self.db.begin_nested():
                await self.db.execute(
                    _UPSERT_CANDIDATE_DOCUMENT,
                    {**doc_params, "is_primary": False},
                )

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
        - **full** (`since=None`): przemiata WSZYSTKICH kandydatów Traffita —
          także tych, którzy mają już jakieś pliki — bo brakujący plik u
          kandydata z jednym plikiem był wcześniej nie do odzyskania (patrz
          komentarz przy zapytaniu). Skan jest budżetowany
          (`TRAFFIT_SYNC_FULL_FILES_LIMIT`) i wznawialny kursorem `after_id`,
          więc kolejne biegi kontynuują sweep zamiast startować od zera.
        - **delta** (`since`): bierze kandydatów zmienionych od ostatniego syncu
          (`updated_at >= since`) NAWET jeśli mają już pliki.

        Oba tryby pobierają wyłącznie te `file_id`, których jeszcze nie ma (po
        `external_id`) — nowe/podmienione CV bez re-downloadu istniejących.
        """
        progress = PhaseProgress(
            phase="candidates_files", started_at=datetime.now(timezone.utc)
        )

        # Full mode only: resumable sweep bookkeeping (see the block below).
        cursor_phase: Optional[str] = None
        scan_limit: Optional[int] = None
        if since is None:
            # Full reconcile sweeps EVERY Traffit candidate — not only those
            # holding zero documents, which is what the old
            # ``HAVING count(cd.id) = 0`` gate did. That gate turned "has at
            # least one file" into a PERMANENT exemption: a candidate whose
            # migration pulled 2 of 5 files (the rest lost to a /content
            # non-200 or a timeout) was never revisited, because delta only
            # looks at candidates Traffit itself changed and those historical
            # rows never change again. That is the path by which Nexus ends up
            # holding fewer CVs than Traffit, and no amount of daily syncing
            # could ever close it.
            #
            # Sweeping everyone costs one /files call per candidate (~49k at
            # TRAFFIT_THROTTLE_RPS=5 ≈ 2.7 h) — longer than the gap between
            # Coolify redeploys, so an unbudgeted sweep would be killed
            # mid-run and restart from the first candidate every Sunday,
            # never reaching the tail. Hence: a per-run budget plus an
            # ``after_id`` cursor that carries the sweep across runs. Downloads
            # stay rare — only file_ids missing locally are fetched below.
            cursor_phase = _FILES_CURSOR_PHASE
            scan_limit = max(1, int(settings.TRAFFIT_SYNC_FULL_FILES_LIMIT))
            _cursor = await self._read_sync_cursor(cursor_phase)
            after_id = int((_cursor or {}).get("after_id") or 0)
            logger.info(
                "Candidates files: full sweep from candidate id > %d (limit %d)",
                after_id,
                scan_limit,
            )
            result = await self.db.execute(
                text(
                    """
                    SELECT c.id, c.external_id
                    FROM candidates c
                    WHERE c.external_source = 'traffit'
                      AND c.external_id IS NOT NULL
                      AND c.id > :after_id
                    ORDER BY c.id
                    LIMIT :limit
                    """
                ),
                {"after_id": after_id, "limit": scan_limit},
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
        # A short batch means the sweep reached the last candidate: the pass is
        # complete and the cursor must be cleared, so the NEXT full run starts a
        # fresh pass from the beginning. Without this the cursor would park at
        # the end of the table and the files phase would silently become a
        # permanent no-op — the exact failure mode this fix exists to remove.
        exhausted = scan_limit is None or len(targets) < scan_limit
        if not targets:
            if cursor_phase is not None and not self.dry_run:
                await self._clear_sync_cursor(cursor_phase)
                await self.db.commit()
            progress.finished_at = datetime.now(timezone.utc)
            logger.info("Candidates files: nothing to do (sweep complete)")
            return progress

        # Pre-load existing traffit doc external_ids for the target candidates so
        # neither mode re-downloads files we already have. This is what keeps the
        # full sweep cheap now that it visits candidates who DO have documents:
        # they cost one /files listing and no /content transfers at all.
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
                if files_resp.status_code in _GONE_STATUS_CODES:
                    # Deleted in Traffit. "Gone" is an ANSWER, not a failure —
                    # retrying cannot change it. Recording it as an error was
                    # doubly wrong: the old message carried no `ext=`/`id=`, so
                    # `_ERROR_REF_RE` could not key it, `_blocking_errors`
                    # counted it as unattributable-and-blocking, and the
                    # quarantine had no ref to park. Four candidates deleted
                    # upstream therefore froze this phase's watermark forever.
                    progress.gone_upstream += 1
                    # Licznik znika razem ze statystykami biegu, więc sam w
                    # sobie nie mówi NIKOMU, że tej osoby już u źródła nie ma.
                    # Nagrobek zostaje na wierszu.
                    if not self.dry_run:
                        res = await self.db.execute(
                            _TOMBSTONE_CANDIDATE, {"id": row.id}
                        )
                        if res.rowcount:
                            progress.tombstoned += 1
                    continue
                if files_resp.status_code != 200:
                    # Everything else IS retryable — and now attributable, so a
                    # persistently failing row can be quarantined instead of
                    # blocking the other 49k.
                    progress.add_error(
                        f"list files candidate ext={traffit_id}: "
                        f"HTTP {files_resp.status_code}"
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
                    if content_resp.status_code in _GONE_STATUS_CODES:
                        # File removed in Traffit between listing and fetch.
                        progress.gone_upstream += 1
                        continue
                    if content_resp.status_code != 200:
                        progress.add_error(
                            f"fetch file {file_id} candidate ext={traffit_id}: "
                            f"HTTP {content_resp.status_code}"
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

                    doc_params = {
                        "candidate_id": row.id,
                        "filename": filename[:500],
                        "storage_key": storage_key,
                        "content_type": content_type[:100] if content_type else None,
                        "size_bytes": len(file_bytes),
                        "document_kind": _traffit_document_kind(
                            filename,
                            is_primary=is_primary,
                        ),
                        "is_primary": is_primary,
                        "uploaded_at": uploaded_at,
                        "external_id": ext_id,
                        "external_source": "traffit",
                    }
                    await self._upsert_candidate_document(doc_params)
                    progress.inserted += 1

                since_commit += 1
                if since_commit >= commit_every:
                    if cursor_phase is not None:
                        # Stage the sweep cursor in the SAME transaction as the
                        # documents it accounts for. Committing them separately
                        # would let an interrupted run claim progress over
                        # candidates whose files were rolled back.
                        await self._write_sync_cursor(
                            cursor_phase, {"after_id": row.id}
                        )
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

        if not self.dry_run:
            if cursor_phase is not None:
                # Advance (or retire) the sweep cursor in the closing
                # transaction, which also flushes any rows still staged.
                #
                # NOTE: this advances past candidates that FAILED this run —
                # `targets[-1].id` is the batch's last id, not the last success.
                # Deliberate. Parking the cursor on a failure instead would make
                # every later run re-scan from that row, so one permanently
                # broken candidate would stall the sweep forever — the exact
                # poison-row freeze that TRAFFIT_MAX_ROW_ATTEMPTS/quarantine
                # exists to prevent, reintroduced one layer down. Failures are
                # not swallowed: `add_error` puts them in `error_refs`, the
                # orchestrator quarantines them and stamps the phase
                # `last_status='errors'`, so they surface in GET /sync/status.
                # Their retry is the next fresh pass (after `exhausted` clears
                # the cursor), which is also why a batch of listing errors keeps
                # `since_commit` below `commit_every` and delays the mid-run
                # cursor writes above — an interrupted error-heavy run simply
                # re-covers more ground next time.
                if exhausted:
                    await self._clear_sync_cursor(cursor_phase)
                else:
                    await self._write_sync_cursor(
                        cursor_phase, {"after_id": targets[-1].id}
                    )
                await self.db.commit()
            elif since_commit > 0:
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
        progress.total_source = await self._probe_total(
            "/employees/recruitment_history", "Pipelines"
        )

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

        # SAVEPOINT per record keeps a single malformed history event (for
        # example withdrawn_requires_reason) from rolling back the batch.
        # The batch itself commits only after RecruitmentProcess is synced, so
        # a crash cannot persist one side of the canonical pair without the
        # other.
        # Wsad trzyma FOR UPDATE na wszystkich swoich kandydatach i ofertach aż
        # do commitu, więc 100 (jak w pozostałych fazach tego pliku) zamiast 500
        # skraca okno rywalizacji z bulk-move; trwałość per-wiersz zapewnia
        # `_replay_stage_rows`, nie rozmiar wsadu.
        commit_every = 100
        unresolved_withdrawn = 0
        # (payload, rejection_reason_id, was_insert) — payload zostaje, bo bez
        # niego nieudany wsad nie da się odtworzyć wiersz po wierszu.
        pending_rows: list[tuple[dict[str, Any], Optional[int], bool]] = []

        # Resumable page cursor. This is the second-largest feed (~166k stage
        # moves) and it sits 12th of 14 in the phase plan, so a Coolify restart —
        # which happens on every push to main — used to throw away the whole run
        # and start again from page 1 the following week. With deploys more
        # frequent than the weekly full reconcile, the tail of this feed could
        # never be reached, and the tail is candidate stages: the recruitment
        # history itself. Slots are per mode for the same reason as activities —
        # delta page numbers are filtered by `since`, full's are not, so sharing
        # one slot means the nightly delta overwrites and then clears the full
        # sweep's parked position.
        since_iso = since.isoformat() if since else None
        start_page = 1
        _cursor = await self._read_mode_cursor(_PIPELINES_CURSOR_PHASE, since_iso)
        if (
            _cursor is not None
            # The mode slot separates delta from full, NOT one delta window from
            # the next: `since` moves every night. Without this check an
            # interrupted run at page 5 for `since=Day1` would resume at page 5
            # of the `since=Day2` feed and silently skip its pages 1-4 — and a
            # clean finish then advances the watermark, so those rows are gone
            # until a full reconcile.
            and _cursor.get("since") == since_iso
            and _cursor.get("page_size") == self.batch_size
        ):
            # Inclusive resume: re-fetch the last committed page (upserts are
            # idempotent) rather than page+1, so a mid-page commit never skips.
            start_page = max(1, int(_cursor.get("page") or 1))
            logger.info("Pipelines: resuming from page %d", start_page)

        current_page = start_page
        # If the tenant rejects the filter (HTTP 400) the client drops it and
        # restarts UNFILTERED from page 1, so page numbers stop mapping to
        # `since` — stop persisting the cursor for this run once that happens.
        saw_fallback = False
        prev_page = start_page

        async for page_no, items in self.traffit.get_pages(
            "/employees/recruitment_history",
            page_size=self.batch_size,
            filter_=self._delta_filter("created_at", since),
            start_page=start_page,
        ):
            if page_no < prev_page:
                saw_fallback = True
            prev_page = page_no
            current_page = page_no
            for raw in items:
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
                    was_insert = await self._upsert_stage_row(
                        payload, rejection_reason_id
                    )
                except Exception as e:  # noqa: BLE001
                    msg = f"upsert stage ext={payload.get('external_id')}: {e!r}"
                    progress.add_error(msg)
                    if progress.errors <= 5 or progress.errors % 500 == 0:
                        logger.warning("Pipelines upsert error: %s", msg[:300])
                    continue

                if was_insert is None:
                    continue
                pending_rows.append((payload, rejection_reason_id, was_insert))
                if len(pending_rows) >= commit_every:
                    if not saw_fallback:
                        # Staged BEFORE the flush so it lands in the same
                        # transaction as the rows it accounts for — the flush
                        # is what commits. A failed batch rolls both back,
                        # leaving the last good cursor in place.
                        await self._write_mode_cursor(
                            _PIPELINES_CURSOR_PHASE,
                            since_iso,
                            {
                                "page": current_page,
                                "since": since_iso,
                                "page_size": self.batch_size,
                            },
                        )
                    await self._flush_stage_batch(progress, pending_rows)
                    pending_rows.clear()
                    logger.info(
                        "Pipelines progress: %d/%d (inserted=%d updated=%d errors=%d)",
                        progress.processed,
                        progress.total_source,
                        progress.inserted,
                        progress.updated,
                        progress.errors,
                    )

        if not self.dry_run and pending_rows:
            if not saw_fallback:
                await self._write_mode_cursor(
                    _PIPELINES_CURSOR_PHASE,
                    since_iso,
                    {
                        "page": current_page,
                        "since": since_iso,
                        "page_size": self.batch_size,
                    },
                )
            await self._flush_stage_batch(progress, pending_rows)
            pending_rows.clear()

        if not self.dry_run:
            # Reached the end of the feed — retire this mode's slot so the next
            # run starts a fresh pass. Row-level errors do NOT block retiring:
            # they freeze the watermark separately, and the next full scan
            # re-covers them from page 1.
            #
            # Deliberately NOT followed by `self.db.commit()`. This phase owes
            # its batch durability to `_flush_stage_batch` (a bare commit here
            # once cost ~18k stages on the first run, which is why a guard test
            # asserts this function contains no such call). The orchestrator
            # commits right after the phase returns when it records the phase
            # state, and that carries this retire with it; if the phase instead
            # unwinds, the rollback simply leaves the cursor in place and the
            # next run resumes from it.
            await self._clear_mode_cursor(_PIPELINES_CURSOR_PHASE, since_iso)

        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Pipelines import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress

    async def _upsert_stage_row(
        self, payload: dict[str, Any], rejection_reason_id: Optional[int]
    ) -> Optional[bool]:
        """Upsert jednego wiersza `candidate_stages` + hooki kolejki kontaktu.

        Zwraca `was_insert` (albo ``None``, gdy ON CONFLICT nic nie zwrócił).
        Nie commituje — o granicy transakcji decyduje wołający, żeby etap i
        `RecruitmentProcess` trafiły do bazy razem albo wcale.
        """

        async with self.db.begin_nested():
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
                            EXCLUDED.moved_by,
                            candidate_stages.moved_by
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
            return None
        # Kolejka kontaktu wisi na tym samym wierszu co import etapu.
        # Hooki są poza savepointem: nieudany hook nie może wycofać
        # zaimportowanego etapu (są `maybe_*`, czyli best-effort).
        if payload["stage_legacy_enum"] in {"hired", "rejected", "withdrawn"}:
            await maybe_close_contact_opportunity(
                self.db,
                candidate_id=payload["candidate_id"],
                job_id=payload["job_id"],
                actor_user_id=payload["moved_by"],
                reason=(f"traffit_pipeline_terminal:{payload['stage_legacy_enum']}"),
                occurred_at=(
                    payload["contact_source_created_at"] or payload["moved_at"]
                ),
                source="traffit",
                source_external_ref=payload["external_id"],
            )
        else:
            await maybe_ensure_contact_opportunity(
                self.db,
                candidate_id=payload["candidate_id"],
                job_id=payload["job_id"],
                source="traffit",
                source_external_ref=payload["external_id"],
                occurred_at=(
                    payload["contact_source_created_at"] or payload["moved_at"]
                ),
            )
        return bool(row[1])

    async def _flush_stage_batch(
        self,
        progress: PhaseProgress,
        pending_rows: list[tuple[dict[str, Any], Optional[int], bool]],
    ) -> None:
        """Domknij wsad: sync procesów + commit etapów i procesów razem."""

        if not pending_rows:
            return
        pairs = sorted({(p["candidate_id"], p["job_id"]) for p, _, _ in pending_rows})
        try:
            await sync_external_observed_processes(self.db, pairs=pairs)
            await self.db.commit()
        except Exception as e:  # noqa: BLE001
            # Rollback wsadu wyrzucał do `commit_every` zaimportowanych etapów
            # (pierwszy run zgubił tak ~18k), a jedyny ślad — błąd wsadowy — nie
            # ma `ext=<id>`, więc kwarantanna nie ma czego zaparkować i faza
            # zamarza. Odtwarzamy więc wiersz po wierszu: każdy commituje etap
            # RAZEM ze swoim procesem (niezmiennik zachowany), tracimy najwyżej
            # jeden zamiast całego wsadu, a błąd niesie `ext=<id>`.
            logger.warning(
                "Pipelines batch commit failed (%d pairs) — replaying %d rows "
                "individually: %r",
                len(pairs),
                len(pending_rows),
                e,
            )
            await self._replay_stage_rows(progress, pending_rows)
            return
        for _, _, was_insert in pending_rows:
            if was_insert:
                progress.inserted += 1
            else:
                progress.updated += 1

    async def _replay_stage_rows(
        self,
        progress: PhaseProgress,
        pending_rows: list[tuple[dict[str, Any], Optional[int], bool]],
    ) -> None:
        """Odtwórz wsad wiersz po wierszu, każdy w osobnej transakcji."""

        await self.db.rollback()
        for payload, rejection_reason_id, _ in pending_rows:
            try:
                was_insert = await self._upsert_stage_row(payload, rejection_reason_id)
                if was_insert is None:
                    await self.db.rollback()
                    continue
                await sync_external_observed_processes(
                    self.db, pairs=[(payload["candidate_id"], payload["job_id"])]
                )
                await self.db.commit()
            except Exception as e:  # noqa: BLE001
                await self.db.rollback()
                # Format `<verb> <entity> ext=<id>` — patrz `_ERROR_REF_RE`:
                # bez niego błąd jest nieprzypisywalny i blokuje watermark.
                msg = f"replay stage ext={payload.get('external_id')}: {e!r}"
                progress.add_error(msg)
                if progress.errors <= 5 or progress.errors % 500 == 0:
                    logger.warning("Pipelines replay error: %s", msg[:300])
                continue
            if was_insert:
                progress.inserted += 1
            else:
                progress.updated += 1

    # ── Faza 5b: candidate activities ───────────────────────────────────────

    async def _read_sync_cursor(self, phase: str) -> Optional[dict[str, Any]]:
        """Read the resume cursor (JSONB ``cursor_payload``) for a phase row.

        The dedicated ``cursor_*`` columns are safe to use: the orchestrator's
        ``_UPSERT_STATE``/``_get_state`` never touch them (it owns
        ``last_status``/``stats``/``last_synced_at``), so a phase can persist its
        own resume cursor here without being clobbered.
        """
        row = await self.db.execute(
            text("SELECT cursor_payload FROM traffit_sync_state WHERE phase = :p"),
            {"p": phase},
        )
        r = row.fetchone()
        if r is None or r[0] is None:
            return None
        val = r[0]
        if isinstance(val, str):  # some drivers return JSONB as text
            val = json.loads(val)
        return val if isinstance(val, dict) else None

    async def _write_sync_cursor(self, phase: str, payload: dict[str, Any]) -> None:
        """UPSERT the resume cursor onto the phase row (touching ONLY
        ``cursor_payload`` — the row may not exist yet on the first-ever run, and
        the orchestrator owns the other columns)."""
        await self.db.execute(
            text(
                """
                INSERT INTO traffit_sync_state
                    (phase, cursor_payload, created_at, updated_at)
                VALUES (:p, CAST(:cp AS JSONB), NOW(), NOW())
                ON CONFLICT (phase) DO UPDATE SET
                    cursor_payload = CAST(:cp AS JSONB),
                    updated_at = NOW()
                """
            ),
            {"p": phase, "cp": json.dumps(payload)},
        )

    # ── Activities cursor: one row, one slot per mode ───────────────────────
    #
    # Delta and full both resume `candidate_activities` by page number, but the
    # page numbering only means anything within a mode (delta pages are filtered
    # by `since`, full pages are not). They used to share ONE flat payload, so a
    # nightly delta both overwrote the parked full cursor mid-run and then
    # cleared it on a clean finish — the weekly full restarted from page 1 every
    # time and resume in full mode was mechanically present but practically
    # dead. Keeping a named slot per mode fixes both halves; guarding only the
    # clear would not, because the overwrite happens first.

    @staticmethod
    def _cursor_mode(since_iso: Optional[str]) -> str:
        return "full" if since_iso is None else "delta"

    @staticmethod
    def _split_legacy_cursor(payload: dict[str, Any]) -> dict[str, Any]:
        """Migrate a pre-split flat cursor into its owning mode's slot."""
        if "page" not in payload:
            return payload
        mode = "full" if payload.get("since") is None else "delta"
        stray = sorted(payload.keys() & {"delta", "full"})
        if stray:
            # Unreachable via the current write path (a flat payload and mode
            # slots are mutually exclusive), but if some future format ever
            # produced both, wrapping the whole dict would silently discard the
            # nested slots. Say so rather than lose a resume position quietly.
            logger.warning(
                "Resume cursor has a flat 'page' AND mode slot(s) %s — "
                "format drift; keeping the flat cursor under %r, dropping %s",
                stray,
                mode,
                stray,
            )
        return {mode: payload}

    async def _read_mode_cursor(
        self, phase: str, since_iso: Optional[str]
    ) -> Optional[dict[str, Any]]:
        payload = await self._read_sync_cursor(phase) or {}
        return self._split_legacy_cursor(payload).get(self._cursor_mode(since_iso))

    async def _write_mode_cursor(
        self, phase: str, since_iso: Optional[str], entry: dict[str, Any]
    ) -> None:
        # Re-reads before every write so the OTHER mode's slot survives it. That
        # is one extra local round-trip per committed batch (~3.7k on a full
        # activities sweep) — negligible next to the throttled API call that
        # produced the page, and the alternative (caching the other slot for the
        # phase's lifetime) trades correctness for nothing measurable.
        payload = await self._read_sync_cursor(phase) or {}
        payload = self._split_legacy_cursor(payload)
        payload[self._cursor_mode(since_iso)] = entry
        await self._write_sync_cursor(phase, payload)

    async def _clear_mode_cursor(self, phase: str, since_iso: Optional[str]) -> None:
        """Retire only THIS mode's slot; the other mode keeps its position."""
        payload = await self._read_sync_cursor(phase) or {}
        payload = self._split_legacy_cursor(payload)
        payload.pop(self._cursor_mode(since_iso), None)
        if payload:
            await self._write_sync_cursor(phase, payload)
        else:
            await self._clear_sync_cursor(phase)

    async def _clear_sync_cursor(self, phase: str) -> None:
        """Clear the resume cursor (no-op if the row does not exist yet)."""
        await self.db.execute(
            text(
                "UPDATE traffit_sync_state SET cursor_payload = NULL, "
                "updated_at = NOW() WHERE phase = :p"
            ),
            {"p": phase},
        )

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
            # Log and continue rather than returning early: a slow/timed-out
            # probe must not skip the import loop AND note promotion below.
            # total_source is informational only (progress %), so a probe
            # failure must NOT be recorded as a blocking error — otherwise an
            # otherwise-complete run would freeze the watermark and stay
            # `degraded`. The pagination loop below has its own failure path.
            logger.warning("Activities total_count probe failed: %r", e)
            progress.total_source = 0

        cand_map = await self._build_candidate_external_id_map()
        user_map = await self.build_user_id_map()
        logger.info(
            "Activities lookups: candidates=%d users=%d",
            len(cand_map),
            len(user_map),
        )

        commit_every = 500
        since_commit = 0

        # Stage 3 — resumable page cursor. A large catch-up (days of history) is
        # slow and a Coolify deploy restart kills the run mid-stream; without a
        # cursor it would restart from page 1 every time and never persist
        # progress. We store the last committed page on the phase's own
        # traffit_sync_state row and resume here, so progress survives
        # interruptions and the catch-up completes across runs.
        since_iso = since.isoformat() if since else None
        start_page = 1
        _cursor = await self._read_mode_cursor(_ACTIVITIES_CURSOR_PHASE, since_iso)
        if (
            _cursor is not None
            and _cursor.get("since") == since_iso
            and _cursor.get("page_size") == self.batch_size
        ):
            # Inclusive resume: re-fetch the last committed page (idempotent via
            # ON CONFLICT) rather than page+1, so a mid-page commit never skips.
            start_page = max(1, int(_cursor.get("page") or 1))
            logger.info("Activities: resuming from page %d", start_page)

        # Wrap the paginated fetch so a terminal transport failure mid-stream
        # (httpx.ReadTimeout on a large catch-up page, or a non-200 page raised
        # as RuntimeError) stops iteration gracefully instead of aborting the
        # phase. Rows already committed survive; promote_notes below still runs;
        # the recorded (unattributable) error keeps the watermark frozen so the
        # un-fetched tail is re-covered on the next run — never silently lost.
        pagination_error: Optional[Exception] = None
        current_page = start_page
        # If the tenant rejects the filter (400), get_pages drops it and restarts
        # UNFILTERED from page 1 → page numbers no longer map to since_iso, so we
        # stop persisting the cursor for this run (regress detected below).
        saw_fallback = False

        async def _activities_stream():
            nonlocal pagination_error, current_page, saw_fallback
            prev_page = start_page
            try:
                async for page_no, items in self.traffit.get_pages(
                    "/employees/activities",
                    page_size=self.batch_size,
                    filter_=self._delta_filter("created_at", since),
                    start_page=start_page,
                ):
                    if page_no < prev_page:
                        saw_fallback = True
                    prev_page = page_no
                    current_page = page_no
                    for item in items:
                        yield item
            except (httpx.TransportError, RuntimeError) as exc:
                pagination_error = exc

        async for raw in _activities_stream():
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
                    # Stage the resume cursor in the SAME transaction as the row
                    # batch, then one commit → rows + cursor persist atomically
                    # (a row-error rollback drops both, leaving the last good
                    # cursor). Skip once the filter was dropped (page numbers no
                    # longer map to since_iso).
                    if not saw_fallback:
                        await self._write_mode_cursor(
                            _ACTIVITIES_CURSOR_PHASE,
                            since_iso,
                            {
                                "page": current_page,
                                "since": since_iso,
                                "page_size": self.batch_size,
                            },
                        )
                    await self.db.commit()
                    since_commit = 0
                    logger.info(
                        "Activities progress: %d/%d (page %d)",
                        progress.processed,
                        progress.total_source,
                        current_page,
                    )
            except Exception as e:  # noqa: BLE001
                progress.add_error(
                    f"upsert activity ext={payload.get('external_id')}: {e!r}"
                )
                await self.db.rollback()
                since_commit = 0

        if not self.dry_run and since_commit > 0:
            if not saw_fallback:
                await self._write_mode_cursor(
                    _ACTIVITIES_CURSOR_PHASE,
                    since_iso,
                    {
                        "page": current_page,
                        "since": since_iso,
                        "page_size": self.batch_size,
                    },
                )
            await self.db.commit()

        if pagination_error is not None:
            logger.warning(
                "Activities pagination aborted after %d processed: %r — "
                "committed partial batch (cursor at page %d), notes still "
                "promoted, watermark frozen; next run resumes from the cursor",
                progress.processed,
                pagination_error,
                current_page,
            )
            progress.add_error(
                f"activities pagination incomplete: {pagination_error!r}"
            )
        elif not self.dry_run:
            # Full, uninterrupted fetch — clear the cursor so the next run (after
            # the watermark advances → a different `since`) starts fresh. Row
            # errors do NOT block clearing: they freeze the watermark separately
            # and the next full re-scan (fresh cursor) re-covers them.
            #
            # But clear ONLY a cursor belonging to THIS run's mode. Delta and
            # full share one phase row while resuming on different keys (delta
            # carries a `since` timestamp, full carries None), and this used to
            # clear whatever it found: an interrupted full reconcile parked its
            # page, then the very next clean nightly delta wiped it, so the
            # following week's full restarted from page 1 — resume in full mode
            # was mechanically present and practically dead. Matching on
            # "is this the same mode" (rather than the exact `since`) also
            # retires a stale cursor left by an older window of the same mode,
            # instead of letting it linger unreadable forever.
            await self._clear_mode_cursor(_ACTIVITIES_CURSOR_PHASE, since_iso)
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
        progress.total_source = await self._probe_total("/sources/", "Sources")

        cand_map = await self._build_candidate_external_id_map()

        # Aggregate per candidate w pamięci — przy 75k records to OK
        # (każdy record ~200B → ~15MB max).
        per_candidate: dict[int, list[dict[str, Any]]] = {}

        # /sources/ endpoint na tenant b2bnetwork ma server-side bug w paginacji:
        # losowe HTTP 500 na specyficznych stronach (np. p6, p8, p11 przy size=10),
        # nawet przy page_size=10. Cap do 10 (mniej "złych" stron) + skip_on_5xx
        # żeby nie ubić importu z powodu chwiejnego endpoint'u Traffita.
        #
        # Ta strata jest teraz WIDOCZNA. Do 2026-08-10 pominięta strona nie
        # zostawiała żadnego śladu: brak `add_error` → brak `error_refs` → brak
        # kwarantanny → orkiestrator stemplował `ok` i PRZESUWAŁ watermark, a
        # ~10 źródeł znikało bez jednej liczby gdziekolwiek. Liczymy je do
        # `skipped_pages`, widocznego w `/sync/status`.
        #
        # Świadomie NIE jest to `add_error`: komunikat nie ma `ext=`/`id=`, więc
        # byłby nieatrybutowalny, a `_blocking_errors` liczy takie jako blokujące
        # i kwarantanna nie ma czego zaparkować — znany, powtarzalny bug
        # endpointu przypiąłby `checks.traffit=degraded` na stałe. Widoczność
        # tak, zamrożenie nie.
        sources_page_size = min(self.batch_size, 10)

        def _note_skipped_page(page: int, status: int) -> None:
            progress.skipped_pages += 1
            logger.warning(
                "Sources: page %d dropped (HTTP %d) — ~%d records lost this run",
                page,
                status,
                sources_page_size,
            )

        async for raw in self.traffit.get_paginated(
            "/sources/",
            page_size=sources_page_size,
            skip_on_5xx=True,
            filter_=self._delta_filter("created_at", since),
            on_page_skipped=_note_skipped_page,
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
            added = 0
            try:
                # SAVEPOINT per kandydata, jak w `import_workflows` /
                # `import_candidates`. Goły `db.rollback()` w handlerze podnosi
                # SESJĘ, a ta faza commituje RAZ na końcu — jeden zły wiersz
                # kasował atrybucję źródeł wszystkim policzonym wcześniej,
                # a `progress.inserted` dalej ich liczyło.
                async with self.db.begin_nested():
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
            except Exception as e:  # noqa: BLE001
                progress.add_error(f"merge tags candidate={candidate_id}: {e!r}")
                # Savepoint już cofnął zapis; sesję podnosimy tylko przy utracie
                # połączenia (`ROLLBACK TO SAVEPOINT` nie ma wtedy dokąd pójść).
                if needs_session_rollback(e, past_savepoint=False):
                    await self.db.rollback()
                continue
            # Liczone po utrzymaniu się savepointu, nie w jego środku.
            if added > 0:
                progress.inserted += added
            else:
                progress.skipped += 1

        await self.db.commit()
        progress.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Sources import done: %s",
            json.dumps(progress.as_dict(), default=str)[:500],
        )
        return progress
