"""
CSV Import / Export for Candidates.
POST /api/import/candidates  — upload CSV, create candidates (dedup by email)
GET  /api/export/candidates  — download all candidates as CSV (UTF-8 BOM)
"""

import csv
import io
import codecs
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.candidate import Candidate, CandidateStatus
from app.models.activity import Activity

# Re-audyt M2 (PR1b): to jest DRUGA, rownolegla powierzchnia eksportu/importu
# kandydatow obok /api/candidates/export. PR1 zamknal tamta (TAC+ i audyt),
# a ta zostala na golym CurrentUser: GET /api/export/candidates robi
# select(Candidate) BEZ limitu i strumieniuje imie/nazwisko/email/telefon/
# lokalizacje/stawke calej bazy do dowolnej zalogowanej roli (w tym `user`,
# ktora PR1 mial odcieta), bez zdarzenia audytowego. Import pozwalal tej
# samej roli masowo tworzyc kandydatow.
from app.api.candidate_access import CandidateExportAccess, CandidateWriteAccess
from app.services import candidate_audit
from app.services import candidate_profile_facts
from app.services.candidate_language_writer import (
    normalize_language_payload,
    sync_candidate_languages_from_source,
)
from app.services.candidate_profile_rate import canonical_profile_rate_amount
from app.services.candidate_location_writer import normalize_candidate_location

logger = logging.getLogger(__name__)
router = APIRouter()

# Expected CSV columns (case-insensitive, order flexible)
EXPECTED_COLUMNS = {
    "name",
    "lastname",
    "email",
    "phone",
    "city",
    "country",
    "location",
    "source",
    "skills",
    "languages",
    "expected_rate_hourly",
}


def _parse_skills(raw: str) -> list:
    """Convert 'Python, React, AWS' → [{'name': 'Python'}, ...]"""
    if not raw or not raw.strip():
        return []
    return [{"name": s.strip()} for s in raw.split(",") if s.strip()]


