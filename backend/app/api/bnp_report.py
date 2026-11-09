"""Raport miesięczny BNP na karcie klienta (szablon banku, dwa arkusze)."""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import user_can_view_client_rate
from app.api.deps import require_onboarded_user
from app.api.jobs import (
    _maybe_embed_job,
    job_opened_effective_expr,
    jobs_opened_clauses,
)
from app.api.permission_access import RecruitmentManageUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_framework_contract_chunk import ClientFrameworkContractChunk
from app.models.contract import RateUnit
from app.models.job import Job, JobStatus, Seniority
from app.models.pipeline_template import RejectionReason
from app.models.rate_card import RateCard
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)
from app.services.auto_match_outbox import enqueue_job_safe
from app.services.bnp_report.calculations import (
    BNP_REPORT_CLIENT_IDS,
    SENIORITY_LABELS,
    RateBand,
    ReportJob,
    ReportRow,
    StageEvent,
    build_row,
)
from app.services.bnp_report.rate_annex import parse_rate_annex
from app.services.bnp_report.workbook import build_workbook, report_filename
from app.services.job_matching_refresh import mark_latest_snapshot_stale
from app.services.marketplace_service import run_marketplace_scan_safe
from app.services.match_score_cache import mark_stale_for_job

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
RATE_DENIED = "Raport zawiera stawki do klienta, których Twoja rola nie widzi."


def require_client_rate_viewer(
    user: Annotated[User, Depends(require_onboarded_user)],
) -> User:
    if not user_can_view_client_rate(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, RATE_DENIED)
    return user


ClientRateViewer = Annotated[User, Depends(require_client_rate_viewer)]


class JobReportFields(BaseModel):
    start: Optional[date] = None
    client_reference: Optional[str] = Field(default=None, max_length=120)
    seniority: Optional[Seniority] = None
    rate_card_id: Optional[int] = None


