"""
Phase 7a — Talent Radar → Nexus CV importer.

Pulls candidates from the Supabase `talentradar-prod` project (40 745 rows)
and inserts them into the Nexus `candidates` table. Idempotent: re-runs
UPSERT by (external_source='talent_radar', external_id=str(traffit_id)).

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

logger = logging.getLogger(__name__)

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

    async def _upsert(self, payloads: list[dict[str, Any]]) -> tuple[int, int]:
        """Return (inserted, updated). Uses ON CONFLICT on (external_source, external_id)."""
        if not payloads or self.dry_run:
            return (0, 0)

        # INSERT ... ON CONFLICT DO UPDATE.  We can't tell row-level whether
        # each hit was INSERT or UPDATE without RETURNING xmax=0, so use that.
        sql = text(
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
            RETURNING (xmax = 0) AS was_insert
            """
        )

        inserted = 0
        updated = 0
        import json

        for p in payloads:
            # SQLAlchemy won't auto-serialize dicts into JSONB via :params — do it here
            params = dict(p)
            params["skills"] = json.dumps(p["skills"])
            params["languages"] = json.dumps(p["languages"])
            params["cv_extracted_data"] = json.dumps(p["cv_extracted_data"])
            result = await self.target_db.execute(sql, params)
            row = result.fetchone()
            if row is None:
                continue
            if row[0]:
                inserted += 1
            else:
                updated += 1

        await self.target_db.commit()
        return (inserted, updated)

    async def run(self) -> AsyncIterator[ImportProgress]:
        """Stream progress updates as we process batches. Caller awaits each yield."""
        progress = ImportProgress()
        conn: Optional[asyncpg.Connection] = None
        try:
            conn = await asyncpg.connect(self.source_dsn, statement_cache_size=0)
            progress.total = await self._count_source(conn)
            yield progress

            offset = 0
            while offset < progress.total:
                batch = await self._fetch_batch(conn, offset)
                if not batch:
                    break

                payloads: list[dict[str, Any]] = []
                for row in batch:
                    try:
                        payloads.append(self._to_payload(row))
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
