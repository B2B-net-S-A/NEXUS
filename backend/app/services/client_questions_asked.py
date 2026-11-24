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
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.contact import Contact
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


@dataclass(frozen=True)
class BankRole:
    job_id: int
    title: str
    client_reference: str | None
    manager: str | None


@dataclass(frozen=True)
class BankQuestion:
    question: InterviewQuestion
    client_name: str | None
    roles: tuple[BankRole, ...]
    asked_count: int
    last_asked_at: datetime | None


async def question_bank(db: AsyncSession, *, job_scope: Any) -> list[BankQuestion]:
    """Rekrutacje → „Pytania z rozmów”: dawny Excel pytań, uzupełniany debriefami.

    Prośba Delivery Leadki z 24.11.2026: stanowisko, klient, manager i pytania
    bez duplikatów, z filtrami, bez ręcznego wpisywania. Wiersz = pytanie
    z banku klienta (unikalne po kliencie i treści), z debriefów
    (``client_debrief``) i z importu Excela (``legacy_import``). Rekrutacje przy
    pytaniu liczą się jak w ``questions_asked_in_job``: linia debriefu albo
    przypięcie z Excela. Manager = hiring manager tej rekrutacji.

    ``job_scope`` to warunek SQL na rekrutacje wołającego. Klient jest widoczny,
    gdy wołający czyta choć jedną jego rekrutację (jak ``client_id``
    w ``GET /interview-cycle/client-questions``); rekrutacje spoza zakresu nie
    trafiają do stanowisk ani do licznika.
    """
    client_ids = set(
        (
            await db.execute(
                select(Job.client_id)
                .where(Job.client_id.is_not(None), job_scope)
                .distinct()
            )
        ).scalars()
    )
    if not client_ids:
        return []
    questions = list(
        (
            await db.execute(
                select(InterviewQuestion)
                .where(
                    InterviewQuestion.client_id.in_(client_ids),
                    InterviewQuestion.source.in_(
                        (
                            InterviewQuestionSource.client_debrief,
                            InterviewQuestionSource.legacy_import,
                        )
                    ),
                )
                .order_by(InterviewQuestion.id)
            )
        ).scalars()
    )
    if not questions:
        return []
    title = job_display_title_expr()
    job_cols = (Job.id, title, Job.client_reference, Contact.name)
    roles_by_key: dict[tuple[int, str], dict[int, BankRole]] = defaultdict(dict)
    asked: dict[tuple[int, str], set[int]] = defaultdict(set)
    last_at: dict[tuple[int, str], datetime] = {}
    debriefs = await db.execute(
        select(
            *job_cols,
            Job.client_id,
            InterviewFeedback.id,
            InterviewFeedback.client_questions,
            InterviewFeedback.created_at,
        )
        .join(InterviewFeedback, InterviewFeedback.job_id == Job.id)
        .outerjoin(Contact, Contact.id == Job.hiring_manager_contact_id)
        .where(
            Job.client_id.in_(client_ids),
            job_scope,
            InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
            InterviewFeedback.client_questions.is_not(None),
        )
    )
    for job_id, job_title, ref, manager, client_id, fb_id, text, created_at in debriefs:
        role = BankRole(
            job_id=job_id, title=job_title, client_reference=ref, manager=manager
        )
        for line_hash in _line_hashes(text):
            key = (client_id, line_hash)
            roles_by_key[key][job_id] = role
            asked[key].add(fb_id)
            if created_at is not None and (
                key not in last_at or created_at > last_at[key]
            ):
                last_at[key] = created_at
    roles_by_question: dict[int, dict[int, BankRole]] = defaultdict(dict)
    excel_pins = await db.execute(
        select(JobQuestion.question_id, *job_cols)
        .join(Job, Job.id == JobQuestion.job_id)
        .outerjoin(Contact, Contact.id == Job.hiring_manager_contact_id)
        .where(
            JobQuestion.added_by_user_id.is_(None),
            JobQuestion.question_id.in_([q.id for q in questions]),
            job_scope,
        )
    )
    for question_id, job_id, job_title, ref, manager in excel_pins:
        roles_by_question[question_id][job_id] = BankRole(
            job_id=job_id, title=job_title, client_reference=ref, manager=manager
        )
    client_names = dict(
        (
            await db.execute(
                select(Client.id, Client.name).where(Client.id.in_(client_ids))
            )
        ).all()
    )
    out: list[BankQuestion] = []
    for q in questions:
        key = (q.client_id, q.normalized_text_hash)
        roles = {**roles_by_question.get(q.id, {}), **roles_by_key.get(key, {})}
        out.append(
            BankQuestion(
                question=q,
                client_name=client_names.get(q.client_id),
                roles=tuple(roles[j] for j in sorted(roles, reverse=True)),
                asked_count=len(asked.get(key, ())),
                last_asked_at=last_at.get(key),
            )
        )
    out.sort(key=lambda b: b.last_asked_at or b.question.created_at, reverse=True)
    return out
