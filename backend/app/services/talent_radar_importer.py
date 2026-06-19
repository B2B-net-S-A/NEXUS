"""
Phase 7a — Talent Radar → Nexus CV importer.

Pulls candidates from the Supabase `talentradar-prod` project (40 745 rows)
and inserts them into the Nexus `candidates` table.

Cross-source dedup (added 2026-06): before inserting we check whether the
person already exists in Nexus — by `external_id` (TalentRadar carries the
Traffit id, so a TalentRadar row maps onto its `traffit` twin), by unique
`email`, or by a corroborated dedup hit — and if so we **merge the CV into the
existing row** instead of creating a parallel `talent_radar` record. This is
what prevents the double-import that previously produced ~1 884 duplicates
(`('traffit', id)` and `('talent_radar', id)` coexisting). Only genuinely-new
people get inserted as `external_source='talent_radar'`. Re-runs stay
idempotent (the per-source ON CONFLICT still covers same-source re-imports).

Mapping (source → Nexus):
  traffit_id              → external_id (string), external_source='talent_radar'
  email                   → email
  name, lastname          → name, lastname
  raw_cv_text             → raw_cv_text
  cv_content (bytea)      → cv_file_content
  extracted_data (jsonb)  → cv_extracted_data
  skills (jsonb)          → skills
  experience_years (int)  → years_it_experience
  seniority (varchar)     → competence_category  (normalized to junior/mid/senior/lead/architect)
  languages (jsonb)       → languages
  location                → location
  finance_expectations    → salary_expectation (parsed: regex \\d{4,6})
  availability            → availability_date  (parsed: ISO date or None)
  cv_language             → cv_language
  cv_date (date)          → cv_parsed_at       (date → datetime midnight UTC)

Safety:
- batch_size=500 by default (bounded memory)
- dry-run flag (read-only mode)
- all errors captured per-row, batch continues
- progress reported back to caller via async generator
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any, AsyncIterator, Optional

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.dedup_service import find_candidate_duplicates

logger = logging.getLogger(__name__)

# Reasons from dedup_service that are *hard* corroborators (a shared identity
# signal beyond a bare namesake). Name-only matches are deliberately NOT trusted
# for auto-merge in the importer — two different people can share a name.
_HARD_DEDUP_REASONS = {"email_exact", "phone_exact", "linkedin_slug_match"}

# Adopt/merge a TalentRadar row into an already-existing candidate (matched by
# external_id, email, or a corroborated dedup hit). Purely additive: every field
# is COALESCE/CASE-guarded so we only fill gaps and NEVER overwrite the existing
# (canonical) row's data, and we do NOT touch its external_source/name/lastname.
_MERGE_CV_INTO_EXISTING = text(
    """
    UPDATE candidates SET
        email             = COALESCE(candidates.email, :email),
        phone             = COALESCE(candidates.phone, :phone),
        raw_cv_text       = COALESCE(NULLIF(btrim(candidates.raw_cv_text), ''),
                                     :raw_cv_text),
        cv_file_content   = COALESCE(candidates.cv_file_content, :cv_file_content),
        cv_storage_key    = COALESCE(candidates.cv_storage_key, :cv_storage_key),
        cv_filename       = COALESCE(NULLIF(btrim(candidates.cv_filename), ''),
                                     :cv_filename),
        cv_extracted_data = CASE
            WHEN candidates.cv_extracted_data IS NULL
              OR candidates.cv_extracted_data::text IN ('{}', 'null')
            THEN CAST(:cv_extracted_data AS JSONB)
            ELSE candidates.cv_extracted_data END,
        skills = CASE
            WHEN candidates.skills IS NULL
              OR candidates.skills::text IN ('[]', '{}', 'null')
            THEN CAST(:skills AS JSONB)
            ELSE candidates.skills END,
        years_it_experience = COALESCE(candidates.years_it_experience,
                                       :years_it_experience),
        competence_category = COALESCE(candidates.competence_category,
                                       :competence_category),
        languages = CASE
            WHEN candidates.languages IS NULL
              OR candidates.languages::text IN ('[]', '{}', 'null')
            THEN CAST(:languages AS JSONB)
            ELSE candidates.languages END,
        location          = COALESCE(NULLIF(btrim(candidates.location), ''),
                                     :location),
        salary_expectation = COALESCE(candidates.salary_expectation,
                                      :salary_expectation),
        availability_date  = COALESCE(candidates.availability_date,
                                      :availability_date),
        cv_language        = COALESCE(candidates.cv_language, :cv_language),
        cv_parsed_at       = COALESCE(candidates.cv_parsed_at, :cv_parsed_at),
        updated_at         = NOW()
    WHERE id = :nexus_id
    """
)

# ── Normalizers ──────────────────────────────────────────────────────────────

_SENIORITY_MAP = {
    "junior": "junior",
    "jr": "junior",
    "mid": "mid",
    "middle": "mid",
    "regular": "mid",
    "senior": "senior",
    "sr": "senior",
    "lead": "lead",
    "tech lead": "lead",
    "team lead": "lead",
    "architect": "architect",
    "staff": "architect",
    "principal": "architect",
}


def normalize_seniority(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().lower()
    return _SENIORITY_MAP.get(key, key)  # keep as-is if unknown


_SALARY_RE = re.compile(r"(\d{4,6})")


def parse_salary(raw: Optional[str]) -> Optional[int]:
    """Extract the first 4-6 digit number from a free-text expectation."""
    if not raw:
        return None
    m = _SALARY_RE.search(raw.replace(" ", "").replace(",", ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


_AVAILABILITY_KEYWORDS = {
    "natychmiast": 0,
    "od zaraz": 0,
    "immediately": 0,
    "asap": 0,
    "teraz": 0,
    "zaraz": 0,
}


def parse_availability(raw: Optional[str]) -> Optional[date]:
    """Try to parse availability as ISO date or a known keyword."""
    if not raw:
        return None
    s = raw.strip().lower()
    if s in _AVAILABILITY_KEYWORDS:
        return date.today()
    # Try ISO date formats
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def to_datetime_utc(d: Optional[date]) -> Optional[datetime]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


# ── Result dataclasses ──────────────────────────────────────────────────────


@dataclass
class ImportProgress:
    processed: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    total: int = 0
    error_samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "processed": self.processed,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "total": self.total,
            "error_samples": self.error_samples[:20],
        }


# ── Importer ────────────────────────────────────────────────────────────────


class TalentRadarImporter:
    """Pulls candidates from Supabase talent-radar and upserts into Nexus."""

    def __init__(
        self,
        source_dsn: str,
        target_db: AsyncSession,
        batch_size: int = 500,
        dry_run: bool = False,
    ) -> None:
        self.source_dsn = source_dsn
        self.target_db = target_db
        self.batch_size = batch_size
        self.dry_run = dry_run
        # Pre-loaded dedup maps (populated in run()): they let us merge a
        # TalentRadar row into an already-existing candidate instead of creating
        # a parallel row. ``external_id`` is the deterministic key (TalentRadar
        # carries the Traffit id), ``email`` is the unique-index key.
        self._ext_id_to_id: dict[str, int] = {}
        self._email_to_id: dict[str, int] = {}
        self.adopted = 0

    async def _count_source(self, source_conn: asyncpg.Connection) -> int:
        row = await source_conn.fetchrow(
            "SELECT count(*)::int AS c FROM public.candidates"
        )
        return int(row["c"] if row else 0)

    async def _fetch_batch(
        self, source_conn: asyncpg.Connection, offset: int
    ) -> list[asyncpg.Record]:
        return await source_conn.fetch(
            """
            SELECT id, traffit_id, email, name, lastname, raw_cv_text,
                   cv_content, cv_filename, extracted_data, skills,
                   experience_years, seniority, languages, location,
                   finance_expectations, availability, cv_language, cv_date
            FROM public.candidates
            ORDER BY id
            LIMIT $1 OFFSET $2
            """,
            self.batch_size,
            offset,
        )

    def _to_payload(self, row: asyncpg.Record) -> dict[str, Any]:
        """Map a source row to our INSERT parameters.

        cv_content (BYTEA z source DB) jest uploadowane do Hetzner Object
        Storage (audit-2026-05-07 Faza 3) i `cv_storage_key` zapisany w nexus
        candidates. Source `cv_file_content` zostaje NULL (legacy column).
        """
        cv_storage_key: str | None = None
        cv_content = row["cv_content"]
        if cv_content:
            from app.services.object_storage import (
                is_available as _storage_available,
                upload_cv as _upload_cv,
            )

            if _storage_available():
                try:
                    cv_storage_key = _upload_cv(
                        content=bytes(cv_content),
                        filename=row["cv_filename"] or "cv",
                        content_type=None,
                    )
                except Exception:
                    # Best-effort: na crash storage, zachowuj BYTEA fallback,
                    # żeby import nie blokował się na S3 outage.
                    cv_storage_key = None

        return {
            "external_id": str(row["traffit_id"]),
            "external_source": "talent_radar",
            "email": (row["email"] or "").strip() or None,
            "name": (row["name"] or "").strip() or "?",
            "lastname": (row["lastname"] or "").strip() or "?",
            "raw_cv_text": row["raw_cv_text"],
            # cv_file_content zostaje BYTEA tylko gdy upload do S3 nie zadziałał.
            "cv_file_content": cv_content if cv_storage_key is None else None,
            "cv_storage_key": cv_storage_key,
            "cv_filename": row["cv_filename"],
            "cv_extracted_data": row["extracted_data"] or {},
            "skills": row["skills"] or [],
            "years_it_experience": row["experience_years"],
            "competence_category": normalize_seniority(row["seniority"]),
            "languages": row["languages"] or [],
            "location": row["location"],
            "salary_expectation": parse_salary(row["finance_expectations"]),
            "availability_date": parse_availability(row["availability"]),
            "cv_language": row["cv_language"],
            "cv_parsed_at": to_datetime_utc(row["cv_date"]),
            "source": "talent_radar",
            "status": "active",
        }

    async def _preload_dedup_maps(self) -> None:
        """Pre-load existing-candidate lookup maps so we never create a parallel
        row for someone already in Nexus.

        ``_ext_id_to_id`` maps ``external_id`` → candidate id, **preferring a
        ``traffit`` row** when the same external_id exists under several sources
        (the canonical recruiting row). ``_email_to_id`` maps lower(email) → id
        (the global UNIQUE(email) key).
        """
        ext_rows = (
            await self.target_db.execute(
                text(
                    "SELECT external_id, id, external_source FROM candidates "
                    "WHERE external_id IS NOT NULL AND btrim(external_id) <> '' "
                    # traffit last so it wins the dict overwrite below
                    "ORDER BY (external_source = 'traffit') ASC"
                )
            )
        ).all()
        self._ext_id_to_id = {r[0]: r[1] for r in ext_rows}

        email_rows = (
            await self.target_db.execute(
                text(
                    "SELECT lower(btrim(email)), id FROM candidates "
                    "WHERE email IS NOT NULL AND btrim(email) <> ''"
                )
            )
        ).all()
        self._email_to_id = {r[0]: r[1] for r in email_rows if r[0]}
        logger.info(
            "TalentRadar dedup maps: external_id=%d, email=%d",
            len(self._ext_id_to_id),
            len(self._email_to_id),
        )

    async def _find_existing_id(self, p: dict[str, Any]) -> Optional[int]:
        """Resolve an already-existing candidate for this payload, or None.

        Order: external_id (deterministic) → email (unique) → corroborated
        dedup hit (name + a hard signal). Bare-namesake matches are rejected —
        two different people can share a name.
        """
        ext = p.get("external_id")
        if ext and ext in self._ext_id_to_id:
            return self._ext_id_to_id[ext]

        email_lc = (p.get("email") or "").strip().lower()
        if email_lc and email_lc in self._email_to_id:
            return self._email_to_id[email_lc]

        # Fallback only for genuinely-new external_ids: require a HARD corroborator
        # (phone/linkedin/email), never a bare namesake.
        name = p.get("name")
        if name and name != "?":
            dupes = await find_candidate_duplicates(
                self.target_db,
                email=p.get("email"),
                name=name,
                lastname=p.get("lastname"),
                min_score=0.90,
            )
            for d in dupes:
                if _HARD_DEDUP_REASONS.intersection(d.get("match_reasons", [])):
                    return d["candidate_id"]
        return None

    @staticmethod
    def _merge_params(p: dict[str, Any], nexus_id: int) -> dict[str, Any]:
        import json

        return {
            "nexus_id": nexus_id,
            "email": p.get("email"),
            "phone": p.get("phone"),
            "raw_cv_text": p.get("raw_cv_text"),
            "cv_file_content": p.get("cv_file_content"),
            "cv_storage_key": p.get("cv_storage_key"),
            "cv_filename": p.get("cv_filename"),
            "cv_extracted_data": json.dumps(p.get("cv_extracted_data") or {}),
            "skills": json.dumps(p.get("skills") or []),
            "years_it_experience": p.get("years_it_experience"),
            "competence_category": p.get("competence_category"),
            "languages": json.dumps(p.get("languages") or []),
            "location": p.get("location"),
            "salary_expectation": p.get("salary_expectation"),
            "availability_date": p.get("availability_date"),
            "cv_language": p.get("cv_language"),
            "cv_parsed_at": p.get("cv_parsed_at"),
        }

    # INSERT path for genuinely-new candidates. Keeps the per-source ON CONFLICT
    # upsert (idempotent re-runs of the *same* source); cross-source dedup is
    # handled before we get here, in _find_existing_id.
    _INSERT_SQL = text(
        """
        INSERT INTO candidates (
            external_id, external_source, email, name, lastname,
            raw_cv_text, cv_file_content, cv_storage_key, cv_filename, cv_extracted_data,
            skills, years_it_experience, competence_category, languages,
            location, salary_expectation, availability_date,
            cv_language, cv_parsed_at, source, status,
            notes_count, champion,
            created_at, updated_at
        ) VALUES (
            :external_id, :external_source, :email, :name, :lastname,
            :raw_cv_text, :cv_file_content, :cv_storage_key, :cv_filename, CAST(:cv_extracted_data AS JSONB),
            CAST(:skills AS JSONB), :years_it_experience, :competence_category,
            CAST(:languages AS JSONB), :location, :salary_expectation,
            :availability_date, :cv_language, :cv_parsed_at, :source, :status,
            0, false,
            NOW(), NOW()
        )
        ON CONFLICT (external_source, external_id)
        WHERE external_id IS NOT NULL
        DO UPDATE SET
            email             = COALESCE(EXCLUDED.email, candidates.email),
            name              = EXCLUDED.name,
            lastname          = EXCLUDED.lastname,
            raw_cv_text       = EXCLUDED.raw_cv_text,
            cv_file_content   = COALESCE(EXCLUDED.cv_file_content, candidates.cv_file_content),
            cv_storage_key    = COALESCE(EXCLUDED.cv_storage_key, candidates.cv_storage_key),
            cv_filename       = EXCLUDED.cv_filename,
            cv_extracted_data = EXCLUDED.cv_extracted_data,
            skills            = EXCLUDED.skills,
            years_it_experience = EXCLUDED.years_it_experience,
            competence_category = EXCLUDED.competence_category,
            languages         = EXCLUDED.languages,
            location          = EXCLUDED.location,
            salary_expectation = EXCLUDED.salary_expectation,
            availability_date  = EXCLUDED.availability_date,
            cv_language        = EXCLUDED.cv_language,
            cv_parsed_at       = EXCLUDED.cv_parsed_at,
            updated_at         = NOW()
        RETURNING id, (xmax = 0) AS was_insert
        """
    )

    async def _upsert(self, payloads: list[dict[str, Any]]) -> tuple[int, int]:
        """Return (inserted, updated).

        For each payload: if the person already exists in Nexus (external_id /
        email / corroborated dedup) → merge CV into that row (no parallel row);
        otherwise INSERT. Newly-created rows are registered in the in-memory maps
        so later payloads in the same run dedupe against them too.
        """
        if not payloads or self.dry_run:
            return (0, 0)

        import json

        inserted = 0
        updated = 0

        for p in payloads:
            existing_id = await self._find_existing_id(p)

            if existing_id is not None:
                await self.target_db.execute(
                    _MERGE_CV_INTO_EXISTING, self._merge_params(p, existing_id)
                )
                updated += 1
                self.adopted += 1
                # Cache so other rows in this run targeting the same person merge too.
                if p.get("external_id"):
                    self._ext_id_to_id.setdefault(p["external_id"], existing_id)
                continue

            params = dict(p)
            params["skills"] = json.dumps(p["skills"])
            params["languages"] = json.dumps(p["languages"])
            params["cv_extracted_data"] = json.dumps(p["cv_extracted_data"])
            result = await self.target_db.execute(self._INSERT_SQL, params)
            row = result.fetchone()
            if row is None:
                continue
            new_id, was_insert = row[0], row[1]
            if was_insert:
                inserted += 1
            else:
                updated += 1
            # Register the new/updated row so subsequent payloads see it.
            if p.get("external_id"):
                self._ext_id_to_id.setdefault(p["external_id"], new_id)
            email_lc = (p.get("email") or "").strip().lower()
            if email_lc:
                self._email_to_id.setdefault(email_lc, new_id)

        await self.target_db.commit()
        return (inserted, updated)

    async def run(self) -> AsyncIterator[ImportProgress]:
        """Stream progress updates as we process batches. Caller awaits each yield."""
        progress = ImportProgress()
        conn: Optional[asyncpg.Connection] = None
        try:
            conn = await asyncpg.connect(self.source_dsn, statement_cache_size=0)
            progress.total = await self._count_source(conn)
            # Load existing-candidate maps once so cross-source dedup is O(1)/row.
            if not self.dry_run:
                await self._preload_dedup_maps()
            yield progress

            offset = 0
            while offset < progress.total:
                batch = await self._fetch_batch(conn, offset)
                if not batch:
                    break

                payloads: list[dict[str, Any]] = []
                for row in batch:
                    try:
                        # _to_payload does a sync boto3 CV upload — offload the
                        # whole mapping so the S3 put does not block the loop.
                        payloads.append(await asyncio.to_thread(self._to_payload, row))
                    except Exception as e:  # noqa: BLE001
                        progress.errors += 1
                        if len(progress.error_samples) < 20:
                            progress.error_samples.append(
                                f"row id={row['id']} traffit_id={row['traffit_id']}: {e!r}"
                            )

                try:
                    inserted, updated = await self._upsert(payloads)
                    progress.inserted += inserted
                    progress.updated += updated
                except Exception as e:  # noqa: BLE001
                    progress.errors += len(payloads)
                    if len(progress.error_samples) < 20:
                        progress.error_samples.append(f"batch offset={offset}: {e!r}")
                    # continue with next batch — don't abort on one bad batch
                    await self.target_db.rollback()

                progress.processed += len(batch)
                offset += len(batch)
                yield progress
                # Yield control periodically so async scheduler can breathe
                await asyncio.sleep(0)
        finally:
            if conn is not None:
                await conn.close()
