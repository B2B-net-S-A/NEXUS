"""Arkusz screeningu Championa — tekst pytań przy odpowiedziach i rozmowy kandydata.

Arkusz żyje w ``candidate_stages.screening_answers`` (JSONB na wierszu etapu,
kopiowany przy ruchu karty). Pytania stoją w profilu Championa rekrutacji
z identyfikatorami POZYCYJNYMI (``q1…qN``), więc po edycji profilu zapisane
``question_id`` wskazuje inne pytanie. Od 02.10.2026 odpowiedź niesie własny
``question_text``, stemplowany przez serwer przy zapisie: profil kandydata,
dok na Tablicy i podpowiedzi w kolejnym arkuszu czytają pytanie z odpowiedzi,
a po identyfikatorze tylko dla arkuszy sprzed tej zmiany.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.schemas.champion import ScreeningAnswers
from app.services import champion_view
from app.services.client_identity import client_display_name_expression
from app.services.move_requirements import sheet_filled

logger = logging.getLogger(__name__)

# Treść arkusza — po niej poznajemy, czy zapis coś zmienił.
_ANSWER_CONTENT_KEYS = (
    "question_id",
    "response",
    "deal_breaker_hit",
    "origin",
    "keywords",
    "skipped",
)
_SHEET_CONTENT_KEYS = ("experience_checks", "overall_fit", "notes", "internal_note")


def question_texts(source: Any) -> dict[str, str]:
    """``{id: treść}`` pytań screeningowych z profilu Championa (dowolny kształt)."""

    out: dict[str, str] = {}
    for question in champion_view.screening_questions(source):
        if not isinstance(question, Mapping):
            continue
        question_id = str(question.get("id") or "").strip()
        text = str(question.get("question") or "").strip()
        if question_id and text:
            out[question_id] = text[:2000]
    return out


def _parsed(sheet: Any) -> Optional[ScreeningAnswers]:
    if not isinstance(sheet, dict) or not sheet:
        return None
    try:
        return ScreeningAnswers.model_validate(sheet)
    except ValidationError:
        return None


def _content(sheet: ScreeningAnswers) -> dict[str, Any]:
    data = sheet.model_dump(mode="json")
    return {
        "answers": [
            {key: answer.get(key) for key in _ANSWER_CONTENT_KEYS}
            for answer in data["answers"]
        ],
        **{key: data.get(key) for key in _SHEET_CONTENT_KEYS},
    }


def stamp_sheet(
    sheet: ScreeningAnswers,
    *,
    questions: Mapping[str, str],
    previous: Any,
    user_id: int,
    now: datetime,
) -> ScreeningAnswers:
    """Stempel serwera przed zapisem: tekst pytań oraz kto i kiedy.

    * ``question_text`` — z profilu Championa w chwili zapisu. Odpowiedź
      o niezmienionej treści zachowuje tekst zapisany wcześniej: profil mógł
      się od tego czasu zmienić, a kandydat odpowiadał na tamto pytanie.
    * ``answered_at``/``answered_by`` — zapis bez zmiany treści (ponowny zapis
      po ruchu karty) zostawia pierwotne „kto i kiedy”.

    ``question_text`` z żądania jest ignorowane. ``previous`` to arkusz pary
    sprzed zapisu (surowy JSONB) albo ``None``.
    """

    old = _parsed(previous)
    old_answers = {a.question_id: a for a in old.answers} if old else {}
    for answer in sheet.answers:
        before = old_answers.get(answer.question_id)
        unchanged = (
            before is not None
            and bool(before.question_text)
            and before.response.strip() == answer.response.strip()
            and before.skipped == answer.skipped
        )
        answer.question_text = (
            before.question_text if unchanged else questions.get(answer.question_id)
        )
    if (
        old is not None
        and old.answered_at is not None
        and _content(old) == _content(sheet)
    ):
        sheet.answered_at, sheet.answered_by = old.answered_at, old.answered_by
    else:
        sheet.answered_at, sheet.answered_by = now, user_id
    return sheet


def with_question_texts(sheet: Any, questions: Mapping[str, str]) -> Any:
    """Kopia arkusza z uzupełnionym tekstem pytań (arkusze sprzed 02.10.2026).

    Zapisany ``question_text`` wygrywa. Brak tekstu i brak pytania w profilu
    zostaje ``None`` — ekran mówi wtedy „pytanie usunięte z profilu”.
    """

    if not isinstance(sheet, dict):
        return sheet
    answers = sheet.get("answers")
    if not isinstance(answers, list):
        return sheet
    return {
        **sheet,
        "answers": [
            {
                **answer,
                "question_text": answer.get("question_text")
                or questions.get(str(answer.get("question_id") or "").strip()),
            }
            if isinstance(answer, dict)
            else answer
            for answer in answers
        ],
    }


def _moment(value: Any) -> Optional[datetime]:
    """Znacznik czasu z JSONB albo z kolumny — zawsze ze strefą (sortowanie)."""

    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def candidate_conversations(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_scope: Optional[ColumnElement[bool]] = None,
    exclude_job_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Rozmowy screeningowe kandydata: jeden arkusz na rekrutację, najnowsze pierwsze.

    Arkusz jest kopiowany przy ruchu karty, więc rekrutację reprezentuje jej
    NAJNOWSZY wypełniony wiersz (ta sama reguła co odczyt arkusza na Tablicy).
    Stała liczba zapytań: wiersze etapów, rekrutacje z klientami, autorzy.
    ``job_scope`` to klauzula zakresu odczytu wołającego
    (`job_read_scope_clause`); bez niej zwracane są wszystkie rekrutacje.
    """

    query = (
        select(
            CandidateStage.id,
            CandidateStage.job_id,
            CandidateStage.screening_answers,
            CandidateStage.moved_at,
        )
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.screening_answers.isnot(None),
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
    )
    if job_scope is not None:
        query = query.where(job_scope)
    if exclude_job_id is not None:
        query = query.where(CandidateStage.job_id != exclude_job_id)

    picked: dict[int, tuple[int, ScreeningAnswers, dict, Optional[datetime]]] = {}
    for stage_id, job_id, raw, moved_at in (await db.execute(query)).all():
        if job_id in picked or not sheet_filled(raw):
            continue
        sheet = _parsed(raw)
        if sheet is None:
            logger.warning("screening sheet unreadable stage=%s", stage_id)
            continue
        picked[job_id] = (stage_id, sheet, raw, moved_at)
    if not picked:
        return []

    jobs = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    Job.id,
                    Job.title,
                    Job.champion_profile,
                    client_display_name_expression().label("client_name"),
                )
                .outerjoin(Client, Client.id == Job.client_id)
                .where(Job.id.in_(sorted(picked)))
            )
        ).all()
    }
    author_ids = sorted(
        {sheet.answered_by for _, sheet, _, _ in picked.values() if sheet.answered_by}
    )
    authors: dict[int, str] = {}
    if author_ids:
        authors = {
            row.id: row.name
            for row in (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(author_ids))
                )
            ).all()
        }

    conversations: list[dict[str, Any]] = []
    for job_id, (stage_id, sheet, raw, moved_at) in picked.items():
        job = jobs.get(job_id)
        texts = question_texts(job.champion_profile if job else None)
        data = with_question_texts(sheet.model_dump(mode="json"), texts)
        when = _moment(raw.get("answered_at")) or _moment(moved_at)
        conversations.append(
            {
                "stage_id": stage_id,
                "job_id": job_id,
                "job_title": job.title if job else None,
                "client_name": job.client_name if job else None,
                "answered_at": when,
                "answered_by_name": authors.get(sheet.answered_by or 0),
                "overall_fit": sheet.overall_fit,
                "match_percent": sheet.match_percent(),
                "answers": data["answers"],
                "experience_checks": data["experience_checks"],
                "notes": sheet.notes,
                "internal_note": sheet.internal_note,
            }
        )
    conversations.sort(
        key=lambda c: (c["answered_at"] is not None, c["answered_at"], c["stage_id"]),
        reverse=True,
    )
    return conversations
