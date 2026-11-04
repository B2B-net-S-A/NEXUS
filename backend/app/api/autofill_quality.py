"""„Jakość podpowiedzi systemu” — ekran Insights (silnik „Nowi na 20”, 23.10.2026).

Liczby (``GET /summary``) i raporty poniedziałkowe (``GET /reports``) czyta
każdy z dostępem do sekcji Insights — to agregaty bez nazwisk kandydatów.
Decyzję „Robimy / Nie” przy propozycji zapisuje admin albo Head of
Recruitment (``POST …/decision``). Logika: ``services/autofill_quality.py``.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, HeadOfRecruitmentPlus
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.autofill_quality_report import AutofillQualityReport
from app.services import autofill_quality

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)


def _report_out(report: AutofillQualityReport) -> dict:
    return {
        "id": report.id,
        "week_start": report.week_start.isoformat(),
        "summary": report.summary,
        "proposals": report.proposals,
        "from_model": report.from_model,
        "created_at": report.created_at,
    }


@router.get("/summary")
async def autofill_quality_summary(
    _user: CurrentUser,
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """Liczby ostatnich ``days`` dni (ekran B2)."""
    now = datetime.now(timezone.utc)
    return await autofill_quality.summary(
        db, since=now - timedelta(days=days), until=now, now=now
    )


@router.get("/reports")
async def autofill_quality_reports(
    _user: CurrentUser,
    limit: int = Query(8, ge=1, le=52),
    db: AsyncSession = Depends(get_db),
):
    """Ostatnie raporty poniedziałkowe, najnowszy pierwszy (ekran B3)."""
    rows = (
        await db.scalars(
            select(AutofillQualityReport)
            .order_by(AutofillQualityReport.week_start.desc())
            .limit(limit)
        )
    ).all()
    return {"items": [_report_out(r) for r in rows]}


class ProposalDecision(BaseModel):
    decision: Optional[Literal["yes", "no"]] = None


@router.post("/reports/{report_id}/proposals/{index}/decision")
async def decide_proposal(
    report_id: int,
    index: int,
    data: ProposalDecision,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """„Robimy” / „Nie” przy propozycji; ``null`` cofa decyzję."""
    report = await db.get(AutofillQualityReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego raportu.")
    proposals = list(report.proposals or [])
    if not 0 <= index < len(proposals):
        raise HTTPException(status_code=404, detail="Nie ma takiej propozycji.")
    proposals[index] = {
        **proposals[index],
        "decision": data.decision,
        "decided_by": user.id if data.decision else None,
        "decided_at": datetime.now(timezone.utc).isoformat() if data.decision else None,
    }
    # Nowa lista: JSONB bez MutableList nie widzi zmiany w miejscu.
    report.proposals = proposals
    await db.commit()
    return _report_out(report)