def _parse_profile_rate(raw: str) -> Decimal:
    try:
        amount = Decimal(raw.strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid_profile_rate") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("invalid_profile_rate")
    if amount >= Decimal("100000000"):
        raise ValueError("invalid_profile_rate")
    return amount


@router.post("/import/candidates")
async def import_candidates(
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """
    Accept CSV file (UTF-8 or UTF-8-BOM) and create Candidate records.
    Deduplicates by email — rows with existing emails are skipped.
    Returns: {imported, skipped, errors, details}
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Plik musi być w formacie CSV")

    raw_bytes = await file.read()

    # Detect and strip BOM if present
    if raw_bytes.startswith(codecs.BOM_UTF8):
        raw_bytes = raw_bytes[len(codecs.BOM_UTF8) :]

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw_bytes.decode("cp1250")  # Windows Polish fallback
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Nie można odczytać pliku — użyj kodowania UTF-8",
            )

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise HTTPException(
            status_code=400, detail="Plik CSV jest pusty lub nie ma nagłówków"
        )

    # Normalize header names (strip whitespace, lowercase)
    normalized_fields = {f.strip().lower(): f for f in reader.fieldnames}

    def get_col(row: dict, col: str) -> str:
        original = normalized_fields.get(col)
        if original and original in row:
            value = row[original]
            return "" if value is None else str(value).strip()
        return ""

    imported = 0
    skipped = 0
    errors = 0
    details = []
    imported_ids: list[int] = []
    field_errors = 0

    for row_num, row in enumerate(reader, start=2):  # start=2 (header is row 1)
        try:
            email = get_col(row, "email").lower() or None
            name = get_col(row, "name")
            lastname = get_col(row, "lastname")

            if not name and not lastname:
                errors += 1
                details.append(
                    {
                        "row": row_num,
                        "status": "error",
                        "reason": "Brak imienia i nazwiska",
                    }
                )
                continue

            # Dedup by email
            if email:
                existing = await db.execute(
                    select(Candidate).where(Candidate.email == email)
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    details.append(
                        {
                            "row": row_num,
                            "status": "skipped",
                            "email": email,
                            "reason": "Email już istnieje w bazie",
                        }
                    )
                    continue

            skills_raw = get_col(row, "skills")
            rate_raw = get_col(row, "expected_rate_hourly")
            rate_currency = get_col(row, "expected_rate_currency").upper()
            source_raw = get_col(row, "source") or "manual"
            raw_country = get_col(row, "country")
            location = normalize_candidate_location(
                city=get_col(row, "city") or None,
                country=raw_country or None,
                raw_location=get_col(row, "location") or None,
            )
            row_field_errors: list[dict[str, str]] = []
            if raw_country and location.country is None:
                row_field_errors.append(
                    {
                        "field": "country",
                        "code": "invalid_candidate_country",
                    }
                )
            languages_raw = get_col(row, "languages")
            if languages_raw:
                _normalized_languages, invalid_languages = normalize_language_payload(
                    languages_raw
                )
                if invalid_languages:
                    row_field_errors.append(
                        {
                            "field": "languages",
                            "code": "invalid_candidate_languages",
                        }
                    )

            # A retired column is an error by schema presence, even when every
            # cell is empty.  This prevents an obsolete template from looking
            # successfully migrated while silently dropping the field.
            for retired_field in ("salary_expectation", "salary_currency"):
                if retired_field in normalized_fields:
                    row_field_errors.append(
                        {
                            "field": retired_field,
                            "code": "candidate_monthly_rate_retired",
                        }
                    )

            parsed_rate: Decimal | None = None
            if rate_raw:
                if rate_currency and rate_currency != "PLN":
                    row_field_errors.append(
                        {
                            "field": "expected_rate_currency",
                            "code": "candidate_profile_rate_requires_pln",
                        }
                    )
                else:
                    try:
                        amount = _parse_profile_rate(rate_raw)
                    except ValueError:
                        row_field_errors.append(
                            {
                                "field": "expected_rate_hourly",
                                "code": "invalid_profile_rate",
                            }
                        )
                    else:
                        parsed_rate = amount
            elif rate_currency:
                row_field_errors.append(
                    {
                        "field": "expected_rate_currency",
                        "code": "candidate_profile_rate_amount_required",
                    }
                )

            # A savepoint protects the outer bulk transaction if any persistence
            # hook fails after validation; no half-created candidate survives.
            async with db.begin_nested():
                candidate = Candidate(
                    name=name or "—",
                    lastname=lastname or "",
                    email=email,
                    phone=get_col(row, "phone") or None,
                    city=location.city,
                    country=location.country,
                    location=location.projection,
                    source=source_raw[:100],
                    skills=_parse_skills(skills_raw),
                    status=CandidateStatus.active,
                )
                db.add(candidate)
                await db.flush()

                if languages_raw:
                    await sync_candidate_languages_from_source(
                        db,
                        candidate_id=candidate.id,
                        raw_languages=languages_raw,
                        provenance="csv",
                        source_ref=f"csv-row:{row_num}",
                    )

                if parsed_rate is not None:
                    await candidate_profile_facts.update_candidate_profile_rate(
                        db,
                        candidate_id=candidate.id,
                        amount=parsed_rate,
                        expected_version=candidate.profile_rate_version,
                        actor_id=current_user.id,
                    )

                activity = Activity(
                    entity_type="candidate",
                    entity_id=candidate.id,
                    action="imported",
                    user_id=current_user.id,
                    details={
                        "name": f"{candidate.name} {candidate.lastname}",
                        "source": "csv_import",
                    },
                )
                db.add(activity)
                await db.flush()

            imported_ids.append(candidate.id)

            imported += 1
            detail = {
                "row": row_num,
                "status": "imported",
                "name": f"{name} {lastname}".strip(),
                "email": email,
            }
            if row_field_errors:
                field_errors += len(row_field_errors)
                detail["status"] = "imported_with_field_errors"
                detail["field_errors"] = row_field_errors
            details.append(detail)

        except Exception as exc:
            errors += 1
            details.append(
                {
                    "row": row_num,
                    "status": "error",
                    "reason": str(exc),
                }
            )

    # Record the reindex intent for everything this import created. Bulk path,
    # so intent only — embedding inline here would be one Voyage call per row
    # inside the import loop, turning a 5 000-row CSV into 5 000 sequential API
    # calls where a single timeout costs a candidate. Cheap INSERTs in the same
    # transaction: if the import rolls back, the intents go with it.
    try:
        from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex

        await record_bulk_reindex(db, CANDIDATE, imported_ids)
    except Exception as exc:  # noqa: BLE001 — never fail an import on the queue
        logger.warning("Recording reindex intent for CSV import failed: %s", exc)

    await db.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "field_errors": field_errors,
        "details": details,
    }


def _build_candidates_csv(candidates) -> bytes:
    """Serialize candidates to CSV bytes (UTF-8 BOM for Excel/Polish chars).

    Sync/CPU-bound over the full candidate list — call via run_in_threadpool so
    the serialization of tens of thousands of rows does not block the loop.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(
        [
            "id",
            "name",
            "lastname",
            "email",
            "phone",
            "location",
            "source",
            "status",
            "skills",
            "expected_rate_hourly",
            "created_at",
            "open_to_side_projects",
            "open_to_sales_support",
            "open_to_expert_consult",
        ]
    )

    for c in candidates:
        # Flatten skills list → "Python, React, AWS"
        skills_list = c.skills or []
        if isinstance(skills_list, list):
            skills_str = ", ".join(
                s.get("name", s) if isinstance(s, dict) else str(s) for s in skills_list
            )
        else:
            skills_str = ""

        created = c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else ""
        profile_rate = canonical_profile_rate_amount(
            c.expected_rate_hourly,
            c.expected_rate_currency,
        )

        writer.writerow(
            [
                c.id,
                c.name or "",
                c.lastname or "",
                c.email or "",
                c.phone or "",
                c.location or "",
                c.source or "",
                c.status.value if c.status else "",
                skills_str,
                profile_rate if profile_rate is not None else "",
                created,
                "tak" if c.open_to_side_projects else "",
                "tak" if c.open_to_sales_support else "",
                "tak" if c.open_to_expert_consult else "",
            ]
        )

    # Encode with UTF-8 BOM for Polish characters in Excel
    return codecs.BOM_UTF8 + output.getvalue().encode("utf-8")


@router.get("/export/candidates")
async def export_candidates(
    current_user: CandidateExportAccess,
    db: AsyncSession = Depends(get_db),
):
    """
    Export all candidates as CSV with UTF-8 BOM (Polish characters support).
    """
    result = await db.execute(select(Candidate).order_by(Candidate.created_at.desc()))
    candidates = result.scalars().all()

    csv_bytes = await run_in_threadpool(_build_candidates_csv, candidates)

    # Ten sam nieusuwalny slad audytowy co /api/candidates/export (PR1) —
    # bez PII, same liczniki.
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.EXPORT_REQUESTED,
        user_id=current_user.id,
        details={
            "endpoint": "GET /api/export/candidates",
            "format": "csv",
            "row_count": len(candidates),
        },
    )
    await db.commit()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"kandydaci_{timestamp}.csv"

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8-sig",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(csv_bytes)),
        },
    )
