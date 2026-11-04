"""Pytania zadane na rozmowach — pod rekrutacją i w całej liście klienta.

Zgłoszenie 02.11.2026: pod każdą rekrutacją klienta stała ta sama lista
najnowszych pytań całego klienta (u Nordei przy Project Managerze pytania
z Javy), więc nie było wiadomo, o co pytano naprawdę.

Co liczy się jako „zadane w tej rekrutacji”:

* linia debriefu tej rekrutacji (``InterviewFeedback.client_questions``) — to,
  co rekruter usłyszał od kandydata; poprawa debriefu zdejmuje pytanie;
* przypięcie importu Excela (``added_by_user_id IS NULL``) — arkusz przypisał
  pytanie do tej rekrutacji po numerze albo tytule.

Samo przypięcie przez człowieka nie wystarcza: Baza pytań i kopia rekrutacji
z szablonu też zakładają ``JobQuestion``, ale to znaczy „warto zapytać”.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionSource,
    JobQuestion,
)
from app.models.job import Job
from app.services.job_working_title import job_display_title_expr

_WHITESPACE_RE = re.compile(r"\s+")


def question_hash(text: str) -> str:
    norm = _WHITESPACE_RE.sub(" ", text.strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _line_hashes(value: str | None) -> set[str]:
    return {question_hash(line) for line in (value or "").splitlines() if line.strip()}


@dataclass(frozen=True)
class RecruitmentLabel:
    id: int
    title: str


@dataclass(frozen=True)
class ClientQuestionWithJobs:
    question: InterviewQuestion
    jobs: tuple[RecruitmentLabel, ...]


async def questions_asked_in_job(
    db: AsyncSession, *, job_id: int, client_id: int, limit: int
) -> list[InterviewQuestion]:
    """Pytania zadane na rozmowach w tej rekrutacji, najnowsze pierwsze."""
    debriefs = (
        await db.execute(
            select(InterviewFeedback.client_questions).where(
                InterviewFeedback.job_id == job_id,
                InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
                InterviewFeedback.client_questions.is_not(None),
            )
        )
    ).scalars()
    hashes: set[str] = set()
    for text in debriefs:
        hashes |= _line_hashes(text)
    excel_pins = select(JobQuestion.question_id).where(
        JobQuestion.job_id == job_id,
        JobQuestion.added_by_user_id.is_(None),
    )
    rows = await db.execute(
        select(InterviewQuestion)
        .where(
            InterviewQuestion.client_id == client_id,
            or_(
                InterviewQuestion.normalized_text_hash.in_(hashes),
                InterviewQuestion.id.in_(excel_pins),
            ),
        )
        .order_by(InterviewQuestion.created_at.desc(), InterviewQuestion.id.desc())
        .limit(limit)
    )
    return list(rows.scalars())


async def client_questions_with_jobs(
    db: AsyncSession, *, client_id: int, job_scope: Any, limit: int
) -> list[ClientQuestionWithJobs]:
    """Pytania klienta z debriefów, a przy każdym rekrutacje, w których padły.

    ``job_scope`` to warunek SQL na rekrutacje, które wolno pokazać pytającemu.
    Archiwum (``legacy_import``) tu nie wchodzi: dociera wyłącznie po roli
    (``client_question_archive``), a u Nordei to ponad tysiąc pozycji.
    """
    questions = list(
        (
            await db.execute(
                select(InterviewQuestion)
                .where(
                    InterviewQuestion.client_id == client_id,
                    InterviewQuestion.source == InterviewQuestionSource.client_debrief,
                )
                .order_by(
                    InterviewQuestion.created_at.desc(), InterviewQuestion.id.desc()
                )
                .limit(limit)
            )
        ).scalars()
    )
    if not questions:
        return []
    title = job_display_title_expr()
    debriefs = await db.execute(
        select(Job.id, title, InterviewFeedback.client_questions)
        .join(InterviewFeedback, InterviewFeedback.job_id == Job.id)
        .where(
            Job.client_id == client_id,
            job_scope,
            InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
            InterviewFeedback.client_questions.is_not(None),
        )
    )
    jobs_by_hash: dict[str, dict[int, str]] = defaultdict(dict)
    for job_id, job_title, text in debriefs:
        for line_hash in _line_hashes(text):
            jobs_by_hash[line_hash][job_id] = job_title
    return [
        ClientQuestionWithJobs(
            question=q,
            jobs=tuple(
                RecruitmentLabel(id=job_id, title=job_title)
                for job_id, job_title in sorted(
                    jobs_by_hash.get(q.normalized_text_hash, {}).items(), reverse=True
                )
            ),
        )
        for q in questions
    ]
