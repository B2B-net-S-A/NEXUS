"""Ustawienia → „Jakość generatora CV”: co rekruterzy zgłaszają przy pobraniu
oryginału po złym wyniku generatora (decyzja Artura 02.11.2026).

Zapis: ``POST …/cv/original/download-after-generator`` w ``candidate_stage_cv``.
Dostęp jak panel nowości: admin i Head of Recruitment.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generator_feedback import CvGeneratorFeedback
from app.models.job import Job
from app.models.user import User

router = APIRouter()

_ENTRIES_LIMIT = 100


class FeedbackCount(BaseModel):
    code: str
    count: int


class FeedbackClientCount(BaseModel):
    client_id: Optional[int]
    client_name: Optional[str]
    count: int


class FeedbackEntry(BaseModel):
    id: int
    created_at: datetime
    author_name: Optional[str]
    candidate_id: int
    candidate_name: str
    job_id: Optional[int]
    job_title: Optional[str]
    client_name: Optional[str]
    generation_status: str
    reasons: list[str]
    detail: Optional[str]


class FeedbackSummary(BaseModel):
    days: int
    total: int
    people: int
    generations_ready: int
    reasons: list[FeedbackCount]
    clients: list[FeedbackClientCount]
    entries: list[FeedbackEntry]


@router.get("/cv-generator/feedback/summary", response_model=FeedbackSummary)
async def generator_feedback_summary(
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
) -> FeedbackSummary:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                CvGeneratorFeedback,
                User.name,
                Candidate.name,
                Candidate.lastname,
                Job.title,
                Client.name,
            )
            .join(Candidate, Candidate.id == CvGeneratorFeedback.candidate_id)
            .outerjoin(User, User.id == CvGeneratorFeedback.created_by)
            .outerjoin(Job, Job.id == CvGeneratorFeedback.job_id)
            .outerjoin(Client, Client.id == CvGeneratorFeedback.client_id)
            .where(CvGeneratorFeedback.created_at >= since)
            .order_by(
                CvGeneratorFeedback.created_at.desc(), CvGeneratorFeedback.id.desc()
            )
        )
    ).all()
    generations_ready = int(
        await db.scalar(
            select(func.count())
            .select_from(CvGeneratedDocument)
            .where(
                CvGeneratedDocument.status == "ready",
                CvGeneratedDocument.created_at >= since,
            )
        )
        or 0
    )

    reasons: dict[str, int] = {}
    clients: dict[Optional[int], FeedbackClientCount] = {}
    people: set[int] = set()
    for feedback, *_names, client_name in rows:
        for code in feedback.reasons or []:
            reasons[code] = reasons.get(code, 0) + 1
        if feedback.created_by is not None:
            people.add(feedback.created_by)
        client = clients.setdefault(
            feedback.client_id,
            FeedbackClientCount(
                client_id=feedback.client_id, client_name=client_name, count=0
            ),
        )
        client.count += 1

    return FeedbackSummary(
        days=days,
        total=len(rows),
        people=len(people),
        generations_ready=generations_ready,
        reasons=[
            FeedbackCount(code=code, count=count)
            for code, count in sorted(reasons.items(), key=lambda kv: -kv[1])
        ],
        clients=sorted(clients.values(), key=lambda item: -item.count),
        entries=[
            FeedbackEntry(
                id=feedback.id,
                created_at=feedback.created_at,
                author_name=author,
                candidate_id=feedback.candidate_id,
                candidate_name=f"{first or ''} {last or ''}".strip(),
                job_id=feedback.job_id,
                job_title=job_title,
                client_name=client_name,
                generation_status=feedback.generation_status,
                reasons=list(feedback.reasons or []),
                detail=feedback.detail,
            )
            for feedback, author, first, last, job_title, client_name in rows[
                :_ENTRIES_LIMIT
            ]
        ],
    )
