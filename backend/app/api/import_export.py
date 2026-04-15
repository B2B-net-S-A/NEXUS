"""
CSV Import / Export for Candidates.
POST /api/import/candidates  — upload CSV, create candidates (dedup by email)
GET  /api/export/candidates  — download all candidates as CSV (UTF-8 BOM)
"""

import csv
import io
import codecs
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.candidate import Candidate, CandidateStatus
from app.models.activity import Activity
from app.api.deps import CurrentUser

router = APIRouter()

# Expected CSV columns (case-insensitive, order flexible)
EXPECTED_COLUMNS = {
    "name", "lastname", "email", "phone",
    "location", "source", "skills", "salary_expectation",
}


def _parse_skills(raw: str) -> list:
    """Convert 'Python, React, AWS' → [{'name': 'Python'}, ...]"""
    if not raw or not raw.strip():
        return []
    return [{"name": s.strip()} for s in raw.split(",") if s.strip()]


def _safe_int(val: str) -> Optional[int]:
    try:
        return int(str(val).strip().replace(" ", "").replace(",", ""))
    except (ValueError, TypeError):
        return None


@router.post("/import/candidates")
async def import_candidates(
    current_user: CurrentUser,
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
        raw_bytes = raw_bytes[len(codecs.BOM_UTF8):]

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw_bytes.decode("cp1250")  # Windows Polish fallback
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Nie można odczytać pliku — użyj kodowania UTF-8")

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="Plik CSV jest pusty lub nie ma nagłówków")

    # Normalize header names (strip whitespace, lowercase)
    normalized_fields = {f.strip().lower(): f for f in reader.fieldnames}

    def get_col(row: dict, col: str) -> str:
        original = normalized_fields.get(col)
        if original and original in row:
            return str(row[original]).strip()
        return ""

    imported = 0
    skipped = 0
    errors = 0
    details = []

    for row_num, row in enumerate(reader, start=2):  # start=2 (header is row 1)
        try:
            email = get_col(row, "email").lower() or None
            name = get_col(row, "name")
            lastname = get_col(row, "lastname")

            if not name and not lastname:
                errors += 1
                details.append({
                    "row": row_num,
                    "status": "error",
                    "reason": "Brak imienia i nazwiska",
                })
                continue

            # Dedup by email
            if email:
                existing = await db.execute(
                    select(Candidate).where(Candidate.email == email)
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    details.append({
                        "row": row_num,
                        "status": "skipped",
                        "email": email,
                        "reason": "Email już istnieje w bazie",
                    })
                    continue

            skills_raw = get_col(row, "skills")
            salary_raw = get_col(row, "salary_expectation")
            source_raw = get_col(row, "source") or "manual"

            candidate = Candidate(
                name=name or "—",
                lastname=lastname or "",
                email=email,
                phone=get_col(row, "phone") or None,
                location=get_col(row, "location") or None,
                source=source_raw[:100],
                skills=_parse_skills(skills_raw),
                salary_expectation=_safe_int(salary_raw),
                status=CandidateStatus.active,
            )
            db.add(candidate)
            await db.flush()

            activity = Activity(
                entity_type="candidate",
                entity_id=candidate.id,
                action="imported",
                user_id=current_user.id,
                details={"name": f"{candidate.name} {candidate.lastname}", "source": "csv_import"},
            )
            db.add(activity)

            imported += 1
            details.append({
                "row": row_num,
                "status": "imported",
                "name": f"{name} {lastname}".strip(),
                "email": email,
            })

        except Exception as exc:
            errors += 1
            details.append({
                "row": row_num,
                "status": "error",
                "reason": str(exc),
            })

    await db.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }


@router.get("/export/candidates")
async def export_candidates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Export all candidates as CSV with UTF-8 BOM (Polish characters support).
    """
    result = await db.execute(
        select(Candidate).order_by(Candidate.created_at.desc())
    )
    candidates = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "id", "name", "lastname", "email", "phone",
        "location", "source", "status", "skills",
        "salary_expectation", "created_at",
    ])

    for c in candidates:
        # Flatten skills list → "Python, React, AWS"
        skills_list = c.skills or []
        if isinstance(skills_list, list):
            skills_str = ", ".join(
                s.get("name", s) if isinstance(s, dict) else str(s)
                for s in skills_list
            )
        else:
            skills_str = ""

        created = c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else ""

        writer.writerow([
            c.id,
            c.name or "",
            c.lastname or "",
            c.email or "",
            c.phone or "",
            c.location or "",
            c.source or "",
            c.status.value if c.status else "",
            skills_str,
            c.salary_expectation or "",
            created,
        ])

    # Encode with UTF-8 BOM for Polish characters in Excel
    csv_bytes = codecs.BOM_UTF8 + output.getvalue().encode("utf-8")

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