class RateBandInput(BaseModel):
    role: str = Field(min_length=1, max_length=255)
    minimum: int = Field(ge=1, le=5000)
    maximum: int = Field(ge=1, le=5000)

    @field_validator("role")
    @classmethod
    def _strip_role(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Nazwa roli nie może być pusta.")
        return cleaned


class RateBandsInput(BaseModel):
    bands: list[RateBandInput] = Field(min_length=1, max_length=200)


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise HTTPException(422, "Miesiąc musi mieć postać RRRR-MM.") from exc
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, next_month - timedelta(days=1)


async def _ensure_report_client(db: AsyncSession, user: User, client_id: int) -> None:
    if client_id not in BNP_REPORT_CLIENT_IDS:
        raise HTTPException(404, "Ten klient nie ma raportu miesięcznego.")
    assert_delivery_lead_client_visible(
        client_id, await resolve_delivery_lead_client_ids(user, db)
    )


async def _saved_bands(db: AsyncSession, client_id: int) -> list[RateBand]:
    today = business_today()
    cards = await db.scalars(
        select(RateCard)
        .where(
            RateCard.client_id == client_id,
            RateCard.rate_unit == RateUnit.hourly,
            RateCard.rate_client_min.is_not(None),
            RateCard.rate_client_max.is_not(None),
            (RateCard.valid_from.is_(None)) | (RateCard.valid_from <= today),
            (RateCard.valid_to.is_(None)) | (RateCard.valid_to >= today),
        )
        .order_by(RateCard.role)
    )
    return [
        RateBand(card.id, card.role, card.rate_client_min, card.rate_client_max)
        for card in cards
    ]


async def _bands_from_contract(db: AsyncSession, client_id: int) -> list[RateBand]:
    """Tabela widełek z aktywnej umowy ramowej; propozycja do sprawdzenia."""
    rows = (
        await db.execute(
            select(
                ClientFrameworkContractChunk.amendment_id,
                ClientFrameworkContractChunk.text,
            )
            .join(
                ClientFrameworkContract,
                ClientFrameworkContract.id
                == ClientFrameworkContractChunk.framework_contract_id,
            )
            .where(
                ClientFrameworkContract.client_id == client_id,
                ClientFrameworkContract.status == FrameworkContractStatus.active,
            )
            .order_by(
                ClientFrameworkContractChunk.amendment_id.asc().nulls_first(),
                ClientFrameworkContractChunk.chunk_index,
            )
        )
    ).all()
    agreement = " ".join(text for amendment, text in rows if amendment is None)
    amendments: dict[int, list[str]] = {}
    for amendment, text in rows:
        if amendment is not None:
            amendments.setdefault(amendment, []).append(text)
    parsed = parse_rate_annex(agreement, [" ".join(parts) for parts in amendments.values()])
    return [RateBand(None, row.role, row.minimum, row.maximum) for row in parsed]


async def _load_report(
    db: AsyncSession, client_id: int, month: str
) -> tuple[list[ReportRow], list[RateBand], Literal["saved", "contract", "none"]]:
    first, last = _month_bounds(month)
    jobs = list(
        await db.scalars(
            select(Job)
            .where(
                Job.client_id == client_id,
                Job.status != JobStatus.draft,
                *jobs_opened_clauses(first, last),
            )
            .order_by(job_opened_effective_expr(), Job.id)
        )
    )
    bands = await _saved_bands(db, client_id)
    source: Literal["saved", "contract", "none"] = "saved"
    if not bands:
        bands = await _bands_from_contract(db, client_id)
        source = "contract" if bands else "none"

    events: dict[int, list[StageEvent]] = {job.id: [] for job in jobs}
    if jobs:
        stage_rows = await db.execute(
            select(
                CandidateStage.job_id,
                CandidateStage.candidate_id,
                CandidateStage.stage,
                CandidateStage.ended_by,
                CandidateStage.moved_at,
                CandidateStage.client_rate_value,
                CandidateStage.client_rate_unit,
                CandidateStage.client_rate_currency,
                CandidateStage.expected_rate_value,
                CandidateStage.expected_rate_unit,
                CandidateStage.expected_rate_currency,
                RejectionReason.name.label("rejection_reason"),
            )
            .outerjoin(
                RejectionReason, RejectionReason.id == CandidateStage.rejection_reason_id
            )
            .where(CandidateStage.job_id.in_(list(events)))
            .order_by(CandidateStage.moved_at, CandidateStage.id)
        )
        for row in stage_rows:
            events[row.job_id].append(
                StageEvent(
                    candidate_id=row.candidate_id,
                    stage=row.stage,
                    ended_by=row.ended_by,
                    moved_at=row.moved_at,
                    client_rate_value=row.client_rate_value,
                    client_rate_unit=row.client_rate_unit,
                    client_rate_currency=row.client_rate_currency,
                    expected_rate_value=row.expected_rate_value,
                    expected_rate_unit=row.expected_rate_unit,
                    expected_rate_currency=row.expected_rate_currency,
                    rejection_reason=row.rejection_reason,
                )
            )

    report_rows = [
        build_row(
            ReportJob(
                id=job.id,
                title=job.title,
                working_title=job.working_title,
                description=job.description,
                client_reference=job.client_reference,
                seniority=job.seniority,
                client_rate_card_id=job.client_rate_card_id,
                opened_on=_warsaw_date(job.opened_at or job.created_at),
                closed_on=_warsaw_date(job.closed_at) if job.closed_at else None,
                budget_hourly=(
                    float(job.rate_budget_hourly)
                    if job.rate_budget_hourly is not None
                    else None
                ),
            ),
            events[job.id],
            bands,
        )
        for job in jobs
    ]
    return report_rows, bands, source


def _warsaw_date(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


def _row_payload(row: ReportRow) -> dict:
    return {
        "job_id": row.job_id,
        "title": row.title,
        "start": row.start,
        "closed": row.closed,
        "sla": row.sla,
        "ritm": row.ritm,
        "ritm_source": row.ritm_source,
        "role": row.role,
        "seniority": row.seniority.value if row.seniority else None,
        "seniority_label": row.seniority_label,
        "seniority_source": row.seniority_source,
        "rate_card_id": row.rate_card_id,
        "contract_role": row.contract_role,
        "contract_role_source": row.contract_role_source,
        "cv": row.cv,
        "cv_sla": row.cv_sla,
        "cv_in_budget": row.cv_in_budget,
        "percent_cv_sla": row.percent_cv_sla,
        "ritm_sla": row.ritm_sla,
        "ritm_sla_and_budget": row.ritm_sla_and_budget,
        "rejected_cv": row.rejected_cv,
        "meetings": row.meetings,
        "rejected_after_meeting": row.rejected_after_meeting,
        "meetings_per_cv": row.meetings_per_cv,
        "rejected_per_cv": row.rejected_per_cv,
        "offers": row.offers,
        "offer_min_md": row.offer_min_md,
        "offer_max_md": row.offer_max_md,
        "band_min_md": row.band_min_md,
        "band_max_md": row.band_max_md,
        "band_average_md": row.band_average_md,
        "recommended_average_md": row.recommended_average_md,
        "percent_from_band_average": row.percent_from_band_average,
        "offer_min_minus_top": row.offer_min_minus_top,
        "percent_difference": row.percent_difference,
        "needs_attention": row.needs_attention,
    }


MonthParam = Annotated[str, Query(pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")]


@router.get("/{client_id}/bnp-report/availability")
async def report_availability(
    client_id: int,
    current_user: ClientRateViewer,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Czy pokazać przycisk raportu: bez 404 i 403 dla zwykłego klienta."""
    if client_id not in BNP_REPORT_CLIENT_IDS:
        return {"available": False}
    allowed = await resolve_delivery_lead_client_ids(current_user, db)
    return {"available": allowed is None or client_id in allowed}


@router.get("/{client_id}/bnp-report")
async def get_report(
    client_id: int,
    month: MonthParam,
    current_user: ClientRateViewer,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_report_client(db, current_user, client_id)
    rows, bands, source = await _load_report(db, client_id, month)
    return {
        "month": month,
        "rows": [_row_payload(row) for row in rows],
        "bands": [
            {
                "id": band.id,
                "role": band.role,
                "minimum": band.minimum,
                "maximum": band.maximum,
                "average": band.average,
            }
            for band in bands
        ],
        "bands_source": source,
        "seniority_options": [
            {"value": value.value, "label": label}
            for value, label in SENIORITY_LABELS.items()
        ],
    }


@router.get("/{client_id}/bnp-report/export")
async def export_report(
    client_id: int,
    month: MonthParam,
    current_user: ClientRateViewer,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _ensure_report_client(db, current_user, client_id)
    rows, _bands, _source = await _load_report(db, client_id, month)
    filename = report_filename(month)
    return Response(
        content=build_workbook(rows),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


async def refresh_matching_after_seniority(
    job: Job, db: AsyncSession, background_tasks: BackgroundTasks
) -> None:
    """Seniority wchodzi do wektora i rankingu: te same skutki co `PATCH /api/jobs`."""
    await _maybe_embed_job(job.id, db)
    await mark_stale_for_job(db, job.id)
    await db.commit()
    await mark_latest_snapshot_stale(job.id, db)
    if settings.MARKETPLACE_ENABLED:
        background_tasks.add_task(run_marketplace_scan_safe, job.id)
    if job.status == JobStatus.published:
        background_tasks.add_task(enqueue_job_safe, job.id)


@router.patch("/{client_id}/bnp-report/jobs/{job_id}")
async def update_job_fields(
    client_id: int,
    job_id: int,
    data: JobReportFields,
    current_user: RecruitmentManageUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Braki raportu zapisują się w rekrutacji, żeby kolejny miesiąc miał je gotowe."""
    await _ensure_report_client(db, current_user, client_id)
    job = await db.scalar(
        select(Job).where(Job.id == job_id, Job.client_id == client_id).with_for_update()
    )
    if job is None:
        raise HTTPException(404, "Nie znaleziono rekrutacji tego klienta.")
    fields = data.model_fields_set
    if "start" in fields:
        if data.start is None or data.start > business_today():
            raise HTTPException(422, "Data startu nie może być pusta ani z przyszłości.")
        job.opened_at = datetime.combine(data.start, time(12), tzinfo=ZoneInfo(DEFAULT_TZ))
    if "client_reference" in fields:
        job.client_reference = (data.client_reference or "").strip() or None
    seniority_changed = "seniority" in fields and job.seniority != data.seniority
    if seniority_changed:
        job.seniority = data.seniority
    if "rate_card_id" in fields:
        if data.rate_card_id is not None:
            owner = await db.scalar(
                select(RateCard.client_id).where(RateCard.id == data.rate_card_id)
            )
            if owner != client_id:
                raise HTTPException(422, "Ta rola nie należy do widełek tego klienta.")
        job.client_rate_card_id = data.rate_card_id
    await db.flush()
    if seniority_changed:
        await db.commit()
        await refresh_matching_after_seniority(job, db, background_tasks)
    return {"ok": True}


@router.put("/{client_id}/bnp-report/rate-bands")
async def save_rate_bands(
    client_id: int,
    data: RateBandsInput,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Zapis widełek po sprawdzeniu: wiersz na rolę, istniejąca rola się nadpisuje."""
    await _ensure_report_client(db, current_user, client_id)
    for band in data.bands:
        if band.minimum > band.maximum:
            raise HTTPException(422, f"Rola „{band.role}”: minimum większe niż maksimum.")
    existing = {
        card.role.lower(): card
        for card in await db.scalars(
            select(RateCard).where(
                RateCard.client_id == client_id,
                RateCard.seniority.is_(None),
                RateCard.valid_from.is_(None),
                func.lower(RateCard.role).in_([b.role.lower() for b in data.bands]),
            )
        )
    }
    # Karta z inną jednostką należy do cennika kontraktów; nie zmieniamy jej po cichu.
    foreign = [c.role for c in existing.values() if c.rate_unit != RateUnit.hourly]
    if foreign:
        raise HTTPException(
            409, f"Rola „{foreign[0]}” ma już w karcie stawek inną jednostkę niż zł/h."
        )
    for band in data.bands:
        card = existing.get(band.role.lower())
        if card is None:
            card = RateCard(client_id=client_id, role=band.role, rate_unit=RateUnit.hourly)
            db.add(card)
            existing[band.role.lower()] = card
        card.currency = "PLN"
        card.rate_client_min = band.minimum
        card.rate_client_max = band.maximum
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "Widełki zapisał przed chwilą ktoś inny. Odśwież okno.") from exc
    return {"saved": len(data.bands)}
