"""Rate benchmarks API — CRUD over market rate references (Hays, NoFluffJobs…).

Used by:
- Contracts detail → `GET /api/contracts/{id}/benchmark` compares the contract
  rate against the most recent matching row here.
- Settings admin page → full CRUD + CSV import.
"""

import csv
import io
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.contract import RateUnit
from app.models.rate_benchmark import RateBenchmark, SeniorityLevel
from app.schemas.rate_benchmark import (
    RateBenchmarkCreate,
    RateBenchmarkImportResult,
    RateBenchmarkResponse,
    RateBenchmarkUpdate,
)

router = APIRouter()


@router.get("", response_model=List[RateBenchmarkResponse])
async def list_benchmarks(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    role: Optional[str] = Query(None, description="Case-insensitive prefix match"),
    seniority: Optional[SeniorityLevel] = Query(None),
    location: Optional[str] = Query(None),
    currency: Optional[str] = Query(None, min_length=3, max_length=3),
    limit: int = Query(200, ge=1, le=1000),
):
    query = select(RateBenchmark)
    if role:
        query = query.where(RateBenchmark.role.ilike(f"{role}%"))
    if seniority:
        query = query.where(RateBenchmark.seniority == seniority)
    if location:
        query = query.where(RateBenchmark.location.ilike(f"%{location}%"))
    if currency:
        query = query.where(RateBenchmark.currency == currency.upper())
    query = query.order_by(RateBenchmark.source_date.desc(), RateBenchmark.role).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post(
    "",
    response_model=RateBenchmarkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_benchmark(
    data: RateBenchmarkCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    row = RateBenchmark(**data.model_dump(), created_by=current_user.id)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


@router.patch("/{benchmark_id}", response_model=RateBenchmarkResponse)
async def update_benchmark(
    benchmark_id: int,
    data: RateBenchmarkUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(RateBenchmark).where(RateBenchmark.id == benchmark_id))
    if not row:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    await db.flush()
    await db.refresh(row)
    return row


@router.delete("/{benchmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_benchmark(
    benchmark_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(RateBenchmark).where(RateBenchmark.id == benchmark_id))
    if not row:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    await db.delete(row)


@router.post(
    "/import",
    response_model=RateBenchmarkImportResult,
    status_code=status.HTTP_200_OK,
)
async def import_benchmarks(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """Bulk import from CSV.

    Expected header (order-independent, case-insensitive):
        role, seniority, currency, rate_unit, market_min, market_median,
        market_max, source, source_date, location, notes

    `role`, `rate_unit`, `market_median`, `source`, `source_date` are required
    per row. Rows with missing required fields are reported in `errors` and
    counted in `skipped`.
    """
    if file.content_type not in (
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "text/plain",
        None,
    ):
        raise HTTPException(status_code=415, detail="Only CSV files are supported")
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1250", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    created = 0
    skipped = 0
    errors: list[str] = []

    for row_num, row in enumerate(reader, start=2):  # header is row 1
        lower_row = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        try:
            role = lower_row.get("role")
            rate_unit_str = (lower_row.get("rate_unit") or "").lower()
            median_str = lower_row.get("market_median")
            source = lower_row.get("source")
            source_date_str = lower_row.get("source_date")

            if not role or not rate_unit_str or not median_str or not source or not source_date_str:
                raise ValueError("missing required field (role/rate_unit/market_median/source/source_date)")

            seniority_val = lower_row.get("seniority")
            seniority_enum = SeniorityLevel(seniority_val) if seniority_val else None

            row_obj = RateBenchmark(
                role=role,
                seniority=seniority_enum,
                currency=(lower_row.get("currency") or "PLN").upper()[:3],
                rate_unit=RateUnit(rate_unit_str),
                market_min=int(lower_row["market_min"]) if lower_row.get("market_min") else None,
                market_median=int(median_str),
                market_max=int(lower_row["market_max"]) if lower_row.get("market_max") else None,
                source=source,
                source_date=date.fromisoformat(source_date_str),
                location=lower_row.get("location") or None,
                notes=lower_row.get("notes") or None,
                created_by=current_user.id,
            )
            db.add(row_obj)
            created += 1
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            errors.append(f"row {row_num}: {exc}")

    await db.flush()
    return RateBenchmarkImportResult(created=created, skipped=skipped, errors=errors)
